import hashlib
import secrets
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from loguru import logger

from src.application.common import (
    EventPublisher,
    Interactor,
    Remnawave,
    SubscriptionMutationLock,
)
from src.application.common.dao import ReferralDao, SettingsDao, SubscriptionDao, UserDao
from src.application.common.uow import UnitOfWork
from src.application.dto import (
    LegacyReferralRewardRecoveryDto,
    ReferralRewardDto,
    TransactionDto,
    UserDto,
)
from src.application.events import ReferralRewardFailedEvent, ReferralRewardReceivedEvent
from src.application.legacy_referral_recovery import (
    LegacyReferralRecoveryAuthorizer,
)
from src.application.use_cases.referral.queries.calculations import (
    CalculateReferralReward,
    CalculateReferralRewardDto,
)
from src.core.enums import (
    LegacyReferralRewardRecoveryAction,
    LegacyReferralRewardSourceValidation,
    ReferralAccrualStrategy,
    ReferralLevel,
    ReferralRewardState,
    ReferralRewardType,
    SubscriptionStatus,
    TransactionFulfillmentStatus,
    TransactionStatus,
)
from src.core.utils.time import datetime_now

REWARD_LEASE = timedelta(minutes=5)
REWARD_RUN_LIMIT = 100
MISSING_SUBSCRIPTION_RETRY = timedelta(minutes=30)


@dataclass(frozen=True)
class GiveReferrerRewardDto:
    user_id: int
    reward: ReferralRewardDto
    referred_name: str
    token_hash: str


