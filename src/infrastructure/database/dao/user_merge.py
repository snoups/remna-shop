from datetime import timezone
from hashlib import sha256
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Text,
    and_,
    case,
    cast,
    delete,
    func,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import ARRAY, array
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from src.application.common.dao.payment_operation import PaymentOperationStatus
from src.application.common.dao.user_merge import (
    EmailConflictResolution,
    PaymentConflictResolution,
    TelegramConflictResolution,
    UserMergeDao,
    UserMergeNotFoundError,
    UserMergePaymentOperationConflictError,
    UserMergePlan,
    UserMergeReferralAttributionConflictError,
    UserMergeTargetConflictError,
    UserMergeTargetSnapshot,
)
from src.application.dto import UserDto
from src.core.enums import ReferralRewardState, TransactionFulfillmentStatus
from src.core.utils.time import datetime_now
from src.infrastructure.database.models import (
    PaymentOperation,
    Referral,
    ReferralReward,
    Subscription,
    Transaction,
    User,
    UserMergeAudit,
    UserOAuthProvider,
)
from src.infrastructure.database.referral_graph import (
    acquire_referral_graph_lock,
    referral_path_statement,
)


class UserMergeDaoImpl(UserMergeDao):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _resolve_merged_email_identity(
        *,
        source_email: str | None,
        source_verified: bool,
        target_email: str | None,
        target_verified: bool,
    ) -> tuple[str | None, bool]:
        if target_email is not None:
            # Verification is evidence about a concrete address, not an
            # account-wide flag. Source evidence applies only when it names the
            # exact same selected address; a different KEEP_TARGET address keeps
            # only the target's own verification evidence.
            return target_email, bool(
                target_verified
                or (source_email == target_email and source_verified)
            )
        return source_email, bool(source_email is not None and source_verified)

    async def plan(
        self,
        source_user_id: int,
        target_user_id: int,
        *,
        email_resolution: EmailConflictResolution = EmailConflictResolution.REJECT,
        telegram_resolution: TelegramConflictResolution = TelegramConflictResolution.REJECT,
        payment_resolution: PaymentConflictResolution = PaymentConflictResolution.REJECT,
    ) -> UserMergePlan:
        source, target = await self._lock_users(source_user_id, target_user_id)
        existing_merge = await self._existing_merge_plan(source, target)
        if existing_merge is not None:
            return existing_merge
        self._assert_canonical_merge_target(target)
        await self._lock_nonterminal_referral_rewards(source.id, target.id)
        await self._normalize_stale_payment_work(source.id, target.id)
        moved = await self._collect_moved_counts(source.id, target.id)
        return UserMergePlan(
            source_user_id=source_user_id,
            target_user_id=target_user_id,
            target=self._target_snapshot(target),
            moved=moved,
            conflicts=self._validate(
                source,
                target,
                email_resolution=email_resolution,
                telegram_resolution=telegram_resolution,
                payment_resolution=payment_resolution,
                payment_operation_duplicates=moved["payment_operation_duplicates"],
                active_payment_operations=moved.get("active_payment_operations", 0),
                fulfillment_processing=moved.get("fulfillment_processing", 0),
                referral_reward_attribution_conflicts=moved.get(
                    "referral_reward_attribution_conflicts", 0
                ),
                active_referral_rewards=moved.get("active_referral_rewards", 0),
            ),
        )

    async def merge(
        self,
        *,
        actor: UserDto,
        source_user_id: int,
        target_user_id: int,
        reason: str,
        email_resolution: EmailConflictResolution = EmailConflictResolution.REJECT,
        telegram_resolution: TelegramConflictResolution = TelegramConflictResolution.REJECT,
        payment_resolution: PaymentConflictResolution = PaymentConflictResolution.REJECT,
    ) -> UserMergePlan:
        source, target = await self._lock_users(source_user_id, target_user_id)
        existing_merge = await self._existing_merge_plan(source, target)
        if existing_merge is not None:
            return existing_merge
        self._assert_canonical_merge_target(target)
        await self._lock_nonterminal_referral_rewards(source.id, target.id)
        await self._normalize_stale_payment_work(source.id, target.id)
        await self._assert_no_active_payment_work(source.id, target.id)
        await self._assert_no_active_referral_reward_work(source.id, target.id)
        await self._assert_no_referral_reward_attribution_conflicts(source.id, target.id)
        if payment_resolution is PaymentConflictResolution.REKEY_SOURCE:
            await self._rekey_source_payment_operation_collisions(source.id, target.id)
        else:
            await self._assert_no_payment_operation_collisions(source.id, target.id)
        moved = await self._collect_moved_counts(source.id, target.id)
        await self._merge_records(
            source,
            target,
            moved,
            email_resolution=email_resolution,
            telegram_resolution=telegram_resolution,
        )
        self.session.add(
            UserMergeAudit(
                actor_user_id=None if actor.id < 0 else actor.id,
                actor_role=actor.role.name,
                source_user_id=source.id,
                target_user_id=target.id,
                reason=reason,
                dry_run=False,
                moved=moved,
                conflicts=[],
            )
        )
        return UserMergePlan(
            source_user_id=source_user_id,
            target_user_id=target_user_id,
            target=self._target_snapshot(target),
            moved=moved,
            conflicts=[],
        )

    async def _existing_merge_plan(
        self,
        source: User,
        target: User,
    ) -> UserMergePlan | None:
        merged_target_id = source.merged_into_user_id
        if merged_target_id is None:
            return None
        if merged_target_id != target.id:
            raise UserMergeTargetConflictError(
                f"Source user '{source.id}' is already merged into user "
                f"'{merged_target_id}' and cannot be redirected to user '{target.id}'"
            )

        # A retry must describe the original operation, not the now-empty source.
        # Keep using the first successful audit entry so accidental historical
        # duplicate entries cannot make the response change between retries.
        stmt = (
            select(UserMergeAudit.moved)
            .where(
                UserMergeAudit.source_user_id == source.id,
                UserMergeAudit.target_user_id == target.id,
                UserMergeAudit.dry_run.is_(False),
            )
            .order_by(UserMergeAudit.id.asc())
            .limit(1)
        )
        persisted_moved = await self.session.scalar(stmt)
        moved = (
            {
                key: value
                for key, value in persisted_moved.items()
                if isinstance(key, str) and isinstance(value, int) and not isinstance(value, bool)
            }
            if isinstance(persisted_moved, dict)
            else {}
        )
        return UserMergePlan(
            source_user_id=source.id,
            target_user_id=target.id,
            target=self._target_snapshot(target),
            moved=moved,
            conflicts=[],
        )

    async def _lock_users(self, source_user_id: int, target_user_id: int) -> tuple[User, User]:
        await acquire_referral_graph_lock(self.session)
        ordered_ids = sorted([source_user_id, target_user_id])
        stmt = select(User).where(User.id.in_(ordered_ids)).order_by(User.id).with_for_update()
        users = list((await self.session.scalars(stmt)).all())
        by_id = {user.id: user for user in users}
        source = by_id.get(source_user_id)
        target = by_id.get(target_user_id)
        if source is None:
            raise UserMergeNotFoundError(f"Source user '{source_user_id}' not found")
        if target is None:
            raise UserMergeNotFoundError(f"Target user '{target_user_id}' not found")
        return source, target

    @staticmethod
    def _assert_canonical_merge_target(target: User) -> None:
        if target.merged_into_user_id is not None:
            raise UserMergeTargetConflictError(
                f"Target user '{target.id}' is already merged into user "
                f"'{target.merged_into_user_id}'; merge into the canonical target instead"
            )

    def _validate(
        self,
        source: User,
        target: User,
        *,
        payment_operation_duplicates: int = 0,
        active_payment_operations: int = 0,
        fulfillment_processing: int = 0,
        referral_reward_attribution_conflicts: int = 0,
        active_referral_rewards: int = 0,
        email_resolution: EmailConflictResolution = EmailConflictResolution.REJECT,
        telegram_resolution: TelegramConflictResolution = TelegramConflictResolution.REJECT,
        payment_resolution: PaymentConflictResolution = PaymentConflictResolution.REJECT,
    ) -> list[str]:
        conflicts: list[str] = []
        if (
            target.email
            and source.email
            and target.email != source.email
            and email_resolution is EmailConflictResolution.REJECT
        ):
            conflicts.append("Both users have different emails")
        if (
            target.telegram_id is not None
            and source.telegram_id is not None
            and target.telegram_id != source.telegram_id
            and telegram_resolution is TelegramConflictResolution.REJECT
        ):
            conflicts.append("Both users have different Telegram accounts")
        if target.current_subscription_id and source.current_subscription_id:
            conflicts.append("Both users have current subscriptions")
        if payment_operation_duplicates and payment_resolution is PaymentConflictResolution.REJECT:
            conflicts.append(
                "Payment idempotency key collision between source and target "
                f"({payment_operation_duplicates})"
            )
        if active_payment_operations:
            conflicts.append(
                f"Source user has active payment operations ({active_payment_operations})"
            )
        if fulfillment_processing:
            conflicts.append(
                f"Source user has payment fulfillment in progress ({fulfillment_processing})"
            )
        if referral_reward_attribution_conflicts:
            conflicts.append(
                "Merge has incompatible referral attribution "
                f"({referral_reward_attribution_conflicts})"
            )
        if active_referral_rewards:
            conflicts.append(
                f"Source user has referral reward issuance in progress ({active_referral_rewards})"
            )
        return conflicts

    async def _collect_moved_counts(
        self, source_user_id: int, target_user_id: int
    ) -> dict[str, int]:
        return {
            "subscriptions": await self._count(
                Subscription, Subscription.user_id == source_user_id
            ),
            "transactions": await self._count(Transaction, Transaction.user_id == source_user_id),
            "payment_operations": await self._count(
                PaymentOperation, PaymentOperation.user_id == source_user_id
            ),
            "payment_operation_duplicates": await self._count_payment_operation_duplicates(
                source_user_id, target_user_id
            ),
            "active_payment_operations": await self._count(
                PaymentOperation,
                PaymentOperation.user_id.in_((source_user_id, target_user_id)),
                or_(
                    PaymentOperation.status.in_(
                        (
                            PaymentOperationStatus.CLAIMED.value,
                            PaymentOperationStatus.PROCESSING.value,
                        )
                    ),
                    PaymentOperation.reconcile_token_hash.is_not(None),
                ),
            ),
            "fulfillment_processing": await self._count(
                Transaction,
                Transaction.user_id.in_((source_user_id, target_user_id)),
                or_(
                    Transaction.fulfillment_status == TransactionFulfillmentStatus.PROCESSING,
                    Transaction.fulfillment_token_hash.is_not(None),
                ),
            ),
            "referrals_as_referrer": await self._count(
                Referral, Referral.referrer_id == source_user_id
            ),
            "referrals_as_referred": await self._count(
                Referral, Referral.referred_id == source_user_id
            ),
            "referral_rewards": await self._count(
                ReferralReward, ReferralReward.user_id == source_user_id
            ),
            "active_referral_rewards": await self._count(
                ReferralReward,
                self._nonterminal_referral_reward_predicate(
                    source_user_id,
                    target_user_id,
                ),
            ),
            "referral_reward_attribution_conflicts": (
                await self._count_referral_reward_attribution_conflicts(
                    source_user_id,
                    target_user_id,
                )
            ),
            "promocode_activations": await self._count_promocode_activations(source_user_id),
            "promocode_activation_duplicates": await self._count_promocode_duplicates(
                source_user_id, target_user_id
            ),
            "oauth_providers": await self._count(
                UserOAuthProvider, UserOAuthProvider.user_id == source_user_id
            ),
            "oauth_provider_duplicates": await self._count_oauth_duplicates(
                source_user_id, target_user_id
            ),
        }

    async def _count(self, model: type[Any], *where: ColumnElement[bool]) -> int:
        stmt = select(func.count()).select_from(model).where(*where)
        return int(await self.session.scalar(stmt) or 0)

    async def _count_promocode_activations(self, source_user_id: int) -> int:
        stmt = text("select count(*) from promocode_activations where user_id = :source_user_id")
        return int(await self.session.scalar(stmt, {"source_user_id": source_user_id}) or 0)

    async def _count_promocode_duplicates(self, source_user_id: int, target_user_id: int) -> int:
        stmt = text(
            """
            select count(*)
            from promocode_activations source
            join promocode_activations target
              on target.promocode_id = source.promocode_id
             and target.user_id = :target_user_id
            where source.user_id = :source_user_id
            """
        )
        params = {"source_user_id": source_user_id, "target_user_id": target_user_id}
        return int(await self.session.scalar(stmt, params) or 0)

    async def _count_oauth_duplicates(self, source_user_id: int, target_user_id: int) -> int:
        stmt = text(
            """
            select count(*)
            from user_oauth_providers source
            join user_oauth_providers target
              on target.provider = source.provider
             and target.user_id = :target_user_id
            where source.user_id = :source_user_id
            """
        )
        params = {"source_user_id": source_user_id, "target_user_id": target_user_id}
        return int(await self.session.scalar(stmt, params) or 0)

    async def _count_payment_operation_duplicates(
        self,
        source_user_id: int,
        target_user_id: int,
    ) -> int:
        stmt = text(
            """
            select count(*)
            from payment_operations source
            join payment_operations target
              on target.operation = source.operation
             and target.idempotency_key = source.idempotency_key
             and target.user_id = :target_user_id
            where source.user_id = :source_user_id
            """
        )
        params = {"source_user_id": source_user_id, "target_user_id": target_user_id}
        return int(await self.session.scalar(stmt, params) or 0)

    async def _count_referral_reward_attribution_conflicts(
        self,
        source_user_id: int,
        target_user_id: int,
    ) -> int:
        source_referrer_id = await self.session.scalar(
            select(Referral.referrer_id).where(Referral.referred_id == source_user_id).limit(1)
        )
        target_referrer_id = await self.session.scalar(
            select(Referral.referrer_id).where(Referral.referred_id == target_user_id).limit(1)
        )
        conflicts = int(
            source_referrer_id is not None
            and target_referrer_id is not None
            and source_referrer_id != target_referrer_id
        )
        if await self._referral_accounts_connected(source_user_id, target_user_id):
            conflicts += 1
        return conflicts

    @staticmethod
    def _referral_path_statement(
        ancestor_user_id: int,
        descendant_user_id: int,
    ) -> Select[Any]:
        return referral_path_statement(ancestor_user_id, descendant_user_id)

    async def _referral_path_exists(
        self,
        ancestor_user_id: int,
        descendant_user_id: int,
    ) -> bool:
        return bool(
            await self.session.scalar(
                self._referral_path_statement(ancestor_user_id, descendant_user_id)
            )
        )

    async def _referral_accounts_connected(
        self,
        source_user_id: int,
        target_user_id: int,
    ) -> bool:
        return await self._referral_path_exists(
            source_user_id,
            target_user_id,
        ) or await self._referral_path_exists(
            target_user_id,
            source_user_id,
        )

    async def _lock_nonterminal_referral_rewards(
        self,
        source_user_id: int,
        target_user_id: int,
    ) -> None:
        await self.session.execute(
            select(ReferralReward.id)
            .where(
                self._nonterminal_referral_reward_predicate(
                    source_user_id,
                    target_user_id,
                )
            )
            .order_by(ReferralReward.id)
            .with_for_update()
        )

    @staticmethod
    def _nonterminal_referral_reward_predicate(
        source_user_id: int,
        target_user_id: int,
    ) -> ColumnElement[bool]:
        user_ids = (source_user_id, target_user_id)
        related_referrals = select(Referral.id).where(
            or_(
                Referral.referrer_id.in_(user_ids),
                Referral.referred_id.in_(user_ids),
            )
        )
        related_transactions = select(Transaction.id).where(Transaction.user_id.in_(user_ids))
        return and_(
            ReferralReward.state.notin_(
                (
                    ReferralRewardState.ISSUED,
                    ReferralRewardState.SUPERSEDED,
                )
            ),
            or_(
                ReferralReward.user_id.in_(user_ids),
                ReferralReward.referral_id.in_(related_referrals),
                ReferralReward.origin_referral_id.in_(related_referrals),
                ReferralReward.source_transaction_id.in_(related_transactions),
            ),
        )

    async def _assert_no_referral_reward_attribution_conflicts(
        self,
        source_user_id: int,
        target_user_id: int,
    ) -> None:
        conflicts = await self._count_referral_reward_attribution_conflicts(
            source_user_id,
            target_user_id,
        )
        if conflicts:
            raise UserMergeReferralAttributionConflictError(
                "Merge has incompatible referral attribution "
                f"({conflicts}); resolve it explicitly before retrying"
            )

    async def _assert_no_active_referral_reward_work(
        self,
        source_user_id: int,
        target_user_id: int,
    ) -> None:
        active = await self._count(
            ReferralReward,
            self._nonterminal_referral_reward_predicate(
                source_user_id,
                target_user_id,
            ),
        )
        if active:
            raise UserMergeReferralAttributionConflictError(
                f"Cannot merge with nonterminal referral rewards ({active})"
            )

    async def _assert_no_payment_operation_collisions(
        self,
        source_user_id: int,
        target_user_id: int,
    ) -> None:
        duplicates = await self._count_payment_operation_duplicates(
            source_user_id,
            target_user_id,
        )
        if duplicates:
            raise UserMergePaymentOperationConflictError(
                f"Payment idempotency key collision between source and target ({duplicates})"
            )

    async def _rekey_source_payment_operation_collisions(
        self,
        source_user_id: int,
        target_user_id: int,
    ) -> None:
        target_operation = PaymentOperation.__table__.alias("target_operation")
        stmt = (
            select(PaymentOperation)
            .join(
                target_operation,
                (target_operation.c.operation == PaymentOperation.operation)
                & (target_operation.c.idempotency_key == PaymentOperation.idempotency_key)
                & (target_operation.c.user_id == target_user_id),
            )
            .where(PaymentOperation.user_id == source_user_id)
            .order_by(PaymentOperation.id)
            .with_for_update()
        )
        collisions = list((await self.session.scalars(stmt)).all())
        occupied_keys = set(
            (
                await self.session.scalars(
                    select(PaymentOperation.idempotency_key).where(
                        PaymentOperation.user_id.in_((source_user_id, target_user_id))
                    )
                )
            ).all()
        )

        for operation in collisions:
            counter = 0
            while True:
                digest = sha256(
                    f"{source_user_id}:{operation.id}:{operation.idempotency_key}:{counter}".encode()
                ).hexdigest()
                replacement = f"merged-{source_user_id}-{operation.id}-{digest[:32]}"
                if replacement not in occupied_keys:
                    break
                counter += 1
            operation.idempotency_key = replacement
            occupied_keys.add(replacement)

        if collisions:
            await self.session.flush()

    async def _normalize_stale_payment_work(self, *user_ids: int) -> None:
        now = func.clock_timestamp()
        await self.session.execute(
            delete(PaymentOperation).where(
                PaymentOperation.user_id.in_(user_ids),
                PaymentOperation.status == PaymentOperationStatus.CLAIMED.value,
                PaymentOperation.lease_expires_at <= now,
            )
        )
        await self.session.execute(
            update(PaymentOperation)
            .where(
                PaymentOperation.user_id.in_(user_ids),
                PaymentOperation.status == PaymentOperationStatus.PROCESSING.value,
                PaymentOperation.lease_expires_at <= now,
            )
            .values(
                status=PaymentOperationStatus.UNKNOWN.value,
                lease_expires_at=None,
            )
        )
        await self.session.execute(
            update(PaymentOperation)
            .where(
                PaymentOperation.user_id.in_(user_ids),
                PaymentOperation.reconcile_token_hash.is_not(None),
                PaymentOperation.reconcile_lease_expires_at <= now,
            )
            .values(
                status=PaymentOperationStatus.MANUAL_REQUIRED.value,
                reconcile_next_attempt_at=None,
                reconcile_last_error="RECONCILIATION_LEASE_EXPIRED_DURING_MERGE",
            )
        )
        await self.session.execute(
            update(Transaction)
            .where(
                Transaction.user_id.in_(user_ids),
                Transaction.fulfillment_status == TransactionFulfillmentStatus.PROCESSING,
                Transaction.fulfillment_lease_expires_at <= now,
            )
            .values(
                fulfillment_status=TransactionFulfillmentStatus.MANUAL_REQUIRED,
                fulfillment_lease_expires_at=None,
                fulfillment_last_error="FULFILLMENT_LEASE_EXPIRED_DURING_MERGE",
            )
        )

    async def _assert_no_active_payment_work(self, *user_ids: int) -> None:
        active_operations = await self._count(
            PaymentOperation,
            PaymentOperation.user_id.in_(user_ids),
            or_(
                PaymentOperation.status.in_(
                    (
                        PaymentOperationStatus.CLAIMED.value,
                        PaymentOperationStatus.PROCESSING.value,
                    )
                ),
                PaymentOperation.reconcile_token_hash.is_not(None),
            ),
        )
        processing_fulfillments = await self._count(
            Transaction,
            Transaction.user_id.in_(user_ids),
            or_(
                Transaction.fulfillment_status == TransactionFulfillmentStatus.PROCESSING,
                Transaction.fulfillment_token_hash.is_not(None),
            ),
        )
        if active_operations or processing_fulfillments:
            raise UserMergePaymentOperationConflictError(
                "Source user has active payment work "
                f"(operations={active_operations}, fulfillments={processing_fulfillments})"
            )

    async def _merge_records(
        self,
        source: User,
        target: User,
        moved: dict[str, int],
        *,
        email_resolution: EmailConflictResolution = EmailConflictResolution.REJECT,
        telegram_resolution: TelegramConflictResolution = TelegramConflictResolution.REJECT,
    ) -> None:
        source_email = source.email
        source_email_verified = source.is_email_verified
        merged_email, merged_email_verified = self._resolve_merged_email_identity(
            source_email=source_email,
            source_verified=source_email_verified,
            target_email=target.email,
            target_verified=target.is_email_verified,
        )
        source_password_hash = source.password_hash
        source_telegram_id = source.telegram_id
        source_username = source.username
        source_name = source.name
        source_language = source.language
        source_is_bot_blocked = source.is_bot_blocked
        source_subscription_id = source.current_subscription_id
        target_subscription_id = target.current_subscription_id or source_subscription_id
        merged_points = target.points + source.points
        merged_personal_discount = max(target.personal_discount, source.personal_discount)
        merged_purchase_discount = max(target.purchase_discount, source.purchase_discount)
        merged_rules_accepted = target.is_rules_accepted or source.is_rules_accepted
        merged_trial_available = target.is_trial_available and source.is_trial_available
        merged_ad_link_id = target.ad_link_id or source.ad_link_id

        source.email = None
        source.pending_email = None
        source.email_verification_code_hash = None
        source.email_verification_expires_at = None
        source.password_reset_code_hash = None
        source.password_reset_expires_at = None
        source.password_hash = None
        source.is_email_verified = False
        # Notification consent never crosses an account merge. The canonical
        # target's existing choice wins, including its enabled timestamp.
        source.subscription_expiration_email_enabled = False
        source.subscription_expiration_email_enabled_at = None
        source.telegram_id = None
        source.personal_discount = 0
        source.purchase_discount = 0
        source.points = 0
        source.is_trial_available = False
        source.ad_link_id = None
        source.current_subscription_id = None
        source.token_version += 1
        source.is_blocked = True
        await self.session.flush()

        await self._move_simple_fk(Subscription, source.id, target.id)
        await self._move_simple_fk(Transaction, source.id, target.id)
        await self._move_payment_operations(source.id, target.id, moved)
        await self._move_referrals(source.id, target.id, moved)
        await self._move_promocode_activations(source.id, target.id)
        await self._move_oauth_providers(source.id, target.id)

        # The database rejects marking a source as merged while it still owns
        # payment operations. Keep this assignment after the atomic transfer so
        # both current and rolling-deploy application versions preserve them.
        source.merged_into_user_id = target.id
        source.merged_at = datetime_now().astimezone(timezone.utc)

        target.email = merged_email
        target.password_hash = target.password_hash or source_password_hash
        target.is_email_verified = merged_email_verified
        target.telegram_id = (
            source_telegram_id
            if telegram_resolution is TelegramConflictResolution.KEEP_SOURCE
            and source_telegram_id is not None
            else target.telegram_id or source_telegram_id
        )
        if (
            telegram_resolution is TelegramConflictResolution.KEEP_SOURCE
            and source_telegram_id is not None
        ):
            target.username = source_username
            target.name = source_name
            target.language = source_language
            target.is_bot_blocked = source_is_bot_blocked
        target.points = merged_points
        target.personal_discount = merged_personal_discount
        target.purchase_discount = merged_purchase_discount
        target.is_rules_accepted = merged_rules_accepted
        target.is_trial_available = merged_trial_available
        target.ad_link_id = merged_ad_link_id
        target.pending_email = None
        target.email_verification_code_hash = None
        target.email_verification_expires_at = None
        target.password_reset_code_hash = None
        target.password_reset_expires_at = None
        target.current_subscription_id = target_subscription_id
        target.token_version += 1
        await self.session.flush()

    async def _move_payment_operations(
        self,
        source_user_id: int,
        target_user_id: int,
        moved: dict[str, int],
    ) -> None:
        snapshot = PaymentOperation.resolved_payment_snapshot
        stmt = (
            update(PaymentOperation)
            .where(PaymentOperation.user_id == source_user_id)
            .values(
                user_id=target_user_id,
                resolved_payment_snapshot=case(
                    (
                        snapshot.is_not(None),
                        func.jsonb_set(
                            snapshot,
                            cast(array(["user_id"]), ARRAY(Text())),
                            func.to_jsonb(target_user_id),
                            True,
                        ),
                    ),
                    else_=snapshot,
                ),
            )
        )
        moved["payment_operations"] = int(
            getattr(await self.session.execute(stmt), "rowcount", 0) or 0
        )

    async def _move_simple_fk(
        self, model: type[object], source_user_id: int, target_user_id: int
    ) -> int:
        user_id = getattr(model, "user_id")
        stmt = update(model).where(user_id == source_user_id).values(user_id=target_user_id)
        return int(getattr(await self.session.execute(stmt), "rowcount", 0) or 0)

    async def _move_referrals(
        self, source_user_id: int, target_user_id: int, moved: dict[str, int]
    ) -> None:
        if await self._referral_accounts_connected(source_user_id, target_user_id):
            raise UserMergeReferralAttributionConflictError(
                "Source and target are connected in the referral graph; "
                "merge would create a referral cycle"
            )

        source_referrer_id = await self.session.scalar(
            select(Referral.referrer_id).where(Referral.referred_id == source_user_id).limit(1)
        )
        target_referrer_id = await self.session.scalar(
            select(Referral.referrer_id).where(Referral.referred_id == target_user_id).limit(1)
        )
        if (
            source_referrer_id is not None
            and target_referrer_id is not None
            and source_referrer_id != target_referrer_id
        ):
            raise UserMergeReferralAttributionConflictError(
                "Source and target have different referral attribution; "
                "resolve it explicitly before retrying"
            )

        if target_referrer_id is None:
            await self.session.execute(
                update(Referral)
                .where(Referral.referred_id == source_user_id)
                .values(referred_id=target_user_id)
            )

        await self.session.execute(
            update(Referral)
            .where(Referral.referrer_id == source_user_id)
            .values(referrer_id=target_user_id)
        )
        await self.session.execute(
            update(ReferralReward)
            .where(ReferralReward.user_id == source_user_id)
            .values(user_id=target_user_id)
        )

    async def _move_promocode_activations(self, source_user_id: int, target_user_id: int) -> None:
        await self.session.execute(
            text(
                """
                delete from promocode_activations source
                using promocode_activations target
                where source.user_id = :source_user_id
                  and target.user_id = :target_user_id
                  and source.promocode_id = target.promocode_id
                """
            ),
            {"source_user_id": source_user_id, "target_user_id": target_user_id},
        )
        await self.session.execute(
            text(
                """
                update promocode_activations
                   set user_id = :target_user_id
                 where user_id = :source_user_id
                """
            ),
            {"source_user_id": source_user_id, "target_user_id": target_user_id},
        )

    async def _move_oauth_providers(self, source_user_id: int, target_user_id: int) -> None:
        await self.session.execute(
            text(
                """
                delete from user_oauth_providers source
                using user_oauth_providers target
                where source.user_id = :source_user_id
                  and target.user_id = :target_user_id
                  and source.provider = target.provider
                """
            ),
            {"source_user_id": source_user_id, "target_user_id": target_user_id},
        )
        await self.session.execute(
            update(UserOAuthProvider)
            .where(UserOAuthProvider.user_id == source_user_id)
            .values(user_id=target_user_id)
        )

    def _target_snapshot(self, target: User) -> UserMergeTargetSnapshot:
        return UserMergeTargetSnapshot(
            id=target.id,
            email=target.email,
            telegram_id=target.telegram_id,
            is_email_verified=target.is_email_verified,
            current_subscription_id=target.current_subscription_id,
        )
