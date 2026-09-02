from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Optional, cast

from adaptix import Retort
from adaptix.conversion import ConversionRetort
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import Numeric, and_, case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload
from sqlalchemy.sql import Select

from src.application.common.dao import ReferralDao
from src.application.dto import (
    LegacyReferralRewardRecoveryDto,
    ReferralDto,
    ReferralRewardBackfillAuditDto,
    ReferralRewardDto,
    ReferralStatisticsDto,
    UserReferralStatsDto,
)
from src.core.enums import (
    LegacyReferralRewardRecoveryAction,
    LegacyReferralRewardSourceValidation,
    PaymentGatewayType,
    PurchaseType,
    ReferralAccrualStrategy,
    ReferralLevel,
    ReferralRewardState,
    ReferralRewardStrategy,
    ReferralRewardType,
    TransactionFulfillmentStatus,
    TransactionStatus,
)
from src.core.utils.time import datetime_now
from src.infrastructure.database.models import (
    Referral,
    ReferralReward,
    ReferralRewardBackfillAudit,
    ReferralRewardResolution,
    Transaction,
    UserMergeAudit,
)
from src.infrastructure.database.models.user import User
from src.infrastructure.database.referral_graph import (
    acquire_referral_graph_lock,
    referral_path_statement,
)
from src.infrastructure.database.referral_reward_source import (
    exact_legacy_referral_source_fulfillment,
    normalized_admin_compensated_source_evidence_at,
    normalized_admin_compensated_source_predicate,
    normalized_recovered_source_evidence_at,
    operator_directed_source_predicate,
    paid_nontrial_referral_source_predicate,
    referral_source_evidence_at,
)

# Creation accepts only business fields. DTO audit/identity fields are read-side
# metadata; passing their default None values to a Core INSERT would override the
# database-owned NOT NULL timestamp defaults.
_REFERRAL_REWARD_CREATE_FIELDS = frozenset(
    {
        "user_id",
        "type",
        "amount",
        "is_issued",
        "source_transaction_id",
        "origin_referral_id",
        "level",
        "accrual_strategy_snapshot",
        "accrual_strategy",
        "reward_strategy",
        "config_value",
        "state",
        "attempt_count",
        "next_attempt_at",
        "processing_token_hash",
        "processing_lease_expires_at",
        "last_error",
        "manual_alerted_at",
        "refund_detected_at",
        "manual_incident_version",
        "manual_cause",
        "issued_at",
        "target_subscription_id",
        "baseline_expire_at",
        "target_expire_at",
        "operator_recovery_manifest_sha256",
    }
)

# Before durable transaction provenance was introduced, a reward row was written
# immediately after its payment fulfillment started.  The frozen production audit
# found a maximum delay of 17 seconds across the complete legacy cohort.  Keep a
# deliberately narrow margin so an emitted legacy reward can fence later
# ON_FIRST_PAYMENT candidates without inventing a source for unrelated rows.
_LEGACY_REWARD_MATCH_WINDOW = timedelta(seconds=30)