class GiveReferrerReward(Interactor[GiveReferrerRewardDto, None]):
    required_permission = None

    def __init__(
        self,
        uow: UnitOfWork,
        user_dao: UserDao,
        subscription_dao: SubscriptionDao,
        referral_dao: ReferralDao,
        event_publisher: EventPublisher,
        remnawave: Remnawave,
        subscription_mutation_lock: SubscriptionMutationLock,
    ) -> None:
        self.uow = uow
        self.user_dao = user_dao
        self.subscription_dao = subscription_dao
        self.referral_dao = referral_dao
        self.event_publisher = event_publisher
        self.remnawave = remnawave
        self.subscription_mutation_lock = subscription_mutation_lock

    async def _execute(  # noqa: C901
        self,
        actor: UserDto,
        data: GiveReferrerRewardDto,
    ) -> None:
        async with self.subscription_mutation_lock.hold(data.user_id):
            await self._execute_locked(actor, data)

    async def _execute_locked(  # noqa: C901
        self,
        actor: UserDto,
        data: GiveReferrerRewardDto,
    ) -> None:
        reward = data.reward

        user = await self.user_dao.get_by_id(data.user_id)
        if not user:
            async with self.uow:
                await self.referral_dao.mark_reward_manual_required(
                    reward.id,
                    token_hash=data.token_hash,
                    error_code="REWARD_RECIPIENT_NOT_FOUND",
                )
                await self.uow.commit()
            logger.critical(
                f"{actor.log} User '{data.user_id}' not found; reward '{reward.id}' "
                "requires manual review"
            )
            return

        logger.info(
            f"{actor.log} Start applying reward of '{reward.amount}' "
            f"'{reward.type}' to user '{user.remna_name}'"
        )
        if reward.type == ReferralRewardType.POINTS:
            try:
                async with self.uow:
                    if not await self._lock_source_or_cancel(data):
                        await self.uow.commit()
                        return
                    issued = await self.referral_dao.issue_points_reward(
                        reward.id,
                        user_id=user.id,
                        amount=reward.amount,
                        token_hash=data.token_hash,
                    )
                    await self.uow.commit()
            except Exception as exc:
                logger.exception(f"Failed to issue points reward '{reward.id}'")
                async with self.uow:
                    await self.referral_dao.defer_reward(
                        reward.id,
                        token_hash=data.token_hash,
                        retry_after=self._retry_after(reward.attempt_count),
                        error_code=self._error_code(exc),
                    )
                    await self.uow.commit()
                return
            if not issued:
                logger.info(f"Reward '{reward.id}' was already completed or reclaimed")
                return

        elif reward.type == ReferralRewardType.EXTRA_DAYS:
            subscription = await self.subscription_dao.get_current(user.id)

            if not self._is_safe_extra_days_subscription(subscription):
                async with self.uow:
                    await self.referral_dao.defer_reward(
                        reward.id,
                        token_hash=data.token_hash,
                        retry_after=MISSING_SUBSCRIPTION_RETRY,
                        error_code=(
                            "RECIPIENT_SUBSCRIPTION_TRIAL"
                            if subscription and subscription.is_trial
                            else (
                                "RECIPIENT_SUBSCRIPTION_CHANNEL_DISABLED"
                                if subscription and subscription.disabled_by_channel_leave
                                else (
                                    "RECIPIENT_SUBSCRIPTION_UNSAFE"
                                    if subscription
                                    else "RECIPIENT_SUBSCRIPTION_MISSING"
                                )
                            )
                        ),
                    )
                    await self.uow.commit()
                logger.info(
                    f"{actor.log} Paid subscription not found for '{user.remna_name}'; "
                    f"reward '{reward.id}' remains retryable"
                )
                return

            assert subscription is not None
            baseline_expire_at = subscription.expire_at
            baseline_status = subscription.status
            grant_started_at = datetime_now()
            target_expire_at = max(baseline_expire_at, grant_started_at) + timedelta(
                days=reward.amount
            )
            if reward.amount <= 0 or target_expire_at <= grant_started_at:
                async with self.uow:
                    await self.referral_dao.mark_reward_manual_required(
                        reward.id,
                        token_hash=data.token_hash,
                        error_code="INVALID_TARGET_EXPIRY",
                    )
                    await self.uow.commit()
                await self._publish_failed(user, data)
                return

            # Persist the absolute target before the external call. A crash or timeout
            # afterwards is ambiguous and is fenced to MANUAL_REQUIRED by the sweeper;
            # it is never replayed as another additive extension.
            async with self.uow:
                target_saved = await self.referral_dao.set_extra_days_target(
                    reward.id,
                    token_hash=data.token_hash,
                    subscription_id=subscription.id,
                    baseline_expire_at=baseline_expire_at,
                    target_expire_at=target_expire_at,
                )
                await self.uow.commit()
            if not target_saved:
                return

            try:
                async with self.uow:
                    # Keep the source transaction row locked through the external
                    # side effect and local completion. A concurrent refund UPDATE
                    # must wait, then the refund sweep opens clawback review.
                    if not await self._lock_source_or_cancel(data):
                        await self.uow.commit()
                        return

                    current_subscription = await self.subscription_dao.get_current(user.id)
                    if (
                        current_subscription is None
                        or current_subscription.id != subscription.id
                        or current_subscription.is_trial
                        or current_subscription.disabled_by_channel_leave
                        or current_subscription.status
                        not in (SubscriptionStatus.ACTIVE, SubscriptionStatus.EXPIRED)
                        or current_subscription.status != baseline_status
                        or current_subscription.expire_at != baseline_expire_at
                    ):
                        await self.referral_dao.mark_reward_manual_required(
                            reward.id,
                            token_hash=data.token_hash,
                            error_code="SUBSCRIPTION_CHANGED_BEFORE_EXTERNAL_GRANT",
                        )
                        await self.uow.commit()
                        logger.critical(
                            f"EXTRA_DAYS reward '{reward.id}' target subscription "
                            "changed; manual review required"
                        )
                        return

                    remote_baseline = await self.remnawave.get_user_by_uuid(
                        current_subscription.user_remna_id
                    )
                    if not self._matches_extra_days_remote_baseline(
                        expected_uuid=current_subscription.user_remna_id,
                        expected_expire_at=baseline_expire_at,
                        observed=remote_baseline,
                    ):
                        await self.referral_dao.mark_reward_manual_required(
                            reward.id,
                            token_hash=data.token_hash,
                            error_code="REMOTE_BASELINE_DRIFT",
                        )
                        await self.uow.commit()
                        logger.critical(
                            f"EXTRA_DAYS reward '{reward.id}' remote baseline changed; "
                            "manual review required"
                        )
                        return

                    # Reactivation is part of the same local transaction as reward
                    # completion. Persist ACTIVE before constructing the Remnawave
                    # update, but keep it uncommitted until exact read-after-write.
                    current_subscription.status = SubscriptionStatus.ACTIVE
                    current_subscription.expire_at = target_expire_at
                    updated = await self.subscription_dao.update(current_subscription)
                    if (
                        updated is None
                        or not self._is_active_remote_status(updated.status)
                        or not self._same_expiry(updated.expire_at, target_expire_at)
                    ):
                        raise RuntimeError("Subscription reactivation was not persisted")
                    update_response = await self.remnawave.reactivate_referral_expiry(
                        user_id=user.id,
                        uuid=current_subscription.user_remna_id,
                        expire_at=target_expire_at,
                    )
                    observed = await self.remnawave.get_user_by_uuid(
                        current_subscription.user_remna_id
                    )
                    self._verify_extra_days_target(
                        expected_uuid=current_subscription.user_remna_id,
                        expected_expire_at=target_expire_at,
                        update_response=update_response,
                        observed=observed,
                    )
                    issued = await self.referral_dao.finish_extra_days_reward(
                        reward.id,
                        token_hash=data.token_hash,
                    )
                    if not issued:
                        raise RuntimeError("Reward completion fence changed")
                    await self.uow.commit()
            except Exception as exc:
                logger.exception(
                    f"Ambiguous EXTRA_DAYS reward '{reward.id}' requires manual review"
                )
                async with self.uow:
                    await self.referral_dao.mark_reward_manual_required(
                        reward.id,
                        token_hash=data.token_hash,
                        error_code=self._error_code(exc, prefix="EXTRA_DAYS_AMBIGUOUS"),
                    )
                    await self.uow.commit()
                await self._publish_failed(user, data)
                return

        else:
            async with self.uow:
                await self.referral_dao.mark_reward_manual_required(
                    reward.id,
                    token_hash=data.token_hash,
                    error_code="UNKNOWN_REWARD_TYPE",
                )
                await self.uow.commit()
            raise ValueError(
                f"Failed to apply reward: unknown type '{reward.type}' for user '{user.remna_name}'"
            )

        if reward.operator_recovery_manifest_sha256 is None:
            event_reward = ReferralRewardReceivedEvent(
                user=user,
                name=data.referred_name,
                value=reward.amount,
                reward_type=reward.type,
            )
            await self.event_publisher.publish(event_reward)
        else:
            logger.info(
                f"Operator-directed reward '{reward.id}' completed without a "
                "per-row customer notification"
            )
        logger.info(f"{actor.log} Finished applying reward to user '{user.id}'")

    async def _lock_source_or_cancel(self, data: GiveReferrerRewardDto) -> bool:
        if await self.referral_dao.lock_reward_source_if_eligible(
            data.reward.id,
            token_hash=data.token_hash,
        ):
            return True
        await self.referral_dao.cancel_claimed_reward(
            data.reward.id,
            token_hash=data.token_hash,
            error_code="SOURCE_NOT_ELIGIBLE_BEFORE_GRANT",
        )
        logger.warning(
            f"Reward '{data.reward.id}' canceled before side effect because its "
            "source transaction is no longer completed/succeeded"
        )
        return False

    @classmethod
    def _verify_extra_days_target(
        cls,
        *,
        expected_uuid: object,
        expected_expire_at: datetime,
        update_response: object,
        observed: object,
    ) -> None:
        response_uuid = getattr(update_response, "uuid", None)
        response_expire_at = getattr(update_response, "expire_at", None)
        response_status = getattr(update_response, "status", None)
        observed_uuid = getattr(observed, "uuid", None)
        observed_expire_at = getattr(observed, "expire_at", None)
        observed_status = getattr(observed, "status", None)
        if (
            str(response_uuid) != str(expected_uuid)
            or not cls._same_expiry(response_expire_at, expected_expire_at)
            or not cls._is_active_remote_status(response_status)
            or str(observed_uuid) != str(expected_uuid)
            or not cls._same_expiry(observed_expire_at, expected_expire_at)
            or not cls._is_active_remote_status(observed_status)
        ):
            raise RuntimeError(
                "Remnawave EXTRA_DAYS target mismatch "
                f"(expected_uuid={expected_uuid}, response_uuid={response_uuid}, "
                f"observed_uuid={observed_uuid}, expected_expire_at={expected_expire_at}, "
                f"response_expire_at={response_expire_at}, "
                f"observed_expire_at={observed_expire_at}, "
                f"response_status={response_status}, observed_status={observed_status})"
            )

    @staticmethod
    def _same_expiry(observed: object, expected: datetime) -> bool:
        if not isinstance(observed, datetime):
            return False
        observed_value = observed
        expected_value = expected
        if observed_value.tzinfo is None:
            observed_value = observed_value.replace(tzinfo=timezone.utc)
        if expected_value.tzinfo is None:
            expected_value = expected_value.replace(tzinfo=timezone.utc)
        return abs((observed_value - expected_value).total_seconds()) <= 1

    @classmethod
    def _matches_extra_days_remote_baseline(
        cls,
        *,
        expected_uuid: object,
        expected_expire_at: datetime,
        observed: object,
    ) -> bool:
        observed_status = getattr(observed, "status", None)
        status_value = getattr(observed_status, "value", observed_status)
        return bool(
            str(getattr(observed, "uuid", None)) == str(expected_uuid)
            and cls._same_expiry(
                getattr(observed, "expire_at", None),
                expected_expire_at,
            )
            and isinstance(status_value, str)
            and status_value.upper()
            in (SubscriptionStatus.ACTIVE.value, SubscriptionStatus.EXPIRED.value)
        )

    @staticmethod
    def _is_safe_extra_days_subscription(subscription: object) -> bool:
        return bool(
            subscription is not None
            and not getattr(subscription, "is_trial", True)
            and not getattr(subscription, "disabled_by_channel_leave", True)
            and getattr(subscription, "status", None)
            in (SubscriptionStatus.ACTIVE, SubscriptionStatus.EXPIRED)
        )

    @staticmethod
    def _is_active_remote_status(status: object) -> bool:
        value = getattr(status, "value", status)
        return isinstance(value, str) and value.upper() == SubscriptionStatus.ACTIVE.value

    async def _publish_failed(self, user: UserDto, data: GiveReferrerRewardDto) -> None:
        if data.reward.operator_recovery_manifest_sha256 is not None:
            logger.warning(
                f"Operator-directed reward '{data.reward.id}' failed without a "
                "per-row customer notification"
            )
            return
        await self.event_publisher.publish(
            ReferralRewardFailedEvent(
                user=user,
                name=data.referred_name,
                value=data.reward.amount,
                reward_type=data.reward.type,
            )
        )

    @staticmethod
    def _retry_after(attempt_count: int) -> timedelta:
        return timedelta(seconds=min(3600, 60 * (2 ** min(attempt_count, 6))))

    @staticmethod
    def _error_code(exc: Exception, *, prefix: str = "REWARD") -> str:
        name = "".join(c if c.isalnum() else "_" for c in type(exc).__name__).upper()
        return f"{prefix}_{name}"[:64]


@dataclass(frozen=True)
class AssignReferralRewardsDto:
    user: UserDto
    transaction: TransactionDto


class AssignReferralRewards(Interactor[AssignReferralRewardsDto, None]):
    required_permission = None

    def __init__(
        self,
        uow: UnitOfWork,
        settings_dao: SettingsDao,
        referral_dao: ReferralDao,
        calculate_referral_reward: CalculateReferralReward,
    ) -> None:
        self.uow = uow
        self.settings_dao = settings_dao
        self.referral_dao = referral_dao
        self.calculate_referral_reward = calculate_referral_reward

    async def _execute(self, actor: UserDto, data: AssignReferralRewardsDto) -> None:  # noqa: C901
        settings = await self.settings_dao.get()

        if not settings.referral.enable:
            logger.info("Referral system is disabled; reward assignment skipped")
            return

        if data.transaction.is_test or data.transaction.pricing.is_free:
            logger.info(f"Skip rewards: transaction '{data.transaction.id}' is not paid")
            return

        if data.transaction.plan_snapshot and data.transaction.plan_snapshot.is_trial:
            logger.info(
                f"Skip rewards: transaction '{data.transaction.id}' is a trial plan purchase"
            )
            return

        if data.transaction.status != TransactionStatus.COMPLETED or (
            data.transaction.fulfillment_status
            not in {
                TransactionFulfillmentStatus.PROCESSING,
                TransactionFulfillmentStatus.SUCCEEDED,
            }
        ):
            logger.info(
                f"Skip rewards: transaction '{data.transaction.id}' is not in a "
                "successful fulfillment window"
            )
            return

        async with self.uow:
            initial_referral, initial_parent = await self.referral_dao.get_referral_chain(
                data.user.id
            )
            initial_signature = self._chain_signature(initial_referral, initial_parent)
            referrer_ids = tuple(
                sorted(
                    {
                        item.referrer.id
                        for item in (initial_referral, initial_parent)
                        if item is not None
                    }
                )
            )
            await self.referral_dao.lock_referral_attribution(
                data.user.id,
                referrer_ids,
            )
            referral, parent = await self.referral_dao.get_referral_chain(data.user.id)
            if self._chain_signature(referral, parent) != initial_signature:
                # The statement snapshot was read while a merge/attach owned one
                # of the user rows. Retry the payment finalization from a fresh
                # transaction; never create an intent for an unlocked recipient.
                raise RuntimeError(
                    "Referral attribution changed while acquiring its mutation fence"
                )

            if not referral:
                logger.info(f"{data.user.log} not referred; reward assignment skipped")
                await self.uow.commit()
                return

            reward_type = settings.referral.reward.type
            reward_chain = {ReferralLevel.FIRST: referral.referrer}
            referral_ids = {ReferralLevel.FIRST: referral.id}

            if parent:
                reward_chain[ReferralLevel.SECOND] = parent.referrer
                referral_ids[ReferralLevel.SECOND] = parent.id

            for level, referrer in reward_chain.items():
                if level > settings.referral.level:
                    continue

                config_value = settings.referral.reward.config.get(level)
                if config_value is None:
                    logger.info(f"No reward config for level '{level.name}'")
                    continue

                reward_amount = await self.calculate_referral_reward.system(
                    CalculateReferralRewardDto(
                        settings=settings.referral,
                        transaction=data.transaction,
                        config_value=config_value,
                    )
                )

                if not reward_amount or reward_amount <= 0:
                    logger.warning(
                        f"Reward amount <= 0 for referrer '{referrer.remna_name}', "
                        f"level '{level.name}'"
                    )
                    continue

                created = await self.referral_dao.create_reward(
                    reward=ReferralRewardDto(
                        user_id=referrer.id,
                        type=reward_type,
                        amount=reward_amount,
                        is_issued=False,
                        source_transaction_id=data.transaction.id,
                        origin_referral_id=referral.id,
                        level=level,
                        accrual_strategy_snapshot=settings.referral.accrual_strategy,
                        accrual_strategy=(
                            settings.referral.accrual_strategy
                            if settings.referral.accrual_strategy
                            != ReferralAccrualStrategy.ON_FIRST_PAYMENT
                            else None
                        ),
                        reward_strategy=settings.referral.reward.strategy,
                        config_value=config_value,
                        state=ReferralRewardState.PENDING,
                    ),
                    referral_id=referral_ids[level],
                )

                if created is None:
                    logger.info(
                        f"Skipped duplicate reward intent for source "
                        f"'{data.transaction.id}' level '{level.name}': provenance "
                        "is already consumed"
                    )
                    continue

                logger.info(
                    f"Persisted '{reward_type}' reward intent '{reward_amount}' for referrer "
                    f"'{referrer.remna_name}' (level '{level.name}')"
                )

            # All levels are one durable unit. Database/calculation errors deliberately
            # propagate so payment fulfillment cannot be marked SUCCEEDED without its
            # reward intents.
            await self.uow.commit()

    @staticmethod
    def _chain_signature(referral: object, parent: object) -> tuple[object, ...]:
        def item_signature(item: object) -> tuple[object, object] | None:
            if item is None:
                return None
            return (getattr(item, "id"), getattr(getattr(item, "referrer"), "id"))

        return (item_signature(referral), item_signature(parent))