class ReferralDaoImpl(ReferralDao):
    def __init__(
        self,
        session: AsyncSession,
        retort: Retort,
        conversion_retort: ConversionRetort,
        redis: Redis,
    ) -> None:
        self.session = session
        self.retort = retort
        self.conversion_retort = conversion_retort
        self.redis = redis

        self._convert_to_referral_dto = self.conversion_retort.get_converter(Referral, ReferralDto)
        self._convert_to_referral_list = self.conversion_retort.get_converter(
            list[Referral],
            list[ReferralDto],
        )
        self._convert_to_reward_dto = self.conversion_retort.get_converter(
            ReferralReward,
            ReferralRewardDto,
        )
        self._convert_to_reward_list = self.conversion_retort.get_converter(
            list[ReferralReward],
            list[ReferralRewardDto],
        )

    async def lock_referral_graph(self) -> None:
        await acquire_referral_graph_lock(self.session)

    async def has_referral_path(
        self,
        ancestor_user_id: int,
        descendant_user_id: int,
    ) -> bool:
        return bool(
            await self.session.scalar(
                referral_path_statement(ancestor_user_id, descendant_user_id)
            )
        )

    async def create_referral(self, referral: ReferralDto) -> ReferralDto:
        db_referral = Referral(
            referrer_id=referral.referrer.id,
            referred_id=referral.referred.id,
            level=referral.level,
        )

        self.session.add(db_referral)
        await self.session.flush()
        await self.session.refresh(db_referral, attribute_names=["referrer", "referred"])

        logger.debug(
            f"Created referral: referrer id='{referral.referrer.id}' "
            f"invited referred id='{referral.referred.id}'"
        )
        return self._convert_to_referral_dto(db_referral)

    @staticmethod
    def _backfill_audit_to_dto(
        audit: ReferralRewardBackfillAudit,
    ) -> ReferralRewardBackfillAuditDto:
        return ReferralRewardBackfillAuditDto(
            id=audit.id,
            request_hash=audit.request_hash,
            status=audit.status,
            operator_identity=audit.operator_identity,
            operator_reference=audit.operator_reference,
            reason=audit.reason,
            source_transaction_ids=list(audit.source_transaction_ids),
            config_snapshot=dict(audit.config_snapshot),
            preview_snapshot=dict(audit.preview_snapshot),
            applied_at=audit.applied_at,
            created_at=audit.created_at,
            updated_at=audit.updated_at,
        )

    async def get_rewards_by_source_transaction(
        self,
        source_transaction_id: int,
    ) -> list[ReferralRewardDto]:
        rewards = cast(
            list,
            (
                await self.session.scalars(
                    select(ReferralReward)
                    .where(
                        ReferralReward.source_transaction_id == source_transaction_id,
                    )
                    .order_by(ReferralReward.level, ReferralReward.id)
                )
            ).all(),
        )
        return self._convert_to_reward_list(rewards)

    async def has_legacy_ambiguous_reward(
        self,
        *,
        referral_ids: list[int],
        recipient_user_ids: list[int],
    ) -> bool:
        if not referral_ids and not recipient_user_ids:
            return False
        return bool(
            await self.session.scalar(
                select(ReferralReward.id)
                .where(
                    ReferralReward.source_transaction_id.is_(None),
                    or_(
                        ReferralReward.referral_id.in_(referral_ids),
                        ReferralReward.user_id.in_(recipient_user_ids),
                    ),
                )
                .limit(1)
            )
        )

    async def acquire_historical_backfill_lock(self) -> None:
        # Serialize operator backfills across distinct previews. These are rare,
        # high-impact operations and deterministic global ordering is preferable
        # to deadlocks across overlapping referral chains.
        await self.session.scalar(select(func.pg_advisory_xact_lock(738_341_552)))

    async def create_or_get_backfill_preview(
        self,
        *,
        request_hash: str,
        operator_identity: str,
        operator_reference: str,
        reason: str,
        source_transaction_ids: list[int],
        config_snapshot: dict[str, Any],
        preview_snapshot: dict[str, Any],
    ) -> ReferralRewardBackfillAuditDto:
        preview_id = await self.session.scalar(
            insert(ReferralRewardBackfillAudit)
            .values(
                request_hash=request_hash,
                status="PREVIEWED",
                operator_identity=operator_identity,
                operator_reference=operator_reference,
                reason=reason,
                source_transaction_ids=source_transaction_ids,
                config_snapshot=config_snapshot,
                preview_snapshot=preview_snapshot,
            )
            .on_conflict_do_nothing(index_elements=["request_hash"])
            .returning(ReferralRewardBackfillAudit.id)
        )
        audit = (
            await self.session.get(ReferralRewardBackfillAudit, preview_id)
            if preview_id is not None
            else await self.session.scalar(
                select(ReferralRewardBackfillAudit).where(
                    ReferralRewardBackfillAudit.request_hash == request_hash
                )
            )
        )
        if audit is None:
            raise RuntimeError("Historical referral backfill preview disappeared")
        return self._backfill_audit_to_dto(audit)

    async def get_backfill_preview_for_update(
        self,
        preview_id: int,
    ) -> Optional[ReferralRewardBackfillAuditDto]:
        audit = await self.session.scalar(
            select(ReferralRewardBackfillAudit)
            .where(ReferralRewardBackfillAudit.id == preview_id)
            .with_for_update()
        )
        return self._backfill_audit_to_dto(audit) if audit is not None else None

    async def mark_backfill_preview_applied(self, preview_id: int) -> bool:
        result = await self.session.execute(
            update(ReferralRewardBackfillAudit)
            .where(
                ReferralRewardBackfillAudit.id == preview_id,
                ReferralRewardBackfillAudit.status == "PREVIEWED",
            )
            .values(status="APPLIED", applied_at=datetime_now())
        )
        return bool(getattr(result, "rowcount", 0))

    async def get_by_referred_id(self, referred_id: int) -> Optional[ReferralDto]:
        stmt = (
            select(Referral)
            .where(Referral.referred_id == referred_id)
            .options(selectinload(Referral.referrer), selectinload(Referral.referred))
        )
        db_referral = await self.session.scalar(stmt)

        if db_referral:
            logger.debug(f"Referrer for user_id '{referred_id}' found")
            return self._convert_to_referral_dto(db_referral)

        logger.debug(f"Referrer for user_id '{referred_id}' not found")
        return None

    async def get_referrals_count(self, referrer_id: int) -> int:
        referrer_user = aliased(User, name="referral_count_referrer")
        referred_user = aliased(User, name="referral_count_referred")
        stmt = (
            select(func.count())
            .select_from(Referral)
            .join(referrer_user, referrer_user.id == Referral.referrer_id)
            .join(referred_user, referred_user.id == Referral.referred_id)
            .where(
                Referral.referrer_id == referrer_id,
                referrer_user.merged_into_user_id.is_(None),
                referred_user.merged_into_user_id.is_(None),
            )
        )
        count = await self.session.scalar(stmt) or 0

        logger.debug(f"User_id '{referrer_id}' has '{count}' referrals")
        return count

    async def get_referrals_list(
        self,
        referrer_id: int,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ReferralDto]:
        referrer_user = aliased(User, name="referral_list_referrer")
        referred_user = aliased(User, name="referral_list_referred")
        stmt = (
            select(Referral)
            .join(referrer_user, referrer_user.id == Referral.referrer_id)
            .join(referred_user, referred_user.id == Referral.referred_id)
            .where(
                Referral.referrer_id == referrer_id,
                referrer_user.merged_into_user_id.is_(None),
                referred_user.merged_into_user_id.is_(None),
            )
            .options(selectinload(Referral.referred))
            .limit(limit)
            .offset(offset)
            .order_by(Referral.created_at.desc())
        )
        result = await self.session.scalars(stmt)
        db_referrals = cast(list, result.all())

        logger.debug(
            f"Retrieved '{len(db_referrals)}' referrals for user_id '{referrer_id}' "
            f"with limit '{limit}' and offset '{offset}'"
        )
        return self._convert_to_referral_list(db_referrals)

    async def create_reward(
        self,
        reward: ReferralRewardDto,
        referral_id: int,
    ) -> Optional[ReferralRewardDto]:
        if reward.source_transaction_id is not None:
            recovered_owner = await self.session.scalar(
                select(ReferralRewardResolution.reward_id)
                .where(
                    ReferralRewardResolution.selected_source_transaction_id
                    == reward.source_transaction_id,
                    ReferralRewardResolution.decision.in_(
                        (
                            LegacyReferralRewardRecoveryAction.RETRY_PROVEN_MISSING.value,
                            LegacyReferralRewardRecoveryAction.CONFIRM_ADMIN_COMPENSATED.value,
                            LegacyReferralRewardRecoveryAction.RETRY_OPERATOR_DIRECTED.value,
                        )
                    ),
                )
                .limit(1)
            )
            if recovered_owner is not None:
                # Recovery and the two normal writers hold the same attribution-user
                # fence. A recovery manifest is the complete historical level set,
                # so any resolution consuming this source freezes all later normal
                # levels. Returning None also makes backfill APPLY fail closed.
                logger.warning(
                    f"Reward source '{reward.source_transaction_id}' is frozen by "
                    f"recovered reward '{recovered_owner}'; normal level "
                    f"'{reward.level.name if reward.level is not None else 'UNKNOWN'}' skipped"
                )
                return None

        reward_data = {
            field: value
            for field, value in self.retort.dump(reward).items()
            if field in _REFERRAL_REWARD_CREATE_FIELDS
        }
        # referral_id is accepted on read DTOs so operators can inspect legacy
        # attribution. Creation still takes the authoritative relationship as an
        # explicit argument. Database-owned identity/audit fields are deliberately
        # outside the allowlist so their defaults cannot be overridden by DTO None.
        stmt = (
            insert(ReferralReward)
            .values(**reward_data, referral_id=referral_id)
            .on_conflict_do_nothing()
            .returning(ReferralReward.id)
        )
        reward_id = await self.session.scalar(stmt)

        if reward_id is None:
            db_reward = await self.session.scalar(
                select(ReferralReward).where(
                    ReferralReward.source_transaction_id == reward.source_transaction_id,
                    ReferralReward.origin_referral_id == reward.origin_referral_id,
                    ReferralReward.level == reward.level,
                )
            )
            if db_reward is None:
                # Never return an unrelated historical reward. A conflict with the
                # ON_FIRST claim marker means another successful source won. The
                # marker intentionally survives retry/manual/terminal transitions.
                if reward.accrual_strategy_snapshot == ReferralAccrualStrategy.ON_FIRST_PAYMENT:
                    winner = await self.session.scalar(
                        select(ReferralReward.id).where(
                            ReferralReward.origin_referral_id == reward.origin_referral_id,
                            ReferralReward.level == reward.level,
                            ReferralReward.accrual_strategy
                            == ReferralAccrualStrategy.ON_FIRST_PAYMENT,
                        )
                    )
                    if winner is not None:
                        return None
                raise RuntimeError("Referral reward conflict could not be resolved exactly")
            return self._convert_to_reward_dto(db_reward)

        db_reward = await self.session.get(ReferralReward, reward_id)
        if db_reward is None:
            raise RuntimeError("Created referral reward disappeared")

        logger.debug(f"Created reward amount '{reward.amount}' for referral ID '{referral_id}'")
        return self._convert_to_reward_dto(db_reward)

    async def get_reward_by_id(
        self,
        reward_id: int,
        *,
        for_update: bool = False,
    ) -> Optional[ReferralRewardDto]:
        if for_update:
            reward = await self.session.scalar(
                select(ReferralReward)
                .where(ReferralReward.id == reward_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        else:
            reward = await self.session.get(ReferralReward, reward_id)
        return self._convert_to_reward_dto(reward) if reward is not None else None

    async def lock_manual_reward_source_status(
        self,
        reward_id: int,
    ) -> Optional[TransactionStatus]:
        # The reward row is the first durable fence for every grant/resolution
        # path. Refresh it while locking so a long-lived request session cannot use
        # an identity-map snapshot captured before the operator transaction.
        reward = await self.session.scalar(
            select(ReferralReward)
            .where(ReferralReward.id == reward_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if reward is None:
            return None

        if reward.source_transaction_id is not None:
            return cast(
                Optional[TransactionStatus],
                await self.session.scalar(
                    select(Transaction.status)
                    .where(Transaction.id == reward.source_transaction_id)
                    .with_for_update()
                ),
            )

        resolution_sources = [
            ReferralRewardResolution.decision == "CONFIRM_ADMIN_COMPENSATED"
        ]
        if reward.operator_recovery_manifest_sha256 is not None:
            resolution_sources.append(
                and_(
                    ReferralRewardResolution.decision
                    == LegacyReferralRewardRecoveryAction.RETRY_OPERATOR_DIRECTED.value,
                    ReferralRewardResolution.authorization_manifest_sha256
                    == reward.operator_recovery_manifest_sha256,
                )
            )

        return cast(
            Optional[TransactionStatus],
            await self.session.scalar(
                select(Transaction.status)
                .join(
                    ReferralRewardResolution,
                    ReferralRewardResolution.selected_source_transaction_id == Transaction.id,
                )
                .where(
                    ReferralRewardResolution.reward_id == reward_id,
                    or_(*resolution_sources),
                )
                .with_for_update(of=Transaction)
            ),
        )

    async def claim_pending_rewards(
        self,
        *,
        token_hash: str,
        lease_for: timedelta,
        limit: int,
    ) -> list[ReferralRewardDto]:
        now = datetime_now()

        non_issuable_sources = select(Transaction.id).where(
            Transaction.fulfillment_status == TransactionFulfillmentStatus.MANUAL_REQUIRED,
        )
        await self.session.execute(
            update(ReferralReward)
            .where(
                ReferralReward.source_transaction_id.in_(non_issuable_sources),
                ReferralReward.state.in_(
                    (
                        ReferralRewardState.PENDING,
                        ReferralRewardState.RETRY_WAITING,
                    )
                ),
            )
            .values(
                state=ReferralRewardState.MANUAL_REQUIRED,
                manual_incident_version=ReferralReward.manual_incident_version + 1,
                manual_cause="SOURCE_FULFILLMENT_NOT_PROVEN",
                processing_token_hash=None,
                processing_lease_expires_at=None,
                next_attempt_at=None,
                last_error="SOURCE_FULFILLMENT_NOT_PROVEN",
                manual_alerted_at=None,
            )
        )

        # Once an absolute EXTRA_DAYS target was persisted, a dead worker may have
        # reached Remnawave. Replaying the additive operation is ambiguous, so fence it
        # for an operator instead of reclaiming it.
        await self.session.execute(
            update(ReferralReward)
            .where(
                ReferralReward.state == ReferralRewardState.PROCESSING,
                ReferralReward.type == ReferralRewardType.EXTRA_DAYS,
                ReferralReward.target_expire_at.is_not(None),
                ReferralReward.processing_lease_expires_at <= now,
            )
            .values(
                state=ReferralRewardState.MANUAL_REQUIRED,
                manual_incident_version=ReferralReward.manual_incident_version + 1,
                manual_cause="EXTRA_DAYS_AMBIGUOUS_LEASE_EXPIRED",
                processing_token_hash=None,
                processing_lease_expires_at=None,
                next_attempt_at=None,
                last_error="EXTRA_DAYS_AMBIGUOUS_LEASE_EXPIRED",
                manual_alerted_at=None,
            )
        )

        # A crashed POINTS grant, or EXTRA_DAYS grant that had not persisted an
        # external target yet, is safe to retry. Normalizing first also releases the
        # per-recipient PROCESSING fence.
        await self.session.execute(
            update(ReferralReward)
            .where(
                ReferralReward.state == ReferralRewardState.PROCESSING,
                ReferralReward.processing_lease_expires_at <= now,
            )
            .values(
                state=ReferralRewardState.RETRY_WAITING,
                processing_token_hash=None,
                processing_lease_expires_at=None,
                next_attempt_at=now,
                last_error="REWARD_PROCESSING_LEASE_EXPIRED",
            )
        )

        refunded_sources = select(Transaction.id).where(
            Transaction.status == TransactionStatus.REFUNDED
        )
        admin_compensated_source = aliased(
            Transaction,
            name="admin_compensated_reward_source",
        )
        admin_compensated_refunded_source = (
            select(ReferralRewardResolution.id)
            .join(
                admin_compensated_source,
                admin_compensated_source.id
                == ReferralRewardResolution.selected_source_transaction_id,
            )
            .where(
                ReferralRewardResolution.reward_id == ReferralReward.id,
                ReferralRewardResolution.decision == "CONFIRM_ADMIN_COMPENSATED",
                admin_compensated_source.status == TransactionStatus.REFUNDED,
            )
        )
        operator_recovery_source = aliased(
            Transaction,
            name="operator_recovery_reward_source",
        )
        operator_recovery_refunded_source = (
            select(ReferralRewardResolution.id)
            .join(
                operator_recovery_source,
                operator_recovery_source.id
                == ReferralRewardResolution.selected_source_transaction_id,
            )
            .where(
                ReferralRewardResolution.reward_id == ReferralReward.id,
                ReferralRewardResolution.decision
                == LegacyReferralRewardRecoveryAction.RETRY_OPERATOR_DIRECTED.value,
                ReferralRewardResolution.authorization_manifest_sha256
                == ReferralReward.operator_recovery_manifest_sha256,
                operator_recovery_source.status == TransactionStatus.REFUNDED,
            )
        )
        resolved_current_refund_incident = select(ReferralRewardResolution.id).where(
            ReferralRewardResolution.reward_id == ReferralReward.id,
            ReferralRewardResolution.incident_version == ReferralReward.manual_incident_version,
            ReferralRewardResolution.source_status == TransactionStatus.REFUNDED.value,
        )
        # A reward that never left the durable pending states has no side effect
        # to claw back. Refund terminalizes it without reopening ON_FIRST.
        await self.session.execute(
            update(ReferralReward)
            .where(
                or_(
                    ReferralReward.source_transaction_id.in_(refunded_sources),
                    operator_recovery_refunded_source.exists(),
                ),
                ReferralReward.state.in_(
                    (
                        ReferralRewardState.PENDING,
                        ReferralRewardState.RETRY_WAITING,
                    )
                ),
            )
            .values(
                state=ReferralRewardState.SUPERSEDED,
                next_attempt_at=None,
                last_error="SOURCE_REFUNDED_BEFORE_REWARD_ISSUANCE",
            )
        )
        operator_valid_source = aliased(
            Transaction,
            name="operator_recovery_valid_source",
        )
        operator_valid_resolution = aliased(
            ReferralRewardResolution,
            name="operator_recovery_valid_resolution",
        )
        valid_operator_source = (
            select(operator_valid_source.id)
            .join(
                operator_valid_resolution,
                operator_valid_resolution.selected_source_transaction_id
                == operator_valid_source.id,
            )
            .where(
                operator_valid_resolution.reward_id == ReferralReward.id,
                operator_valid_resolution.incident_version
                == ReferralReward.manual_incident_version,
                operator_valid_resolution.authorization_manifest_sha256
                == ReferralReward.operator_recovery_manifest_sha256,
                *operator_directed_source_predicate(
                    operator_valid_resolution,
                    operator_valid_source,
                ),
            )
        )
        # A non-refund eligibility drift must not strand an authorized row outside
        # both the worker and the manual queue. Refunds were terminalized above;
        # every other invalid/missing source is an alerted manual incident.
        await self.session.execute(
            update(ReferralReward)
            .where(
                ReferralReward.operator_recovery_manifest_sha256.is_not(None),
                ReferralReward.source_transaction_id.is_(None),
                ReferralReward.state.in_(
                    (
                        ReferralRewardState.PENDING,
                        ReferralRewardState.RETRY_WAITING,
                    )
                ),
                ~valid_operator_source.exists(),
            )
            .values(
                state=ReferralRewardState.MANUAL_REQUIRED,
                manual_incident_version=ReferralReward.manual_incident_version + 1,
                manual_cause="OPERATOR_RECOVERY_SOURCE_NOT_ELIGIBLE",
                processing_token_hash=None,
                processing_lease_expires_at=None,
                next_attempt_at=None,
                last_error="OPERATOR_RECOVERY_SOURCE_NOT_ELIGIBLE",
                manual_alerted_at=None,
            )
        )
        # PROCESSING is ambiguous and ISSUED needs an explicit operator clawback
        # decision. Preserve is_issued/issued_at on issued history while surfacing it.
        await self.session.execute(
            update(ReferralReward)
            .where(
                or_(
                    ReferralReward.source_transaction_id.in_(refunded_sources),
                    operator_recovery_refunded_source.exists(),
                ),
                ReferralReward.state == ReferralRewardState.PROCESSING,
            )
            .values(
                state=ReferralRewardState.MANUAL_REQUIRED,
                manual_incident_version=ReferralReward.manual_incident_version + 1,
                manual_cause="SOURCE_REFUNDED_DURING_REWARD_ISSUANCE",
                processing_token_hash=None,
                processing_lease_expires_at=None,
                next_attempt_at=None,
                last_error="SOURCE_REFUNDED_DURING_REWARD_ISSUANCE",
                manual_alerted_at=None,
                refund_detected_at=now,
            )
        )
        await self.session.execute(
            update(ReferralReward)
            .where(
                or_(
                    ReferralReward.source_transaction_id.in_(refunded_sources),
                    admin_compensated_refunded_source.exists(),
                    operator_recovery_refunded_source.exists(),
                ),
                ReferralReward.state == ReferralRewardState.ISSUED,
                ~resolved_current_refund_incident.exists(),
            )
            .values(
                state=ReferralRewardState.MANUAL_REQUIRED,
                manual_incident_version=ReferralReward.manual_incident_version + 1,
                manual_cause="SOURCE_REFUNDED_AFTER_REWARD_ISSUANCE",
                next_attempt_at=None,
                manual_alerted_at=None,
                refund_detected_at=now,
            )
        )
        # A reward may already be MANUAL_REQUIRED for another ambiguous cause.
        # Surface the later refund without destroying that original diagnosis.
        await self.session.execute(
            update(ReferralReward)
            .where(
                or_(
                    ReferralReward.source_transaction_id.in_(refunded_sources),
                    operator_recovery_refunded_source.exists(),
                ),
                ReferralReward.state == ReferralRewardState.MANUAL_REQUIRED,
                or_(
                    ReferralReward.manual_cause.is_(None),
                    ReferralReward.manual_cause.notin_(
                        (
                            "SOURCE_REFUNDED_DURING_REWARD_ISSUANCE",
                            "SOURCE_REFUNDED_AFTER_REWARD_ISSUANCE",
                        )
                    ),
                ),
            )
            .values(
                manual_incident_version=ReferralReward.manual_incident_version + 1,
                manual_cause="SOURCE_REFUNDED_DURING_REWARD_ISSUANCE",
                refund_detected_at=now,
                manual_alerted_at=None,
            )
        )

        source_transaction = aliased(Transaction, name="reward_source_transaction")
        earlier_transaction = aliased(Transaction, name="earlier_successful_transaction")
        supersede_source = aliased(Transaction, name="superseded_reward_source")
        supersede_earlier = aliased(Transaction, name="superseding_earlier_transaction")
        admin_earlier = aliased(Transaction, name="admin_compensated_earlier_transaction")
        supersede_admin_earlier = aliased(
            Transaction,
            name="superseding_admin_compensated_transaction",
        )
        supersede_operator_earlier = aliased(
            Transaction,
            name="superseding_operator_directed_transaction",
        )
        supersede_operator_resolution = aliased(
            ReferralRewardResolution,
            name="superseding_operator_directed_resolution",
        )
        emitted_legacy_source = aliased(
            Transaction,
            name="emitted_legacy_reward_source",
        )
        emitted_legacy_reward = aliased(
            ReferralReward,
            name="emitted_legacy_reward",
        )
        active_winner = aliased(ReferralReward, name="active_first_payment_winner")

        earlier_evidence_at = referral_source_evidence_at(
            earlier_transaction,
            include_legacy=True,
        )
        earlier_success_exists = select(earlier_transaction.id).where(
            earlier_transaction.user_id == source_transaction.user_id,
            *paid_nontrial_referral_source_predicate(
                earlier_transaction,
                include_refunded=True,
                include_legacy=True,
            ),
            or_(
                earlier_evidence_at < source_transaction.fulfillment_completed_at,
                and_(
                    earlier_evidence_at == source_transaction.fulfillment_completed_at,
                    earlier_transaction.id < source_transaction.id,
                ),
            ),
        )
        active_winner_exists = select(active_winner.id).where(
            active_winner.origin_referral_id == ReferralReward.origin_referral_id,
            active_winner.level == ReferralReward.level,
            active_winner.accrual_strategy == ReferralAccrualStrategy.ON_FIRST_PAYMENT,
            active_winner.id != ReferralReward.id,
        )
        admin_compensated_earlier_exists = (
            select(ReferralRewardResolution.id)
            .join(
                admin_earlier,
                admin_earlier.id == ReferralRewardResolution.selected_source_transaction_id,
            )
            .where(
                ReferralRewardResolution.selected_origin_referral_id
                == ReferralReward.origin_referral_id,
                ReferralRewardResolution.selected_level == ReferralReward.level,
                admin_earlier.user_id == source_transaction.user_id,
                *normalized_admin_compensated_source_predicate(
                    ReferralRewardResolution,
                    admin_earlier,
                ),
                or_(
                    normalized_admin_compensated_source_evidence_at(
                        ReferralRewardResolution,
                        admin_earlier,
                    )
                    < source_transaction.fulfillment_completed_at,
                    and_(
                        normalized_admin_compensated_source_evidence_at(
                            ReferralRewardResolution,
                            admin_earlier,
                        )
                        == source_transaction.fulfillment_completed_at,
                        admin_earlier.id < source_transaction.id,
                    ),
                ),
            )
        )

        earlier_success_for_reward = (
            select(supersede_earlier.id)
            .select_from(supersede_source)
            .join(
                supersede_earlier,
                supersede_earlier.user_id == supersede_source.user_id,
            )
            .where(
                supersede_source.id == ReferralReward.source_transaction_id,
                *paid_nontrial_referral_source_predicate(
                    supersede_earlier,
                    include_refunded=True,
                    include_legacy=False,
                ),
                or_(
                    referral_source_evidence_at(supersede_earlier, include_legacy=False)
                    < supersede_source.fulfillment_completed_at,
                    and_(
                        referral_source_evidence_at(
                            supersede_earlier,
                            include_legacy=False,
                        )
                        == supersede_source.fulfillment_completed_at,
                        supersede_earlier.id < supersede_source.id,
                    ),
                ),
            )
        )
        legacy_earlier_for_reward = (
            select(supersede_earlier.id)
            .select_from(supersede_source)
            .join(
                supersede_earlier,
                supersede_earlier.user_id == supersede_source.user_id,
            )
            .where(
                supersede_source.id == ReferralReward.source_transaction_id,
                supersede_earlier.status.in_(
                    (TransactionStatus.COMPLETED, TransactionStatus.REFUNDED)
                ),
                exact_legacy_referral_source_fulfillment(supersede_earlier),
                supersede_earlier.is_test.is_(False),
                supersede_earlier.pricing["final_amount"].astext.cast(Numeric) > 0,
                supersede_earlier.plan_snapshot["is_trial"].astext == "false",
                or_(
                    supersede_earlier.fulfillment_started_at
                    < supersede_source.fulfillment_completed_at,
                    and_(
                        supersede_earlier.fulfillment_started_at
                        == supersede_source.fulfillment_completed_at,
                        supersede_earlier.id < supersede_source.id,
                    ),
                ),
            )
        )
        admin_compensated_earlier_for_reward = (
            select(ReferralRewardResolution.id)
            .select_from(supersede_source)
            .join(
                supersede_admin_earlier,
                supersede_admin_earlier.user_id == supersede_source.user_id,
            )
            .join(
                ReferralRewardResolution,
                ReferralRewardResolution.selected_source_transaction_id
                == supersede_admin_earlier.id,
            )
            .where(
                supersede_source.id == ReferralReward.source_transaction_id,
                ReferralRewardResolution.selected_origin_referral_id
                == ReferralReward.origin_referral_id,
                ReferralRewardResolution.selected_level == ReferralReward.level,
                *normalized_admin_compensated_source_predicate(
                    ReferralRewardResolution,
                    supersede_admin_earlier,
                ),
                or_(
                    normalized_admin_compensated_source_evidence_at(
                        ReferralRewardResolution,
                        supersede_admin_earlier,
                    )
                    < supersede_source.fulfillment_completed_at,
                    and_(
                        normalized_admin_compensated_source_evidence_at(
                            ReferralRewardResolution,
                            supersede_admin_earlier,
                        )
                        == supersede_source.fulfillment_completed_at,
                        supersede_admin_earlier.id < supersede_source.id,
                    ),
                ),
            )
        )

        operator_directed_earlier_for_reward = (
            select(supersede_operator_resolution.id)
            .select_from(supersede_source)
            .join(
                supersede_operator_earlier,
                supersede_operator_earlier.user_id == supersede_source.user_id,
            )
            .join(
                supersede_operator_resolution,
                supersede_operator_resolution.selected_source_transaction_id
                == supersede_operator_earlier.id,
            )
            .where(
                supersede_source.id == ReferralReward.source_transaction_id,
                supersede_operator_resolution.selected_origin_referral_id
                == ReferralReward.origin_referral_id,
                supersede_operator_resolution.selected_level == ReferralReward.level,
                *operator_directed_source_predicate(
                    supersede_operator_resolution,
                    supersede_operator_earlier,
                ),
                or_(
                    normalized_recovered_source_evidence_at(
                        supersede_operator_resolution,
                        supersede_operator_earlier,
                    )
                    < supersede_source.fulfillment_completed_at,
                    and_(
                        normalized_recovered_source_evidence_at(
                            supersede_operator_resolution,
                            supersede_operator_earlier,
                        )
                        == supersede_source.fulfillment_completed_at,
                        supersede_operator_earlier.id < supersede_source.id,
                    ),
                ),
            )
        )

        emitted_legacy_reward_for_reward = (
            select(emitted_legacy_reward.id)
            .select_from(supersede_source)
            .join(
                emitted_legacy_source,
                emitted_legacy_source.user_id == supersede_source.user_id,
            )
            .join(
                emitted_legacy_reward,
                and_(
                    emitted_legacy_reward.user_id == ReferralReward.user_id,
                    emitted_legacy_reward.referral_id == ReferralReward.referral_id,
                    emitted_legacy_reward.type == ReferralReward.type,
                    emitted_legacy_reward.amount == ReferralReward.amount,
                    emitted_legacy_reward.source_transaction_id.is_(None),
                    emitted_legacy_reward.state == ReferralRewardState.ISSUED,
                    emitted_legacy_reward.is_issued.is_(True),
                    emitted_legacy_reward.issued_at.is_not(None),
                    emitted_legacy_reward.created_at
                    >= emitted_legacy_source.fulfillment_started_at,
                    emitted_legacy_reward.created_at
                    <= emitted_legacy_source.fulfillment_started_at + _LEGACY_REWARD_MATCH_WINDOW,
                    emitted_legacy_reward.created_at < supersede_source.fulfillment_completed_at,
                ),
            )
            .where(
                supersede_source.id == ReferralReward.source_transaction_id,
                emitted_legacy_source.status.in_(
                    (TransactionStatus.COMPLETED, TransactionStatus.REFUNDED)
                ),
                exact_legacy_referral_source_fulfillment(emitted_legacy_source),
                emitted_legacy_source.is_test.is_(False),
                emitted_legacy_source.pricing["final_amount"].astext.cast(Numeric) > 0,
                emitted_legacy_source.plan_snapshot["is_trial"].astext == "false",
                or_(
                    emitted_legacy_source.fulfillment_started_at
                    < supersede_source.fulfillment_completed_at,
                    and_(
                        emitted_legacy_source.fulfillment_started_at
                        == supersede_source.fulfillment_completed_at,
                        emitted_legacy_source.id < supersede_source.id,
                    ),
                ),
            )
        )

        # The owner-defined recovery rule treats administrator-added days as an
        # already delivered reward.  That immutable resolution is therefore a
        # conclusive earlier winner for a later ON_FIRST_PAYMENT candidate.
        await self.session.execute(
            update(ReferralReward)
            .where(
                ReferralReward.accrual_strategy_snapshot
                == ReferralAccrualStrategy.ON_FIRST_PAYMENT,
                ReferralReward.accrual_strategy.is_(None),
                or_(
                    ReferralReward.state.in_(
                        (
                            ReferralRewardState.PENDING,
                            ReferralRewardState.RETRY_WAITING,
                        )
                    ),
                    and_(
                        ReferralReward.state == ReferralRewardState.MANUAL_REQUIRED,
                        ReferralReward.manual_cause.in_(
                            (
                                "ADMIN_COMPENSATED_EARLIER_PAYMENT",
                                "LEGACY_EARLIER_PAYMENT_REQUIRES_REVIEW",
                            )
                        ),
                    ),
                ),
                admin_compensated_earlier_for_reward.exists(),
            )
            .values(
                state=ReferralRewardState.SUPERSEDED,
                next_attempt_at=None,
                processing_token_hash=None,
                processing_lease_expires_at=None,
                last_error="FIRST_PAYMENT_ADMIN_COMPENSATED",
            )
        )

        # A trusted operator recovery resolution, or an exact issued legacy
        # reward emitted alongside the earlier fulfillment, proves that the earlier
        # payment already owns the reward intent. Terminalize the later candidate;
        # the earlier reward remains independently retryable until its recipient
        # has an eligible subscription.
        await self.session.execute(
            update(ReferralReward)
            .where(
                ReferralReward.accrual_strategy_snapshot
                == ReferralAccrualStrategy.ON_FIRST_PAYMENT,
                ReferralReward.accrual_strategy.is_(None),
                or_(
                    ReferralReward.state.in_(
                        (
                            ReferralRewardState.PENDING,
                            ReferralRewardState.RETRY_WAITING,
                        )
                    ),
                    and_(
                        ReferralReward.state == ReferralRewardState.MANUAL_REQUIRED,
                        ReferralReward.manual_cause == "LEGACY_EARLIER_PAYMENT_REQUIRES_REVIEW",
                    ),
                ),
                or_(
                    operator_directed_earlier_for_reward.exists(),
                    emitted_legacy_reward_for_reward.exists(),
                ),
            )
            .values(
                state=ReferralRewardState.SUPERSEDED,
                next_attempt_at=None,
                processing_token_hash=None,
                processing_lease_expires_at=None,
                last_error="FIRST_PAYMENT_EARLIER_REWARD_EXISTS",
            )
        )

        # A pre-0049 completed source has no durable fulfillment timestamp, so
        # it cannot safely prove or disprove historical ON_FIRST eligibility.
        # Keep a later candidate fenced for explicit review instead of issuing
        # a potential duplicate or silently terminalizing it.
        await self.session.execute(
            update(ReferralReward)
            .where(
                ReferralReward.accrual_strategy_snapshot
                == ReferralAccrualStrategy.ON_FIRST_PAYMENT,
                ReferralReward.accrual_strategy.is_(None),
                ReferralReward.state.in_(
                    (
                        ReferralRewardState.PENDING,
                        ReferralRewardState.RETRY_WAITING,
                    )
                ),
                legacy_earlier_for_reward.exists(),
            )
            .values(
                state=ReferralRewardState.MANUAL_REQUIRED,
                manual_incident_version=ReferralReward.manual_incident_version + 1,
                manual_cause="LEGACY_EARLIER_PAYMENT_REQUIRES_REVIEW",
                next_attempt_at=None,
                last_error="LEGACY_EARLIER_PAYMENT_REQUIRES_REVIEW",
                manual_alerted_at=None,
            )
        )

        # A source cannot remain pending forever merely because its first eligible
        # paid transaction predates referral attribution or enabled settings.
        await self.session.execute(
            update(ReferralReward)
            .where(
                ReferralReward.accrual_strategy_snapshot
                == ReferralAccrualStrategy.ON_FIRST_PAYMENT,
                ReferralReward.accrual_strategy.is_(None),
                ReferralReward.state.in_(
                    (
                        ReferralRewardState.PENDING,
                        ReferralRewardState.RETRY_WAITING,
                    )
                ),
                earlier_success_for_reward.exists(),
            )
            .values(
                state=ReferralRewardState.SUPERSEDED,
                next_attempt_at=None,
                last_error="FIRST_PAYMENT_EARLIER_SUCCESS",
            )
        )

        # Once a winner has claimed the ON_FIRST marker, every other durable
        # candidate for the same direct referral and level is terminal history.
        await self.session.execute(
            update(ReferralReward)
            .where(
                ReferralReward.accrual_strategy_snapshot
                == ReferralAccrualStrategy.ON_FIRST_PAYMENT,
                ReferralReward.accrual_strategy.is_(None),
                ReferralReward.state.in_(
                    (
                        ReferralRewardState.PENDING,
                        ReferralRewardState.RETRY_WAITING,
                    )
                ),
                active_winner_exists.exists(),
            )
            .values(
                state=ReferralRewardState.SUPERSEDED,
                next_attempt_at=None,
                last_error="FIRST_PAYMENT_SUPERSEDED",
            )
        )
        due_condition = or_(
            ReferralReward.state == ReferralRewardState.PENDING,
            and_(
                ReferralReward.state == ReferralRewardState.RETRY_WAITING,
                or_(
                    ReferralReward.next_attempt_at.is_(None),
                    ReferralReward.next_attempt_at <= now,
                ),
            ),
        )
        source_condition = and_(
            source_transaction.status == TransactionStatus.COMPLETED,
            source_transaction.fulfillment_status == TransactionFulfillmentStatus.SUCCEEDED,
            source_transaction.is_test.is_(False),
            source_transaction.pricing["final_amount"].astext.cast(Numeric) > 0,
            source_transaction.plan_snapshot["is_trial"].astext == "false",
        )
        strategy_condition = or_(
            ReferralReward.accrual_strategy_snapshot != ReferralAccrualStrategy.ON_FIRST_PAYMENT,
            and_(
                ReferralReward.accrual_strategy_snapshot
                == ReferralAccrualStrategy.ON_FIRST_PAYMENT,
                ~earlier_success_exists.exists(),
                ~active_winner_exists.exists(),
                ~admin_compensated_earlier_exists.exists(),
            ),
        )
        normal_eligible_source = select(source_transaction.id).where(
            source_transaction.id == ReferralReward.source_transaction_id,
            source_condition,
            strategy_condition,
        )
        operator_claim_source = aliased(Transaction, name="operator_claim_source")
        operator_claim_resolution = aliased(
            ReferralRewardResolution,
            name="operator_claim_resolution",
        )
        operator_eligible_source = (
            select(operator_claim_source.id)
            .join(
                operator_claim_resolution,
                operator_claim_resolution.selected_source_transaction_id
                == operator_claim_source.id,
            )
            .where(
                operator_claim_resolution.reward_id == ReferralReward.id,
                operator_claim_resolution.incident_version
                == ReferralReward.manual_incident_version,
                operator_claim_resolution.decision
                == LegacyReferralRewardRecoveryAction.RETRY_OPERATOR_DIRECTED.value,
                operator_claim_resolution.authorization_manifest_sha256
                == ReferralReward.operator_recovery_manifest_sha256,
                *operator_directed_source_predicate(
                    operator_claim_resolution,
                    operator_claim_source,
                ),
            )
        )
        eligible_source_condition = or_(
            normal_eligible_source.exists(),
            operator_eligible_source.exists(),
        )

        due_for_user = (
            select(ReferralReward.id)
            .where(
                ReferralReward.user_id == User.id,
                due_condition,
                eligible_source_condition,
            )
        )
        active_for_user = select(ReferralReward.id).where(
            ReferralReward.user_id == User.id,
            ReferralReward.state == ReferralRewardState.PROCESSING,
        )
        # User rows are the common lock shared by all rewards for a recipient. After
        # commit, the durable PROCESSING row (plus the partial unique index) keeps the
        # recipient serialized across the external EXTRA_DAYS call.
        candidate_user_ids = (
            select(User.id)
            .where(due_for_user.exists(), ~active_for_user.exists())
            .order_by(User.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        user_ids = list((await self.session.scalars(candidate_user_ids)).all())
        ids: list[int] = []
        for user_id in user_ids:
            # READ COMMITTED takes a new snapshot for this statement. The user-lock
            # query above can acquire a row immediately after another claimant
            # commits its PROCESSING row while still evaluating an older snapshot.
            # Rechecking under the acquired user lock closes that narrow race and
            # keeps the partial unique index as a last-resort invariant instead of
            # turning normal concurrent claims into task failures.
            processing_for_user = aliased(
                ReferralReward,
                name="processing_reward_for_locked_user",
            )
            active_after_lock = select(processing_for_user.id).where(
                processing_for_user.user_id == user_id,
                processing_for_user.state == ReferralRewardState.PROCESSING,
            )
            reward_id = await self.session.scalar(
                select(ReferralReward.id)
                .where(
                    ReferralReward.user_id == user_id,
                    due_condition,
                    eligible_source_condition,
                    ~active_after_lock.exists(),
                )
                .order_by(
                    ReferralReward.next_attempt_at.asc().nullsfirst(),
                    ReferralReward.id,
                )
                .limit(1)
            )
            if reward_id is not None:
                ids.append(reward_id)

        if not ids:
            return []

        # The recipient lock serializes workers, but administrative recovery and
        # source reconciliation intentionally use different entry points. Reapply
        # every mutable eligibility predicate in the state transition itself so a
        # row changed while this claimant was waiting can never be overwritten by
        # a stale candidate id.
        processing_during_claim = aliased(
            ReferralReward,
            name="processing_reward_during_claim_update",
        )
        other_processing_for_recipient = select(processing_during_claim.id).where(
            processing_during_claim.user_id == ReferralReward.user_id,
            processing_during_claim.id != ReferralReward.id,
            processing_during_claim.state == ReferralRewardState.PROCESSING,
        )
        stmt = (
            update(ReferralReward)
            .where(
                ReferralReward.id.in_(ids),
                due_condition,
                eligible_source_condition,
                ~other_processing_for_recipient.exists(),
            )
            .values(
                state=ReferralRewardState.PROCESSING,
                accrual_strategy=case(
                    (
                        ReferralReward.accrual_strategy_snapshot
                        == ReferralAccrualStrategy.ON_FIRST_PAYMENT,
                        ReferralAccrualStrategy.ON_FIRST_PAYMENT,
                    ),
                    else_=ReferralReward.accrual_strategy_snapshot,
                ),
                processing_token_hash=token_hash,
                processing_lease_expires_at=now + lease_for,
                attempt_count=ReferralReward.attempt_count + 1,
                next_attempt_at=None,
                last_error=None,
            )
            .returning(ReferralReward)
        )
        rewards = cast(list, (await self.session.scalars(stmt)).all())
        for reward in rewards:
            if reward.accrual_strategy_snapshot == ReferralAccrualStrategy.ON_FIRST_PAYMENT:
                await self.session.execute(
                    update(ReferralReward)
                    .where(
                        ReferralReward.id != reward.id,
                        ReferralReward.origin_referral_id == reward.origin_referral_id,
                        ReferralReward.level == reward.level,
                        ReferralReward.accrual_strategy_snapshot
                        == ReferralAccrualStrategy.ON_FIRST_PAYMENT,
                        ReferralReward.accrual_strategy.is_(None),
                        ReferralReward.state.in_(
                            (
                                ReferralRewardState.PENDING,
                                ReferralRewardState.RETRY_WAITING,
                            )
                        ),
                    )
                    .values(
                        state=ReferralRewardState.SUPERSEDED,
                        next_attempt_at=None,
                        last_error="FIRST_PAYMENT_SUPERSEDED",
                    )
                )
        return self._convert_to_reward_list(rewards)

    async def defer_reward(
        self,
        reward_id: int,
        *,
        token_hash: str,
        retry_after: timedelta,
        error_code: str,
    ) -> bool:
        result = await self.session.execute(
            update(ReferralReward)
            .where(
                ReferralReward.id == reward_id,
                ReferralReward.state == ReferralRewardState.PROCESSING,
                ReferralReward.processing_token_hash == token_hash,
                ReferralReward.target_expire_at.is_(None),
            )
            .values(
                state=ReferralRewardState.RETRY_WAITING,
                processing_token_hash=None,
                processing_lease_expires_at=None,
                next_attempt_at=datetime_now() + retry_after,
                last_error=error_code[:64],
            )
        )
        return bool(getattr(result, "rowcount", 0))

    async def mark_reward_manual_required(
        self,
        reward_id: int,
        *,
        token_hash: str,
        error_code: str,
    ) -> bool:
        result = await self.session.execute(
            update(ReferralReward)
            .where(
                ReferralReward.id == reward_id,
                ReferralReward.state == ReferralRewardState.PROCESSING,
                ReferralReward.processing_token_hash == token_hash,
            )
            .values(
                state=ReferralRewardState.MANUAL_REQUIRED,
                manual_incident_version=ReferralReward.manual_incident_version + 1,
                manual_cause=error_code[:64],
                processing_token_hash=None,
                processing_lease_expires_at=None,
                next_attempt_at=None,
                last_error=error_code[:64],
                manual_alerted_at=None,
            )
        )
        return bool(getattr(result, "rowcount", 0))

    async def lock_reward_source_if_eligible(
        self,
        reward_id: int,
        *,
        token_hash: str,
    ) -> bool:
        # All reward mutation paths use Reward -> source Transaction ordering.
        # Holding the reward row across the external side effect prevents the lease
        # sweeper or an operator from changing its state mid-grant, while the source
        # lock keeps a concurrent refund behind the completed grant.
        reward = await self.session.scalar(
            select(ReferralReward)
            .where(
                ReferralReward.id == reward_id,
                ReferralReward.state == ReferralRewardState.PROCESSING,
                ReferralReward.processing_token_hash == token_hash,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if reward is None:
            return False

        if reward.source_transaction_id is not None:
            source_id = await self.session.scalar(
                select(Transaction.id)
                .where(
                    Transaction.id == reward.source_transaction_id,
                    *paid_nontrial_referral_source_predicate(
                        Transaction,
                        include_refunded=False,
                        include_legacy=False,
                    ),
                )
                .with_for_update()
            )
            return source_id is not None

        if reward.operator_recovery_manifest_sha256 is None:
            return False

        operator_source = await self.session.scalar(
            select(Transaction.id)
            .join(
                ReferralRewardResolution,
                ReferralRewardResolution.selected_source_transaction_id == Transaction.id,
            )
            .where(
                ReferralRewardResolution.reward_id == reward_id,
                ReferralRewardResolution.incident_version
                == reward.manual_incident_version,
                ReferralRewardResolution.decision
                == LegacyReferralRewardRecoveryAction.RETRY_OPERATOR_DIRECTED.value,
                ReferralRewardResolution.authorization_manifest_sha256
                == reward.operator_recovery_manifest_sha256,
                *operator_directed_source_predicate(
                    ReferralRewardResolution,
                    Transaction,
                ),
            )
            .with_for_update(of=Transaction)
        )
        return operator_source is not None

    async def cancel_claimed_reward(
        self,
        reward_id: int,
        *,
        token_hash: str,
        error_code: str,
    ) -> bool:
        result = await self.session.execute(
            update(ReferralReward)
            .where(
                ReferralReward.id == reward_id,
                ReferralReward.state == ReferralRewardState.PROCESSING,
                ReferralReward.processing_token_hash == token_hash,
            )
            .values(
                state=ReferralRewardState.SUPERSEDED,
                processing_token_hash=None,
                processing_lease_expires_at=None,
                next_attempt_at=None,
                last_error=error_code[:64],
            )
        )
        return bool(getattr(result, "rowcount", 0))

    async def set_extra_days_target(
        self,
        reward_id: int,
        *,
        token_hash: str,
        subscription_id: int,
        baseline_expire_at: datetime,
        target_expire_at: datetime,
    ) -> bool:
        result = await self.session.execute(
            update(ReferralReward)
            .where(
                ReferralReward.id == reward_id,
                ReferralReward.state == ReferralRewardState.PROCESSING,
                ReferralReward.processing_token_hash == token_hash,
                ReferralReward.target_expire_at.is_(None),
            )
            .values(
                target_subscription_id=subscription_id,
                baseline_expire_at=baseline_expire_at,
                target_expire_at=target_expire_at,
            )
        )
        return bool(getattr(result, "rowcount", 0))

    async def issue_points_reward(
        self,
        reward_id: int,
        *,
        user_id: int,
        amount: int,
        token_hash: str,
    ) -> bool:
        now = datetime_now()
        reward_id_result = await self.session.scalar(
            update(ReferralReward)
            .where(
                ReferralReward.id == reward_id,
                ReferralReward.user_id == user_id,
                ReferralReward.state == ReferralRewardState.PROCESSING,
                ReferralReward.processing_token_hash == token_hash,
            )
            .values(
                is_issued=True,
                state=ReferralRewardState.ISSUED,
                issued_at=now,
                processing_token_hash=None,
                processing_lease_expires_at=None,
                next_attempt_at=None,
                last_error=None,
            )
            .returning(ReferralReward.id)
        )
        if reward_id_result is None:
            return False
        user_result = await self.session.execute(
            update(User).where(User.id == user_id).values(points=User.points + amount)
        )
        if not getattr(user_result, "rowcount", 0):
            raise RuntimeError(f"Referral reward recipient '{user_id}' disappeared")
        return True

    async def finish_extra_days_reward(
        self,
        reward_id: int,
        *,
        token_hash: str,
    ) -> bool:
        result = await self.session.execute(
            update(ReferralReward)
            .where(
                ReferralReward.id == reward_id,
                ReferralReward.state == ReferralRewardState.PROCESSING,
                ReferralReward.processing_token_hash == token_hash,
                ReferralReward.target_expire_at.is_not(None),
            )
            .values(
                is_issued=True,
                state=ReferralRewardState.ISSUED,
                issued_at=datetime_now(),
                processing_token_hash=None,
                processing_lease_expires_at=None,
                next_attempt_at=None,
                last_error=None,
            )
        )
        return bool(getattr(result, "rowcount", 0))

    async def get_reward_referred_name(self, reward_id: int) -> str:
        stmt = (
            select(User.name)
            .join(Transaction, Transaction.user_id == User.id)
            .join(
                ReferralReward,
                ReferralReward.source_transaction_id == Transaction.id,
            )
            .where(ReferralReward.id == reward_id)
        )
        return await self.session.scalar(stmt) or "Referral"

    async def get_manual_required_rewards(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ReferralRewardDto]:
        rows = cast(
            list,
            (
                await self.session.scalars(
                    select(ReferralReward)
                    .where(ReferralReward.state == ReferralRewardState.MANUAL_REQUIRED)
                    .order_by(ReferralReward.updated_at.asc(), ReferralReward.id)
                    .limit(limit)
                    .offset(offset)
                )
            ).all(),
        )
        return self._convert_to_reward_list(rows)

    async def claim_manual_required_rewards_for_alert(
        self,
        *,
        limit: int = 100,
    ) -> list[ReferralRewardDto]:
        candidate_ids = (
            select(ReferralReward.id)
            .where(
                ReferralReward.state == ReferralRewardState.MANUAL_REQUIRED,
                ReferralReward.manual_alerted_at.is_(None),
            )
            .order_by(ReferralReward.updated_at, ReferralReward.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        ids = list((await self.session.scalars(candidate_ids)).all())
        if not ids:
            return []
        rows = cast(
            list,
            (
                await self.session.scalars(
                    select(ReferralReward)
                    .where(ReferralReward.id.in_(ids))
                    .order_by(ReferralReward.updated_at, ReferralReward.id)
                )
            ).all(),
        )
        return self._convert_to_reward_list(rows)

    async def mark_manual_rewards_alerted(self, reward_ids: list[int]) -> None:
        if not reward_ids:
            return
        await self.session.execute(
            update(ReferralReward)
            .where(
                ReferralReward.id.in_(reward_ids),
                ReferralReward.state == ReferralRewardState.MANUAL_REQUIRED,
                ReferralReward.manual_alerted_at.is_(None),
            )
            .values(manual_alerted_at=datetime_now())
        )

    async def resolve_manual_reward(  # noqa: C901
        self,
        reward_id: int,
        *,
        expected_version: int,
        confirm_issued: bool,
        operator_reference: str,
        resolved_by: str,
        reason: str,
        allow_drift: bool = False,
        observed_subscription_id: Optional[int] = None,
        observed_remote_uuid: Optional[str] = None,
        observed_expire_at: Optional[datetime] = None,
        source_status: Optional[TransactionStatus] = None,
        ack_admin_compensated_refund: bool = False,
    ) -> bool:
        reward = await self.session.scalar(
            select(ReferralReward).where(ReferralReward.id == reward_id).with_for_update()
        )
        if reward is None:
            return False

        decision = (
            "ACK_ADMIN_COMPENSATED_REFUND"
            if ack_admin_compensated_refund
            else ("CONFIRM_ISSUED" if confirm_issued else "CANCEL")
        )
        existing = await self.session.scalar(
            select(ReferralRewardResolution).where(
                ReferralRewardResolution.reward_id == reward_id,
                ReferralRewardResolution.incident_version == expected_version,
            )
        )
        if existing is not None:
            return bool(
                existing.decision == decision
                and existing.operator_reference == operator_reference
                and existing.resolved_by == resolved_by
                and existing.reason == reason
                and existing.allow_drift == allow_drift
            )
        if reward.state != ReferralRewardState.MANUAL_REQUIRED:
            return False
        if reward.manual_incident_version != expected_version:
            return False
        if ack_admin_compensated_refund and (
            confirm_issued
            or allow_drift
            or reward.type != ReferralRewardType.EXTRA_DAYS
            or not reward.is_issued
            or reward.source_transaction_id is not None
            or reward.origin_referral_id is not None
            or reward.level is not None
            or reward.target_subscription_id is not None
            or reward.baseline_expire_at is not None
            or reward.target_expire_at is not None
            or reward.manual_cause != "SOURCE_REFUNDED_AFTER_REWARD_ISSUANCE"
            or reward.refund_detected_at is None
        ):
            return False
        if (
            confirm_issued
            and reward.accrual_strategy_snapshot == ReferralAccrualStrategy.ON_FIRST_PAYMENT
            and reward.accrual_strategy != ReferralAccrualStrategy.ON_FIRST_PAYMENT
        ):
            return False

        admin_evidence: ReferralRewardResolution | None = None
        if ack_admin_compensated_refund:
            admin_evidence = await self.session.scalar(
                select(ReferralRewardResolution).where(
                    ReferralRewardResolution.reward_id == reward_id,
                    ReferralRewardResolution.decision == "CONFIRM_ADMIN_COMPENSATED",
                )
            )
            if (
                admin_evidence is None
                or admin_evidence.selected_source_transaction_id is None
                or admin_evidence.selected_origin_referral_id is None
                or admin_evidence.selected_level is None
                or admin_evidence.authorization_manifest_sha256 is None
            ):
                return False
            locked_source_status = cast(
                Optional[TransactionStatus],
                await self.session.scalar(
                    select(Transaction.status)
                    .where(Transaction.id == admin_evidence.selected_source_transaction_id)
                    .with_for_update()
                ),
            )
            if locked_source_status != TransactionStatus.REFUNDED:
                return False
            source_status = locked_source_status

        self.session.add(
            ReferralRewardResolution(
                reward_id=reward_id,
                incident_version=expected_version,
                decision=decision,
                operator_reference=operator_reference,
                resolved_by=resolved_by,
                reason=reason,
                allow_drift=allow_drift,
                observed_subscription_id=observed_subscription_id,
                observed_remote_uuid=observed_remote_uuid,
                observed_expire_at=observed_expire_at,
                source_status=(source_status.value if source_status is not None else None),
                selected_source_transaction_id=(
                    admin_evidence.selected_source_transaction_id
                    if admin_evidence is not None
                    else None
                ),
                selected_origin_referral_id=(
                    admin_evidence.selected_origin_referral_id
                    if admin_evidence is not None
                    else None
                ),
                selected_level=(
                    admin_evidence.selected_level if admin_evidence is not None else None
                ),
                authorization_manifest_sha256=(
                    admin_evidence.authorization_manifest_sha256
                    if admin_evidence is not None
                    else None
                ),
            )
        )

        values: dict[str, object]
        if confirm_issued or ack_admin_compensated_refund:
            values = {
                "state": ReferralRewardState.ISSUED,
                "is_issued": True,
                "issued_at": func.coalesce(
                    ReferralReward.issued_at,
                    datetime_now(),
                ),
            }
        else:
            values = {
                "state": ReferralRewardState.SUPERSEDED,
                "is_issued": False,
            }
        result = await self.session.execute(
            update(ReferralReward)
            .where(
                ReferralReward.id == reward_id,
                ReferralReward.state == ReferralRewardState.MANUAL_REQUIRED,
                ReferralReward.manual_incident_version == expected_version,
            )
            .values(
                **values,
                processing_token_hash=None,
                processing_lease_expires_at=None,
                next_attempt_at=None,
            )
        )
        return bool(getattr(result, "rowcount", 0))

    async def manual_resolution_match(
        self,
        reward_id: int,
        *,
        expected_version: int,
        confirm_issued: bool,
        operator_reference: str,
        resolved_by: str,
        reason: str,
        allow_drift: bool = False,
        ack_admin_compensated_refund: bool = False,
    ) -> Optional[bool]:
        existing = await self.session.scalar(
            select(ReferralRewardResolution).where(
                ReferralRewardResolution.reward_id == reward_id,
                ReferralRewardResolution.incident_version == expected_version,
            )
        )
        if existing is None:
            return None
        decision = (
            "ACK_ADMIN_COMPENSATED_REFUND"
            if ack_admin_compensated_refund
            else ("CONFIRM_ISSUED" if confirm_issued else "CANCEL")
        )
        return bool(
            existing.decision == decision
            and existing.operator_reference == operator_reference
            and existing.resolved_by == resolved_by
            and existing.reason == reason
            and existing.allow_drift == allow_drift
        )

    async def recover_legacy_extra_days_reward(  # noqa: C901, PLR0912
        self,
        recovery: LegacyReferralRewardRecoveryDto,
    ) -> bool:
        """Atomically attach proven provenance to one legacy EXTRA_DAYS row.

        True means the row was transitioned in this transaction. False is an
        exact replay of the immutable decision. Every mismatch fails closed.
        """

        if (
            recovery.authorization_manifest_sha256 is None
            or len(recovery.authorization_manifest_sha256) != 64
            or recovery.authorization_manifest_sha256
            != recovery.authorization_manifest_sha256.lower()
            or any(
                character not in "0123456789abcdef"
                for character in recovery.authorization_manifest_sha256
            )
        ):
            raise ValueError("Trusted recovery manifest authorization is missing")
        if (
            recovery.source_transaction_id is None
            or recovery.origin_referral_id is None
            or recovery.level is None
        ):
            raise ValueError("Legacy recovery requires exact source and referral evidence")
        if recovery.action == LegacyReferralRewardRecoveryAction.RETRY_OPERATOR_DIRECTED:
            if recovery.source_validation not in (
                LegacyReferralRewardSourceValidation.LOCAL_COMPLETED,
                LegacyReferralRewardSourceValidation.PROVIDER_SUCCEEDED,
            ):
                raise ValueError("Operator-directed source validation class is missing")
        elif recovery.source_validation is not None:
            raise ValueError("Source validation class is reserved for operator-directed recovery")
        await self.acquire_historical_backfill_lock()
        requested_provenance = self._legacy_recovery_request_provenance(recovery)
        existing = await self.session.scalar(
            select(ReferralRewardResolution).where(
                ReferralRewardResolution.reward_id == recovery.reward_id,
                ReferralRewardResolution.incident_version == recovery.expected_version,
            )
        )
        if existing is not None:
            selected = existing.selected_provenance or {}
            if not (
                existing.decision == recovery.action.value
                and selected.get("request") == requested_provenance
                and existing.operator_reference == recovery.operator_reference
                and existing.resolved_by == recovery.resolved_by
                and existing.reason == recovery.reason
                and existing.evidence_sha256 == recovery.evidence_sha256
                and existing.allow_drift is False
                and existing.selected_source_transaction_id == recovery.source_transaction_id
                and existing.selected_origin_referral_id == recovery.origin_referral_id
                and existing.selected_level == recovery.level
                and existing.authorization_manifest_sha256 == recovery.authorization_manifest_sha256
            ):
                raise ValueError(
                    f"Referral reward '{recovery.reward_id}' was recovered with "
                    "different provenance or evidence"
                )
            return False
        other_resolution = await self.session.scalar(
            select(ReferralRewardResolution.id)
            .where(ReferralRewardResolution.reward_id == recovery.reward_id)
            .limit(1)
        )
        if other_resolution is not None:
            raise ValueError(
                f"Referral reward '{recovery.reward_id}' already has another resolution incident"
            )

        # Hints are deliberately unlocked. They only identify the complete user lock
        # set. After those users are locked in the same order as user-merge and the
        # live reward writer, every mutable row is re-read under FOR UPDATE.
        reward_hint = await self.session.get(ReferralReward, recovery.reward_id)
        source_hint = await self.session.get(Transaction, recovery.source_transaction_id)
        origin_hint = await self.session.get(Referral, recovery.origin_referral_id)
        if reward_hint is None:
            raise ValueError(f"Referral reward '{recovery.reward_id}' was not found")
        if source_hint is None:
            raise ValueError(f"Source transaction '{recovery.source_transaction_id}' was not found")
        if origin_hint is None:
            raise ValueError(f"Origin referral '{recovery.origin_referral_id}' was not found")
        parent_hint = await self.session.scalar(
            select(Referral).where(Referral.referred_id == origin_hint.referrer_id).limit(1)
        )
        participant_ids = {
            reward_hint.user_id,
            source_hint.user_id,
            origin_hint.referrer_id,
            origin_hint.referred_id,
        }
        if parent_hint is not None:
            participant_ids.update((parent_hint.referrer_id, parent_hint.referred_id))
        locked_user_ids = set(
            (
                await self.session.scalars(
                    select(User.id)
                    .where(User.id.in_(sorted(participant_ids)))
                    .order_by(User.id)
                    .with_for_update()
                )
            ).all()
        )
        if locked_user_ids != participant_ids:
            raise ValueError("Legacy reward participants changed or no longer exist")
        participant_merge_audit_ids: tuple[int, ...] = ()
        if recovery.action == LegacyReferralRewardRecoveryAction.RETRY_OPERATOR_DIRECTED:
            participant_merge_audit_ids = tuple(
                (
                    await self.session.scalars(
                        self._operator_recovery_participant_merge_audit_ids_query(
                            participant_ids
                        )
                    )
                ).all()
            )
            if (
                participant_merge_audit_ids
                != recovery.expected_participant_merge_audit_ids
            ):
                raise ValueError(
                    "Legacy reward participant merge history drifted from the frozen manifest"
                )
            merge_conflict = await self.session.scalar(
                self._operator_recovery_merge_conflict_query(participant_ids)
            )
            if merge_conflict is not None:
                raise ValueError(
                    "Legacy reward participants have non-canonical user-merge history"
                )
        else:
            real_merge = await self.session.scalar(
                select(UserMergeAudit.id)
                .where(
                    UserMergeAudit.dry_run.is_(False),
                    or_(
                        UserMergeAudit.source_user_id.in_(participant_ids),
                        UserMergeAudit.target_user_id.in_(participant_ids),
                    ),
                )
                .limit(1)
            )
            if real_merge is not None:
                raise ValueError("Legacy reward participants have real user-merge history")

        reward = await self.session.scalar(
            select(ReferralReward)
            .where(ReferralReward.id == recovery.reward_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if reward is None:
            raise ValueError(f"Referral reward '{recovery.reward_id}' was not found")
        self._validate_0052_legacy_reward_shape(reward, recovery)
        if recovery.action == LegacyReferralRewardRecoveryAction.RETRY_OPERATOR_DIRECTED:
            if (
                recovery.expected_user_id is None
                or recovery.expected_referral_id is None
                or recovery.expected_created_at is None
                or reward.user_id != recovery.expected_user_id
                or reward.referral_id != recovery.expected_referral_id
                or reward.created_at != recovery.expected_created_at
            ):
                raise ValueError(
                    "Operator-directed recovery row no longer matches the frozen manifest"
                )

        source = await self.session.scalar(
            select(Transaction)
            .where(Transaction.id == recovery.source_transaction_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if source is None:
            raise ValueError(f"Source transaction '{recovery.source_transaction_id}' was not found")
        self._validate_legacy_recovery_source(
            source,
            recovery.action,
            recovery.source_validation,
        )
        source_timestamp_kind, source_evidence_at = self._legacy_recovery_source_evidence_timestamp(
            source
        )

        origin = await self.session.scalar(
            select(Referral)
            .where(Referral.id == recovery.origin_referral_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if origin is None or origin.referred_id != source.user_id:
            raise ValueError("Origin referral does not exactly attribute the source payer")
        direct = await self.session.scalar(
            select(Referral)
            .where(Referral.referred_id == source.user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if direct is None or direct.id != origin.id:
            raise ValueError("Direct referral attribution changed")

        selected_referral = direct
        if recovery.level == ReferralLevel.SECOND:
            parent = await self.session.scalar(
                select(Referral)
                .where(Referral.referred_id == direct.referrer_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if parent is None:
                raise ValueError("Exact second-level referral attribution was not found")
            selected_referral = parent

        # L2 exists in two exact historical shapes. Before cf35a93 it retained
        # the direct/origin referral while selecting the parent's referrer as
        # recipient; newer legacy rows (including rr1486) stored the parent
        # referral. Preserve and audit whichever exact shape is present.
        if reward.referral_id == direct.id:
            stored_referral_shape = "DIRECT_ORIGIN"
        elif recovery.level == ReferralLevel.SECOND and reward.referral_id == selected_referral.id:
            stored_referral_shape = "PARENT_RECIPIENT"
        else:
            stored_referral_shape = None
        if stored_referral_shape is None or reward.user_id != selected_referral.referrer_id:
            raise ValueError("Legacy reward recipient does not match the exact referral chain")
        self._validate_legacy_reward_source_window(reward, source_evidence_at)
        if origin.created_at is None or origin.created_at > source_evidence_at:
            raise ValueError("Origin referral does not predate the source fulfillment")
        if recovery.level == ReferralLevel.SECOND and (
            selected_referral.created_at is None
            or selected_referral.created_at > source_evidence_at
        ):
            raise ValueError("Second-level referral does not predate the source fulfillment")

        collision = await self.session.scalar(
            select(ReferralReward.id)
            .where(
                ReferralReward.id != reward.id,
                ReferralReward.source_transaction_id == source.id,
                ReferralReward.level == recovery.level,
            )
            .with_for_update()
        )
        if collision is not None:
            raise ValueError("A durable reward already owns the selected provenance")
        recovery_collision = await self.session.scalar(
            select(ReferralRewardResolution.id)
            .where(
                ReferralRewardResolution.selected_source_transaction_id == source.id,
                ReferralRewardResolution.selected_level == recovery.level,
            )
            .limit(1)
        )
        if recovery_collision is not None:
            raise ValueError("A recovered reward already owns the selected source and level")

        if (
            recovery.action == LegacyReferralRewardRecoveryAction.RETRY_PROVEN_MISSING
            and recovery.accrual_strategy_snapshot == ReferralAccrualStrategy.ON_FIRST_PAYMENT
        ):
            fulfilled_at = source.fulfillment_completed_at
            if fulfilled_at is None:
                raise ValueError(
                    "ON_FIRST legacy recovery requires a durable fulfillment timestamp"
                )
            if source.purchase_type != PurchaseType.NEW:
                raise ValueError("ON_FIRST legacy recovery requires a NEW purchase source")
            earlier_source = aliased(Transaction, name="legacy_recovery_earlier_source")
            earlier_evidence_at = referral_source_evidence_at(
                earlier_source,
                include_legacy=True,
            )
            earlier = await self.session.scalar(
                select(earlier_source.id).where(
                    earlier_source.user_id == source.user_id,
                    earlier_source.id != source.id,
                    *paid_nontrial_referral_source_predicate(
                        earlier_source,
                        include_refunded=True,
                        include_legacy=True,
                    ),
                    or_(
                        earlier_evidence_at < fulfilled_at,
                        and_(
                            earlier_evidence_at == fulfilled_at,
                            earlier_source.id < source.id,
                        ),
                    ),
                )
            )
            if earlier is not None:
                raise ValueError("Source is not the first successful paid transaction")
            winner = await self.session.scalar(
                select(ReferralReward.id)
                .where(
                    ReferralReward.id != reward.id,
                    ReferralReward.origin_referral_id == origin.id,
                    ReferralReward.level == recovery.level,
                    ReferralReward.accrual_strategy == ReferralAccrualStrategy.ON_FIRST_PAYMENT,
                )
                .with_for_update()
            )
            if winner is not None:
                raise ValueError("Another durable reward already won ON_FIRST_PAYMENT")

        if recovery.action == LegacyReferralRewardRecoveryAction.RETRY_PROVEN_MISSING:
            if (
                recovery.accrual_strategy_snapshot is None
                or recovery.reward_strategy is None
                or recovery.config_value is None
            ):
                raise ValueError(
                    "RETRY_PROVEN_MISSING requires the exact historical policy snapshot"
                )
            expected_amount = self._legacy_recovery_extra_days_amount(
                source,
                recovery.reward_strategy,
                recovery.config_value,
            )
            if reward.amount != expected_amount:
                raise ValueError(
                    f"Legacy reward amount '{reward.amount}' does not match the historical "
                    f"snapshot amount '{expected_amount}'"
                )
        elif any(
            value is not None
            for value in (
                recovery.accrual_strategy_snapshot,
                recovery.reward_strategy,
                recovery.config_value,
            )
        ):
            raise ValueError(
                f"{recovery.action.value} must not invent a historical policy snapshot"
            )

        selected_provenance = {
            "request": requested_provenance,
            "selected": {
                "payer_user_id": source.user_id,
                "recipient_user_id": reward.user_id,
                "stored_reward_referral_id": reward.referral_id,
                "recipient_referral_id": selected_referral.id,
                "stored_reward_referral_shape": stored_referral_shape,
                "reward_type": reward.type.value,
                "reward_amount": reward.amount,
                "legacy_reward_created_at": (
                    reward.created_at.isoformat() if reward.created_at is not None else None
                ),
                "origin_referral_created_at": origin.created_at.isoformat(),
                "source_purchase_type": source.purchase_type.value,
                "source_fulfillment_status": source.fulfillment_status.value,
                "source_fulfillment_completed_at": (
                    source.fulfillment_completed_at.isoformat()
                    if source.fulfillment_completed_at is not None
                    else None
                ),
                "source_evidence_timestamp_kind": source_timestamp_kind,
                "source_evidence_timestamp": source_evidence_at.isoformat(),
            },
        }
        if recovery.action == LegacyReferralRewardRecoveryAction.RETRY_OPERATOR_DIRECTED:
            selected_provenance["selected"]["source_validation"] = (
                recovery.source_validation.value
                if recovery.source_validation is not None
                else None
            )
            selected_provenance["selected"]["participant_merge_audit_ids"] = list(
                participant_merge_audit_ids
            )
        self.session.add(
            ReferralRewardResolution(
                reward_id=reward.id,
                incident_version=recovery.expected_version,
                decision=recovery.action.value,
                operator_reference=recovery.operator_reference,
                resolved_by=recovery.resolved_by,
                reason=recovery.reason,
                allow_drift=False,
                source_status=source.status.value,
                selected_provenance=selected_provenance,
                evidence_sha256=recovery.evidence_sha256,
                selected_source_transaction_id=source.id,
                selected_origin_referral_id=origin.id,
                selected_level=recovery.level,
                authorization_manifest_sha256=recovery.authorization_manifest_sha256,
            )
        )

        confirm_compensated = (
            recovery.action == LegacyReferralRewardRecoveryAction.CONFIRM_ADMIN_COMPENSATED
        )
        values = self._legacy_recovery_transition_values(
            recovery,
            source_transaction_id=source.id,
            origin_referral_id=origin.id,
            issued_at=datetime_now() if confirm_compensated else None,
        )
        result = await self.session.execute(
            update(ReferralReward)
            .where(
                ReferralReward.id == reward.id,
                ReferralReward.state == ReferralRewardState.MANUAL_REQUIRED,
                ReferralReward.manual_incident_version == recovery.expected_version,
                ReferralReward.source_transaction_id.is_(None),
            )
            .values(**values)
        )
        if not getattr(result, "rowcount", 0):
            raise ValueError("Legacy reward recovery fence changed before transition")
        return True

    @staticmethod
    def _operator_recovery_participant_merge_audit_ids_query(
        participant_ids: set[int],
    ) -> Any:
        """Return the exact ordered real-merge lineage touching participants."""

        return (
            select(UserMergeAudit.id)
            .where(
                UserMergeAudit.dry_run.is_(False),
                or_(
                    UserMergeAudit.source_user_id.in_(sorted(participant_ids)),
                    UserMergeAudit.target_user_id.in_(sorted(participant_ids)),
                ),
            )
            .order_by(UserMergeAudit.id)
        )

    @staticmethod
    def _operator_recovery_merge_conflict_query(participant_ids: set[int]) -> Any:
        """Find a merge participant that is not a canonical current target.

        A successful user merge rewrites referral, reward, and transaction foreign
        keys to the target. Consequently a frozen operator manifest can legitimately
        name that target. It must never name a source tombstone, though, and every
        inbound audit edge must still agree with the source's immutable merge marker.

        Participant rows are already locked in ascending order by the caller. The
        inbound source rows are deliberately read without an extra lock: their
        ``merged_into_user_id`` is database-immutable, while locking them after the
        targets would invert the user-merge lock order and introduce a deadlock.
        """

        merge_source = aliased(User, name="legacy_recovery_merge_source")
        merge_marker_source = aliased(User, name="legacy_recovery_merge_marker_source")
        merge_marker_audit = aliased(
            UserMergeAudit,
            name="legacy_recovery_merge_marker_audit",
        )
        marker_has_real_audit = (
            select(merge_marker_audit.id)
            .where(
                merge_marker_audit.dry_run.is_(False),
                merge_marker_audit.source_user_id == merge_marker_source.id,
                merge_marker_audit.target_user_id == User.id,
            )
            .correlate(User, merge_marker_source)
            .exists()
        )
        unattested_inbound_marker = (
            select(merge_marker_source.id)
            .where(
                merge_marker_source.merged_into_user_id == User.id,
                ~marker_has_real_audit,
            )
            .correlate(User)
            .exists()
        )
        return (
            select(User.id)
            .outerjoin(
                UserMergeAudit,
                and_(
                    UserMergeAudit.dry_run.is_(False),
                    or_(
                        UserMergeAudit.source_user_id == User.id,
                        UserMergeAudit.target_user_id == User.id,
                    ),
                ),
            )
            .outerjoin(
                merge_source,
                merge_source.id == UserMergeAudit.source_user_id,
            )
            .where(
                User.id.in_(sorted(participant_ids)),
                or_(
                    # A current participant must be the final merge target, never
                    # a source or a target that was subsequently merged onward.
                    User.merged_into_user_id.is_not(None),
                    User.merged_at.is_not(None),
                    UserMergeAudit.source_user_id == User.id,
                    # A source marker without the corresponding immutable audit
                    # edge is inconsistent even though the target itself is live.
                    unattested_inbound_marker,
                    and_(
                        UserMergeAudit.target_user_id == User.id,
                        or_(
                            # A valid inbound edge ends at this exact target and
                            # retains the canonical, empty source tombstone.
                            merge_source.id.is_(None),
                            merge_source.merged_into_user_id.is_distinct_from(User.id),
                            merge_source.merged_at.is_(None),
                            merge_source.is_blocked.is_not(True),
                            merge_source.telegram_id.is_not(None),
                            merge_source.email.is_not(None),
                            merge_source.current_subscription_id.is_not(None),
                        ),
                    ),
                ),
            )
            .limit(1)
        )

    @staticmethod
    def _legacy_recovery_request_provenance(
        recovery: LegacyReferralRewardRecoveryDto,
    ) -> dict[str, object]:
        provenance: dict[str, object] = {
            "reward_id": recovery.reward_id,
            "action": recovery.action.value,
            "expected_version": recovery.expected_version,
            "source_transaction_id": recovery.source_transaction_id,
            "origin_referral_id": recovery.origin_referral_id,
            "level": recovery.level.value if recovery.level is not None else None,
            "expected_reward_amount": recovery.expected_reward_amount,
            "accrual_strategy_snapshot": (
                recovery.accrual_strategy_snapshot.value
                if recovery.accrual_strategy_snapshot is not None
                else None
            ),
            "reward_strategy": (
                recovery.reward_strategy.value if recovery.reward_strategy is not None else None
            ),
            "config_value": recovery.config_value,
            "operator_reference": recovery.operator_reference,
            "reason": recovery.reason,
            "resolved_by": recovery.resolved_by,
            "evidence_sha256": recovery.evidence_sha256,
            "authorization_manifest_sha256": recovery.authorization_manifest_sha256,
        }
        if recovery.action == LegacyReferralRewardRecoveryAction.RETRY_OPERATOR_DIRECTED:
            provenance.update(
                expected_user_id=recovery.expected_user_id,
                expected_referral_id=recovery.expected_referral_id,
                expected_created_at=(
                    recovery.expected_created_at.isoformat()
                    if recovery.expected_created_at is not None
                    else None
                ),
                expected_participant_merge_audit_ids=list(
                    recovery.expected_participant_merge_audit_ids
                ),
                source_validation=(
                    recovery.source_validation.value
                    if recovery.source_validation is not None
                    else None
                ),
            )
        return provenance

    @staticmethod
    def _legacy_recovery_transition_values(
        recovery: LegacyReferralRewardRecoveryDto,
        *,
        source_transaction_id: int,
        origin_referral_id: int,
        issued_at: Optional[datetime],
    ) -> dict[str, object]:
        confirm_compensated = (
            recovery.action == LegacyReferralRewardRecoveryAction.CONFIRM_ADMIN_COMPENSATED
        )
        values: dict[str, object] = {
            "state": (
                ReferralRewardState.ISSUED if confirm_compensated else ReferralRewardState.PENDING
            ),
            "is_issued": confirm_compensated,
            "issued_at": issued_at if confirm_compensated else None,
            "attempt_count": 0,
            "next_attempt_at": None,
            "processing_token_hash": None,
            "processing_lease_expires_at": None,
            "last_error": None,
            "manual_alerted_at": None,
            "manual_cause": None,
            "refund_detected_at": None,
        }
        if recovery.action == LegacyReferralRewardRecoveryAction.RETRY_PROVEN_MISSING:
            values.update(
                source_transaction_id=source_transaction_id,
                origin_referral_id=origin_referral_id,
                level=recovery.level,
                accrual_strategy_snapshot=recovery.accrual_strategy_snapshot,
                # Claim the proven historical ON_FIRST winner now. The partial
                # unique index keeps it stable until the worker runs.
                accrual_strategy=recovery.accrual_strategy_snapshot,
                reward_strategy=recovery.reward_strategy,
                config_value=recovery.config_value,
            )
        elif recovery.action == LegacyReferralRewardRecoveryAction.RETRY_OPERATOR_DIRECTED:
            values["operator_recovery_manifest_sha256"] = (
                recovery.authorization_manifest_sha256
            )
        return values

    @staticmethod
    def _validate_0052_legacy_reward_shape(
        reward: ReferralReward,
        recovery: LegacyReferralRewardRecoveryDto,
    ) -> None:
        if (
            reward.state != ReferralRewardState.MANUAL_REQUIRED
            or recovery.expected_version != 1
            or reward.manual_incident_version != recovery.expected_version
            or reward.manual_cause != "LEGACY_AMBIGUOUS_ISSUANCE"
            or reward.last_error != "LEGACY_AMBIGUOUS_ISSUANCE"
            or reward.type != ReferralRewardType.EXTRA_DAYS
            or isinstance(reward.amount, bool)
            or reward.amount <= 0
            or reward.amount != recovery.expected_reward_amount
            or reward.is_issued
            or reward.issued_at is not None
            or reward.attempt_count != 0
            or reward.next_attempt_at is not None
            or reward.processing_token_hash is not None
            or reward.processing_lease_expires_at is not None
            or reward.source_transaction_id is not None
            or reward.origin_referral_id is not None
            or reward.level is not None
            or reward.accrual_strategy_snapshot is not None
            or reward.accrual_strategy is not None
            or reward.reward_strategy is not None
            or reward.config_value is not None
            or reward.target_subscription_id is not None
            or reward.baseline_expire_at is not None
            or reward.target_expire_at is not None
            or reward.refund_detected_at is not None
            or getattr(reward, "operator_recovery_manifest_sha256", None) is not None
        ):
            raise ValueError(
                f"Referral reward '{recovery.reward_id}' is not the exact unresolved "
                "0052 legacy EXTRA_DAYS shape"
            )

    @staticmethod
    def _validate_legacy_reward_source_window(
        reward: ReferralReward,
        source_evidence_at: datetime,
    ) -> None:
        if reward.created_at is None:
            raise ValueError("Legacy reward/source timestamps are missing")
        try:
            delay = reward.created_at - source_evidence_at
        except TypeError as exc:
            raise ValueError("Legacy reward/source timestamps are incompatible") from exc
        if abs(delay) > timedelta(minutes=5):
            raise ValueError("Legacy reward creation is outside the proven fulfillment window")

    @staticmethod
    def _legacy_recovery_source_evidence_timestamp(
        source: Transaction,
    ) -> tuple[str, datetime]:
        for kind, value in (
            ("fulfillment_completed_at", source.fulfillment_completed_at),
            ("fulfillment_started_at", source.fulfillment_started_at),
            ("created_at", source.created_at),
        ):
            if value is not None:
                return kind, value
        raise ValueError("Legacy source evidence timestamp is missing")

    @classmethod
    def _validate_legacy_recovery_source(
        cls,
        source: Transaction,
        action: LegacyReferralRewardRecoveryAction,
        source_validation: Optional[LegacyReferralRewardSourceValidation] = None,
    ) -> None:
        try:
            final_amount = Decimal(str(source.pricing["final_amount"]))
        except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
            raise ValueError("Source paid amount is invalid") from exc
        provider_succeeded = (
            action == LegacyReferralRewardRecoveryAction.RETRY_OPERATOR_DIRECTED
            and source_validation
            == LegacyReferralRewardSourceValidation.PROVIDER_SUCCEEDED
        )
        if (
            source.is_test
            or final_amount <= 0
            or not isinstance(source.plan_snapshot, dict)
            or source.plan_snapshot.get("is_trial") is not False
        ):
            raise ValueError(
                "Source must be completed, fulfilled, non-test, paid, non-trial, and non-refunded"
            )
        if provider_succeeded:
            if not (
                source.status == TransactionStatus.FAILED
                and source.gateway_type == PaymentGatewayType.YOOKASSA
                and source.fulfillment_status == TransactionFulfillmentStatus.MANUAL_REQUIRED
                and source.fulfillment_completed_at is None
                and source.fulfillment_started_at is not None
                and source.fulfillment_token_hash is None
                and source.fulfillment_lease_expires_at is None
            ):
                raise ValueError(
                    "PROVIDER_SUCCEEDED requires the exact failed local YooKassa source shape"
                )
            cls._legacy_recovery_source_evidence_timestamp(source)
            return
        if source.status != TransactionStatus.COMPLETED:
            raise ValueError("Local recovery source must remain completed and non-refunded")
        if (
            action == LegacyReferralRewardRecoveryAction.RETRY_OPERATOR_DIRECTED
            and source_validation
            != LegacyReferralRewardSourceValidation.LOCAL_COMPLETED
        ):
            raise ValueError("Operator-directed source validation class is missing")
        if action == LegacyReferralRewardRecoveryAction.RETRY_PROVEN_MISSING:
            if (
                source.fulfillment_status != TransactionFulfillmentStatus.SUCCEEDED
                or source.fulfillment_completed_at is None
            ):
                raise ValueError(
                    "RETRY_PROVEN_MISSING requires a succeeded source with a durable "
                    "fulfillment timestamp"
                )
        elif not (
            (
                source.fulfillment_status == TransactionFulfillmentStatus.SUCCEEDED
                and source.fulfillment_completed_at is not None
            )
            or (
                source.fulfillment_status == TransactionFulfillmentStatus.MANUAL_REQUIRED
                and source.fulfillment_completed_at is None
                and source.fulfillment_last_error == "LEGACY_COMPLETED_WITHOUT_PROOF"
                and source.fulfillment_started_at is not None
                and source.fulfillment_token_hash is None
                and source.fulfillment_lease_expires_at is None
            )
        ):
            raise ValueError(
                f"{action.value} requires a succeeded source or the exact "
                "legacy manual-required source shape"
            )
        cls._legacy_recovery_source_evidence_timestamp(source)

    @staticmethod
    def _legacy_recovery_extra_days_amount(
        source: Transaction,
        strategy: ReferralRewardStrategy,
        config_value: int,
    ) -> int:
        if isinstance(config_value, bool) or config_value <= 0:
            raise ValueError("Historical reward config must be a positive integer")
        if strategy == ReferralRewardStrategy.AMOUNT:
            return config_value
        if strategy != ReferralRewardStrategy.PERCENT:
            raise ValueError("Unsupported historical reward strategy")
        duration = source.plan_snapshot.get("duration")
        if isinstance(duration, bool):
            raise ValueError("Source plan duration is invalid")
        try:
            duration_value = Decimal(str(duration))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("Source plan duration is invalid") from exc
        if duration_value <= 0:
            raise ValueError("Source plan duration is invalid")
        return max(1, int(duration_value * Decimal(config_value) / Decimal(100)))

    async def get_referral_chain(
        self,
        referred_id: int,
    ) -> tuple[Optional[ReferralDto], Optional[ReferralDto]]:
        first_level = await self.get_by_referred_id(referred_id)
        if not first_level:
            return None, None

        second_level = await self.get_by_referred_id(first_level.referrer.id)

        logger.debug(
            f"Referral chain for user_id '{referred_id}': "
            f"level 1 referrer id='{first_level.referrer.id}', "
            f"level 2 referrer id='{second_level.referrer.id if second_level else 'none'}'"
        )

        return first_level, second_level

    async def lock_referral_attribution(
        self,
        referred_id: int,
        referrer_ids: tuple[int, ...] = (),
    ) -> None:
        # User merge takes the same rows in ascending order before rewriting
        # attribution. Lock the payer and every L1/L2 recipient deterministically,
        # then lock their attribution rows. The caller re-reads and validates the
        # chain after this fence before creating any durable intent.
        participant_ids = tuple(sorted({referred_id, *referrer_ids}))
        await self.session.execute(
            select(User.id).where(User.id.in_(participant_ids)).order_by(User.id).with_for_update()
        )
        await self.session.execute(
            select(Referral.id)
            .where(Referral.referred_id.in_(participant_ids))
            .order_by(Referral.id)
            .with_for_update()
        )

    @staticmethod
    def _referral_network_stats_statement() -> Select[Any]:
        # A referral row stores one direct attribution edge. Whether that edge also
        # represents an L2 referral depends on the referrer's own attribution, so it
        # must be derived from the graph instead of Referral.level legacy metadata.
        referrer_attribution = aliased(Referral, name="referrer_attribution")
        canonical_referrer = aliased(User, name="canonical_referrer")
        canonical_referred = aliased(User, name="canonical_referred")
        canonical_level_2_owner = aliased(User, name="canonical_level_2_owner")
        return (
            select(
                func.count(Referral.id).label("total_referrals"),
                func.count(Referral.id).label("level_1_count"),
                func.count(canonical_level_2_owner.id).label("level_2_count"),
                func.count(func.distinct(Referral.referrer_id)).label("unique_referrers"),
            )
            .select_from(Referral)
            .join(canonical_referrer, canonical_referrer.id == Referral.referrer_id)
            .join(canonical_referred, canonical_referred.id == Referral.referred_id)
            .outerjoin(
                referrer_attribution,
                referrer_attribution.referred_id == Referral.referrer_id,
            )
            .outerjoin(
                canonical_level_2_owner,
                and_(
                    canonical_level_2_owner.id == referrer_attribution.referrer_id,
                    canonical_level_2_owner.merged_into_user_id.is_(None),
                ),
            )
            .where(
                canonical_referrer.merged_into_user_id.is_(None),
                canonical_referred.merged_into_user_id.is_(None),
            )
        )

    @staticmethod
    def _user_referral_network_stats_statement(user_id: int) -> Select[Any]:
        direct_referral = aliased(Referral, name="direct_referral")
        second_level_referral = aliased(Referral, name="second_level_referral")
        canonical_direct_referred = aliased(User, name="canonical_direct_referred")
        canonical_second_referred = aliased(User, name="canonical_second_referred")
        return (
            select(
                func.count(func.distinct(direct_referral.id)).label("level_1"),
                func.count(canonical_second_referred.id).label("level_2"),
            )
            .select_from(direct_referral)
            .join(
                canonical_direct_referred,
                canonical_direct_referred.id == direct_referral.referred_id,
            )
            .outerjoin(
                second_level_referral,
                second_level_referral.referrer_id == direct_referral.referred_id,
            )
            .outerjoin(
                canonical_second_referred,
                and_(
                    canonical_second_referred.id == second_level_referral.referred_id,
                    canonical_second_referred.merged_into_user_id.is_(None),
                ),
            )
            .where(
                direct_referral.referrer_id == user_id,
                canonical_direct_referred.merged_into_user_id.is_(None),
            )
        )

    async def get_stats(self) -> ReferralStatisticsDto:
        stmt = self._referral_network_stats_statement()

        rewards_stmt = select(
            func.sum(case((ReferralReward.is_issued.is_(True), 1), else_=0)).label(
                "total_rewards_issued"
            ),
            func.sum(
                case(
                    (
                        and_(
                            ReferralReward.is_issued.is_(True),
                            ReferralReward.type == ReferralRewardType.POINTS,
                        ),
                        ReferralReward.amount,
                    ),
                    else_=0,
                )
            ).label("total_points_issued"),
            func.sum(
                case(
                    (
                        and_(
                            ReferralReward.is_issued.is_(True),
                            ReferralReward.type == ReferralRewardType.EXTRA_DAYS,
                        ),
                        ReferralReward.amount,
                    ),
                    else_=0,
                )
            ).label("total_days_issued"),
        )

        top_referrer_user = aliased(User, name="top_referrer_user")
        top_referred_user = aliased(User, name="top_referred_user")
        top_referrer_stmt = (
            select(
                Referral.referrer_id,
                func.count().label("referrals_count"),
            )
            .join(top_referrer_user, top_referrer_user.id == Referral.referrer_id)
            .join(top_referred_user, top_referred_user.id == Referral.referred_id)
            .where(
                top_referrer_user.merged_into_user_id.is_(None),
                top_referred_user.merged_into_user_id.is_(None),
            )
            .group_by(Referral.referrer_id)
            .order_by(func.count().desc())
            .limit(1)
        )

        referral_row = (await self.session.execute(stmt)).mappings().one()
        reward_row = (await self.session.execute(rewards_stmt)).mappings().one()
        top_referrer_row = (await self.session.execute(top_referrer_stmt)).mappings().first()

        logger.debug("Referral stats fetched")
        return ReferralStatisticsDto(
            total_referrals=int(referral_row["total_referrals"] or 0),
            level_1_count=int(referral_row["level_1_count"] or 0),
            level_2_count=int(referral_row["level_2_count"] or 0),
            unique_referrers=int(referral_row["unique_referrers"] or 0),
            total_rewards_issued=int(reward_row["total_rewards_issued"] or 0),
            total_points_issued=int(reward_row["total_points_issued"] or 0),
            total_days_issued=int(reward_row["total_days_issued"] or 0),
            top_referrer_referrals_count=int(top_referrer_row["referrals_count"])
            if top_referrer_row
            else 0,
            top_referrer_id=top_referrer_row["referrer_id"] if top_referrer_row else None,
        )

    async def get_user_referral_stats(self, user_id: int) -> UserReferralStatsDto:
        # Referrer info: find the User who referred this user (referred_id = user_id)
        referrer_stmt = (
            select(User.telegram_id, User.email, User.username)
            .join(Referral, Referral.referrer_id == User.id)
            .where(Referral.referred_id == user_id)
        )

        invited_stmt = self._user_referral_network_stats_statement(user_id)

        rewards_stmt = select(
            func.sum(
                case(
                    (
                        and_(
                            ReferralReward.is_issued.is_(True),
                            ReferralReward.type == ReferralRewardType.POINTS,
                        ),
                        ReferralReward.amount,
                    ),
                    else_=0,
                )
            ).label("reward_points"),
            func.sum(
                case(
                    (
                        and_(
                            ReferralReward.is_issued.is_(True),
                            ReferralReward.type == ReferralRewardType.EXTRA_DAYS,
                        ),
                        ReferralReward.amount,
                    ),
                    else_=0,
                )
            ).label("reward_days"),
        ).where(ReferralReward.user_id == user_id)

        referrer_row = (await self.session.execute(referrer_stmt)).mappings().first()
        invited_row = (await self.session.execute(invited_stmt)).mappings().one()
        rewards_row = (await self.session.execute(rewards_stmt)).mappings().one()

        return UserReferralStatsDto(
            referrer_telegram_id=referrer_row["telegram_id"] if referrer_row else None,
            referrer_email=referrer_row["email"] if referrer_row else None,
            referrer_username=referrer_row["username"] if referrer_row else None,
            referrals_level_1=int(invited_row["level_1"] or 0),
            referrals_level_2=int(invited_row["level_2"] or 0),
            reward_points=int(rewards_row["reward_points"] or 0),
            reward_days=int(rewards_row["reward_days"] or 0),
        )

    async def get_referrals_with_payment_count(self, user_id: int) -> int:
        referred_user = aliased(User, name="paid_referral_referred")
        stmt = (
            select(func.count(func.distinct(Referral.referred_id)))
            .join(referred_user, referred_user.id == Referral.referred_id)
            .join(Transaction, Transaction.user_id == Referral.referred_id)
            .where(
                Referral.referrer_id == user_id,
                referred_user.merged_into_user_id.is_(None),
                Transaction.status == TransactionStatus.COMPLETED,
                Transaction.fulfillment_status == TransactionFulfillmentStatus.SUCCEEDED,
                Transaction.is_test.is_(False),
                Transaction.pricing["final_amount"].astext.cast(Numeric) > 0,
                Transaction.plan_snapshot["is_trial"].astext == "false",
            )
        )
        count = await self.session.scalar(stmt) or 0

        logger.debug(f"User_id '{user_id}' has '{count}' referrals with payments")
        return int(count)