class RetryPendingReferralRewards(Interactor[None, int]):
    required_permission = None

    def __init__(
        self,
        uow: UnitOfWork,
        referral_dao: ReferralDao,
        give_referrer_reward: GiveReferrerReward,
    ) -> None:
        self.uow = uow
        self.referral_dao = referral_dao
        self.give_referrer_reward = give_referrer_reward

    async def _execute(self, actor: UserDto, data: None = None) -> int:
        processed = 0
        # Claim just in time. A sequential batch with one shared five-minute lease
        # lets later rows expire while an earlier external call is still running.
        for _ in range(REWARD_RUN_LIMIT):
            token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(
                f"remnashop:referral-reward:v1\0{token}".encode()
            ).hexdigest()
            async with self.uow:
                rewards = await self.referral_dao.claim_pending_rewards(
                    token_hash=token_hash,
                    lease_for=REWARD_LEASE,
                    limit=1,
                )
                await self.uow.commit()
            if not rewards:
                break

            reward = rewards[0]
            processed += 1
            try:
                referred_name = await self.referral_dao.get_reward_referred_name(reward.id)
                await self.give_referrer_reward.system(
                    GiveReferrerRewardDto(
                        user_id=reward.user_id,
                        reward=reward,
                        referred_name=referred_name,
                        token_hash=token_hash,
                    )
                )
            except Exception:
                logger.exception(f"Referral reward worker failed on reward '{reward.id}'")
                # Failures before the grant use case starts (for example, resolving
                # the display name) used to strand a safe claim in PROCESSING until
                # its lease expired. Reset the session and release only claims that
                # have no persisted external target; issued or ambiguous rows remain
                # protected by their state/target fences.
                await self.uow.rollback()
                async with self.uow:
                    await self.referral_dao.defer_reward(
                        reward.id,
                        token_hash=token_hash,
                        retry_after=GiveReferrerReward._retry_after(reward.attempt_count),
                        error_code="REWARD_WORKER_UNEXPECTED_FAILURE",
                    )
                    await self.uow.commit()

        async with self.uow:
            manual = await self.referral_dao.claim_manual_required_rewards_for_alert(limit=20)
            if manual:
                # Emit before the durable alert marker. A crash may duplicate an
                # alert, but can never silently lose the operator notification.
                logger.critical(
                    "Referral rewards require operator review: {}",
                    [reward.id for reward in manual],
                )
                await self.referral_dao.mark_manual_rewards_alerted(
                    [reward.id for reward in manual]
                )
            await self.uow.commit()
        return processed


@dataclass(frozen=True)
class ResolveManualReferralRewardDto:
    reward_id: int
    expected_version: int
    confirm_issued: bool
    operator_reference: str
    reason: str
    resolved_by: str = "ADMIN_API"
    allow_drift: bool = False
    ack_admin_compensated_refund: bool = False


@dataclass(frozen=True)
class ManualReferralRewardEvidence:
    observed_subscription_id: int | None = None
    observed_remote_uuid: str | None = None
    observed_expire_at: datetime | None = None


class ResolveManualReferralReward(Interactor[ResolveManualReferralRewardDto, None]):
    """Record an operator decision without replaying an ambiguous side effect."""

    required_permission = None

    def __init__(
        self,
        uow: UnitOfWork,
        referral_dao: ReferralDao,
        user_dao: UserDao,
        subscription_dao: SubscriptionDao,
        remnawave: Remnawave,
        subscription_mutation_lock: SubscriptionMutationLock,
    ) -> None:
        self.uow = uow
        self.referral_dao = referral_dao
        self.user_dao = user_dao
        self.subscription_dao = subscription_dao
        self.remnawave = remnawave
        self.subscription_mutation_lock = subscription_mutation_lock

    async def _execute(  # noqa: C901
        self,
        actor: UserDto,
        data: ResolveManualReferralRewardDto,
    ) -> None:
        if not data.operator_reference.strip() or not data.reason.strip():
            raise ValueError("Operator reference and reason are required")
        if data.ack_admin_compensated_refund and (data.confirm_issued or data.allow_drift):
            raise ValueError(
                "ADMIN compensation refund acknowledgment is a distinct no-drift action"
            )

        reward = await self.referral_dao.get_reward_by_id(data.reward_id)
        if reward is None:
            raise ValueError(f"Referral reward '{data.reward_id}' was not found")

        existing_match = await self.referral_dao.manual_resolution_match(
            data.reward_id,
            expected_version=data.expected_version,
            confirm_issued=data.confirm_issued,
            operator_reference=data.operator_reference,
            resolved_by=data.resolved_by,
            reason=data.reason,
            allow_drift=data.allow_drift,
            ack_admin_compensated_refund=data.ack_admin_compensated_refund,
        )
        if existing_match is True:
            logger.info(f"Manual referral reward resolution '{data.reward_id}' replayed")
            return
        if existing_match is False:
            raise ValueError(
                f"Referral reward '{data.reward_id}' was resolved with different evidence"
            )

        if (
            data.confirm_issued
            and reward.accrual_strategy_snapshot == ReferralAccrualStrategy.ON_FIRST_PAYMENT
            and reward.accrual_strategy != ReferralAccrualStrategy.ON_FIRST_PAYMENT
        ):
            # A marker-less MANUAL row never atomically won first-payment
            # eligibility. Another transaction may already own the unique marker;
            # confirming this row would grant a second ON_FIRST reward.
            raise ValueError(
                "Cannot confirm an ON_FIRST_PAYMENT reward that did not claim "
                "first-payment eligibility; resolve/cancel the source and let the "
                "worker select the winner"
            )

        async with self.subscription_mutation_lock.hold(reward.user_id):
            async with self.uow:
                reward = await self.referral_dao.get_reward_by_id(
                    data.reward_id,
                    for_update=True,
                )
                if reward is None:
                    raise ValueError(f"Referral reward '{data.reward_id}' was not found")
                if reward.manual_incident_version != data.expected_version:
                    raise ValueError(
                        f"Manual reward incident version changed: expected "
                        f"'{data.expected_version}', current "
                        f"'{reward.manual_incident_version}'"
                    )

                if (
                    data.confirm_issued
                    and reward.accrual_strategy_snapshot == ReferralAccrualStrategy.ON_FIRST_PAYMENT
                    and reward.accrual_strategy != ReferralAccrualStrategy.ON_FIRST_PAYMENT
                ):
                    raise ValueError(
                        "Cannot confirm an ON_FIRST_PAYMENT reward that did not "
                        "claim first-payment eligibility"
                    )

                source_status: TransactionStatus | None = None
                if data.ack_admin_compensated_refund:
                    if not self._is_admin_compensated_refund_incident(reward):
                        raise ValueError(
                            "Reward is not an exact ADMIN-compensated later-refund incident"
                        )
                    source_status = await self.referral_dao.lock_manual_reward_source_status(
                        data.reward_id
                    )
                    if source_status != TransactionStatus.REFUNDED:
                        raise ValueError("ADMIN-compensated source is not currently refunded")
                elif (
                    reward.source_transaction_id is not None
                    or reward.operator_recovery_manifest_sha256 is not None
                ):
                    source_status = await self.referral_dao.lock_manual_reward_source_status(
                        data.reward_id
                    )
                    if source_status is None:
                        raise ValueError("Manual reward source transaction was not found")
                    if (
                        source_status == TransactionStatus.REFUNDED
                        and data.confirm_issued
                        and not data.allow_drift
                    ):
                        raise ValueError(
                            "Cannot confirm a refunded reward without an audited drift override"
                        )

                evidence = ManualReferralRewardEvidence()
                if (
                    reward.type == ReferralRewardType.EXTRA_DAYS
                    and not data.ack_admin_compensated_refund
                ):
                    if self._is_unapplied_admin_earlier_payment_incident(reward):
                        if data.confirm_issued or data.allow_drift:
                            raise ValueError(
                                "An unapplied ADMIN-earlier reward can only be canceled "
                                "without a drift override"
                            )
                    else:
                        evidence = await self._reconcile_extra_days(
                            reward,
                            data.confirm_issued,
                            data.allow_drift,
                        )

                resolved = await self.referral_dao.resolve_manual_reward(
                    data.reward_id,
                    expected_version=data.expected_version,
                    confirm_issued=data.confirm_issued,
                    operator_reference=data.operator_reference,
                    resolved_by=data.resolved_by,
                    reason=data.reason,
                    allow_drift=data.allow_drift,
                    observed_subscription_id=evidence.observed_subscription_id,
                    observed_remote_uuid=evidence.observed_remote_uuid,
                    observed_expire_at=evidence.observed_expire_at,
                    source_status=source_status,
                    ack_admin_compensated_refund=data.ack_admin_compensated_refund,
                )
                if not resolved:
                    raise ValueError(
                        f"Referral reward '{data.reward_id}' has already been resolved "
                        "with different evidence or is not awaiting manual review"
                    )
                await self.uow.commit()
        decision = (
            "admin-refund-acknowledged"
            if data.ack_admin_compensated_refund
            else ("issued" if data.confirm_issued else "canceled")
        )
        logger.warning(
            f"{actor.log} Resolved manual referral reward '{data.reward_id}' as {decision}"
        )

    @staticmethod
    def _is_admin_compensated_refund_incident(reward: ReferralRewardDto) -> bool:
        return bool(
            reward.type == ReferralRewardType.EXTRA_DAYS
            and reward.state == ReferralRewardState.MANUAL_REQUIRED
            and reward.is_issued
            and reward.source_transaction_id is None
            and reward.origin_referral_id is None
            and reward.level is None
            and reward.target_subscription_id is None
            and reward.baseline_expire_at is None
            and reward.target_expire_at is None
            and reward.manual_cause == "SOURCE_REFUNDED_AFTER_REWARD_ISSUANCE"
            and reward.refund_detected_at is not None
        )

    @staticmethod
    def _is_unapplied_admin_earlier_payment_incident(reward: ReferralRewardDto) -> bool:
        """Recognize the exact never-applied row fenced by an ADMIN earlier source."""

        return bool(
            reward.type == ReferralRewardType.EXTRA_DAYS
            and reward.state == ReferralRewardState.MANUAL_REQUIRED
            and not reward.is_issued
            and reward.issued_at is None
            and reward.source_transaction_id is not None
            and reward.origin_referral_id is not None
            and reward.level is not None
            and reward.accrual_strategy_snapshot == ReferralAccrualStrategy.ON_FIRST_PAYMENT
            and reward.accrual_strategy is None
            and reward.reward_strategy is not None
            and reward.config_value is not None
            and reward.target_subscription_id is None
            and reward.baseline_expire_at is None
            and reward.target_expire_at is None
            and reward.processing_token_hash is None
            and reward.processing_lease_expires_at is None
            and reward.next_attempt_at is None
            and reward.manual_cause == "ADMIN_COMPENSATED_EARLIER_PAYMENT"
            and reward.last_error == "ADMIN_COMPENSATED_EARLIER_PAYMENT"
            and reward.refund_detected_at is None
        )

    async def _reconcile_extra_days(
        self,
        reward: ReferralRewardDto,
        confirm_issued: bool,
        allow_drift: bool,
    ) -> ManualReferralRewardEvidence:
        if (
            reward.target_subscription_id is None
            or reward.baseline_expire_at is None
            or reward.target_expire_at is None
        ):
            raise ValueError(
                "Legacy EXTRA_DAYS reward has no durable target and cannot be "
                "resolved through the generic API"
            )
        subscription = await self.subscription_dao.get_current(reward.user_id)
        observed = (
            await self.remnawave.get_user_by_uuid(subscription.user_remna_id)
            if subscription is not None
            else None
        )
        evidence = ManualReferralRewardEvidence(
            observed_subscription_id=(subscription.id if subscription is not None else None),
            observed_remote_uuid=(
                str(observed.uuid) if observed is not None and observed.uuid is not None else None
            ),
            observed_expire_at=(observed.expire_at if observed is not None else None),
        )
        expected_expire_at = (
            reward.target_expire_at if confirm_issued else reward.baseline_expire_at
        )
        remote_maps_to_current = bool(
            subscription is not None
            and observed is not None
            and str(observed.uuid) == str(subscription.user_remna_id)
        )
        target_is_current = bool(
            subscription is not None and subscription.id == reward.target_subscription_id
        )
        expiry_matches = bool(
            observed is not None
            and GiveReferrerReward._same_expiry(
                observed.expire_at,
                expected_expire_at,
            )
        )
        if (
            not (target_is_current and remote_maps_to_current and expiry_matches)
            and not allow_drift
        ):
            action = "confirm" if confirm_issued else "cancel"
            raise ValueError(
                f"Cannot {action} EXTRA_DAYS reward: Remnawave expiry does not "
                "match the durable target evidence; an audited drift override is required"
            )

        # Remote truth is verified under the mutation fence. Synchronize local state
        # in the same transaction as the append-only operator decision.
        # Both decisions require the exact durable expiry unless the operator supplies
        # an explicit audited drift override. A later renewal or promo is not causal
        # proof that this reward reached Remnawave.
        if (
            remote_maps_to_current
            and subscription is not None
            and observed is not None
            and isinstance(observed.expire_at, datetime)
        ):
            subscription.expire_at = observed.expire_at
            if await self.subscription_dao.update(subscription) is None:
                raise RuntimeError("Observed EXTRA_DAYS expiry was not persisted locally")
        return evidence


class RecoverLegacyReferralReward(Interactor[LegacyReferralRewardRecoveryDto, None]):
    """Record proven legacy evidence and transition the existing row only."""

    required_permission = None

    def __init__(
        self,
        uow: UnitOfWork,
        referral_dao: ReferralDao,
        recovery_authorizer: LegacyReferralRecoveryAuthorizer,
    ) -> None:
        self.uow = uow
        self.referral_dao = referral_dao
        self.recovery_authorizer = recovery_authorizer

    async def _execute(  # noqa: C901
        self,
        actor: UserDto,
        data: LegacyReferralRewardRecoveryDto,
    ) -> None:
        if data.reward_id <= 0 or data.expected_version < 0:
            raise ValueError("A positive reward id and non-negative version are required")
        if (
            data.source_transaction_id is None
            or data.source_transaction_id <= 0
            or data.origin_referral_id is None
            or data.origin_referral_id <= 0
            or data.level is None
        ):
            raise ValueError("Positive source transaction and origin referral ids are required")
        if isinstance(data.expected_reward_amount, bool) or data.expected_reward_amount <= 0:
            raise ValueError("A positive expected legacy reward amount is required")
        snapshot = (
            data.accrual_strategy_snapshot,
            data.reward_strategy,
            data.config_value,
        )
        expected_row = (
            data.expected_user_id,
            data.expected_referral_id,
            data.expected_created_at,
        )
        merge_audit_ids = data.expected_participant_merge_audit_ids
        if (
            not isinstance(merge_audit_ids, tuple)
            or any(
                isinstance(audit_id, bool)
                or not isinstance(audit_id, int)
                or audit_id <= 0
                for audit_id in merge_audit_ids
            )
            or merge_audit_ids != tuple(sorted(set(merge_audit_ids)))
        ):
            raise ValueError(
                "expected_participant_merge_audit_ids must be a positive, sorted, unique tuple"
            )
        if data.action == LegacyReferralRewardRecoveryAction.RETRY_PROVEN_MISSING:
            if any(value is None for value in snapshot):
                raise ValueError(
                    "RETRY_PROVEN_MISSING requires the exact historical policy snapshot"
                )
            if (
                data.config_value is None
                or isinstance(data.config_value, bool)
                or data.config_value <= 0
            ):
                raise ValueError("Historical reward config must be a positive integer")
            if (
                any(value is not None for value in expected_row)
                or data.source_validation is not None
                or merge_audit_ids
            ):
                raise ValueError("Source-backed recovery must not include operator row hints")
        elif data.action == LegacyReferralRewardRecoveryAction.CONFIRM_ADMIN_COMPENSATED:
            if (
                any(value is not None for value in (*snapshot, *expected_row))
                or data.source_validation is not None
                or merge_audit_ids
            ):
                raise ValueError(
                    "CONFIRM_ADMIN_COMPENSATED must not invent a historical policy snapshot"
                )
        elif data.action == LegacyReferralRewardRecoveryAction.RETRY_OPERATOR_DIRECTED:
            if any(value is not None for value in snapshot) or any(
                value is None for value in expected_row
            ) or data.source_validation not in (
                LegacyReferralRewardSourceValidation.LOCAL_COMPLETED,
                LegacyReferralRewardSourceValidation.PROVIDER_SUCCEEDED,
            ):
                raise ValueError(
                    "RETRY_OPERATOR_DIRECTED requires exact row hints and no policy snapshot"
                )
            if data.expected_created_at is None or data.expected_created_at.tzinfo is None:
                raise ValueError("Operator-directed expected_created_at must include a timezone")
        else:
            raise ValueError(
                f"Unsupported legacy recovery action '{data.action}'"
            )
        if (
            not data.operator_reference
            or data.operator_reference != data.operator_reference.strip()
            or len(data.operator_reference) > 256
            or not data.reason
            or data.reason != data.reason.strip()
            or len(data.reason) > 1024
        ):
            raise ValueError("Canonical operator reference and reason are required")
        if (
            len(data.evidence_sha256) != 64
            or data.evidence_sha256 != data.evidence_sha256.lower()
            or any(character not in "0123456789abcdef" for character in data.evidence_sha256)
        ):
            raise ValueError("evidence_sha256 must be a lowercase SHA-256 digest")
        manifest_digest = self.recovery_authorizer.authorize(data)
        authorized_data = replace(
            data,
            authorization_manifest_sha256=manifest_digest,
        )

        async with self.uow:
            transitioned = await self.referral_dao.recover_legacy_extra_days_reward(authorized_data)
            await self.uow.commit()
        logger.warning(
            f"{actor.log} Legacy referral reward '{data.reward_id}' recovery "
            f"'{data.action.value}' {'applied' if transitioned else 'replayed'} "
            f"({data.operator_reference})"
        )
