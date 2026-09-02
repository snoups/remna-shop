import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from loguru import logger

from src.application.common import Interactor
from src.application.common.dao import ReferralDao, SettingsDao, TransactionDao
from src.application.common.uow import UnitOfWork
from src.application.dto import ReferralDto, ReferralRewardDto, TransactionDto, UserDto
from src.application.use_cases.referral.queries.calculations import (
    CalculateReferralReward,
    CalculateReferralRewardDto,
)
from src.core.config import AppConfig
from src.core.enums import (
    ReferralAccrualStrategy,
    ReferralLevel,
    ReferralRewardState,
)

BackfillAction = Literal["INVENTORY", "PREVIEW", "APPLY"]
_INVENTORY_BLOCKING_ERRORS = frozenset(
    {
        "LEGACY_AMBIGUOUS_REWARD_REQUIRES_RESOLUTION",
        "PARTIAL_EXISTING_INTENTS_MANUAL_REVIEW",
        "SOURCE_FULFILLMENT_TIMESTAMP_MISSING",
        "DIRECT_REFERRAL_TIMESTAMP_MISSING",
        "DIRECT_REFERRAL_TIMESTAMP_INVALID",
        "DIRECT_REFERRAL_POSTDATES_PAYMENT",
        "SECOND_LEVEL_REFERRAL_TIMESTAMP_MISSING",
        "SECOND_LEVEL_REFERRAL_TIMESTAMP_INVALID",
        "SECOND_LEVEL_REFERRAL_POSTDATES_PAYMENT",
    }
)


class HistoricalReferralBackfillUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class HistoricalReferralRewardBackfillDto:
    action: BackfillAction
    limit: int = 100
    offset: int = 0
    source_transaction_ids: tuple[int, ...] = ()
    preview_id: int | None = None
    operator_identity: str = ""
    operator_reference: str = ""
    reason: str = ""
    expected_config_snapshot: dict[str, Any] | None = None


class ManageHistoricalReferralRewards(
    Interactor[HistoricalReferralRewardBackfillDto, dict[str, Any]]
):
    """Inventory and explicitly enqueue missing historical reward intents.

    Inventory is read-only. Preview persists immutable operator evidence and the
    exact current config/intent snapshot. Apply accepts only that same evidence,
    explicit transaction set and config, then recomputes under DB locks before
    inserting idempotent durable intents.
    """

    required_permission = None

    def __init__(
        self,
        uow: UnitOfWork,
        transaction_dao: TransactionDao,
        referral_dao: ReferralDao,
        settings_dao: SettingsDao,
        calculate_referral_reward: CalculateReferralReward,
        config: AppConfig,
    ) -> None:
        self.uow = uow
        self.transaction_dao = transaction_dao
        self.referral_dao = referral_dao
        self.settings_dao = settings_dao
        self.calculate_referral_reward = calculate_referral_reward
        self.config = config

    async def _execute(  # noqa: C901
        self,
        actor: UserDto,
        data: HistoricalReferralRewardBackfillDto,
    ) -> dict[str, Any]:
        if data.action == "INVENTORY":
            return await self._inventory(data)
        if not self.config.referral_reward_backfill_enabled:
            raise HistoricalReferralBackfillUnavailableError(
                "Historical referral reward backfill is disabled for this deployment"
            )
        self._validate_operator_evidence(data)
        if data.action == "PREVIEW":
            return await self._preview(data)
        if data.action == "APPLY":
            return await self._apply(actor, data)
        raise ValueError(f"Unsupported historical referral action '{data.action}'")

    async def _inventory(
        self,
        data: HistoricalReferralRewardBackfillDto,
    ) -> dict[str, Any]:
        settings = await self.settings_dao.get()
        transactions = await self.transaction_dao.list_historical_referral_reward_sources(
            limit=data.limit,
            offset=data.offset,
        )
        plan = await self._build_plan(
            transactions,
            settings=settings,
            lock_attribution=False,
            requested_ids=None,
        )
        candidates = [
            item
            for item in plan["transactions"]
            if item["intents"]
            or any(error in _INVENTORY_BLOCKING_ERRORS for error in item["errors"])
        ]
        return {
            "read_only": True,
            "limit": data.limit,
            "offset": data.offset,
            "config_snapshot": self._config_snapshot(settings),
            "candidates": candidates,
        }

    async def _preview(
        self,
        data: HistoricalReferralRewardBackfillDto,
    ) -> dict[str, Any]:
        transaction_ids = self._normalized_transaction_ids(data.source_transaction_ids)
        async with self.uow:
            # Bypass Redis and keep the authoritative policy row locked until
            # its exact preview/audit snapshot is committed.
            settings = await self.settings_dao.get_for_update()
            config_snapshot = self._config_snapshot(settings)
            transactions = await self.transaction_dao.get_historical_referral_reward_sources(
                transaction_ids,
                for_update=False,
            )
            preview_snapshot = await self._build_plan(
                transactions,
                settings=settings,
                lock_attribution=False,
                requested_ids=transaction_ids,
            )
            request_hash = self._request_hash(
                transaction_ids=transaction_ids,
                config_snapshot=config_snapshot,
                preview_snapshot=preview_snapshot,
                operator_identity=data.operator_identity,
                operator_reference=data.operator_reference,
                reason=data.reason,
            )
            audit = await self.referral_dao.create_or_get_backfill_preview(
                request_hash=request_hash,
                operator_identity=data.operator_identity,
                operator_reference=data.operator_reference,
                reason=data.reason,
                source_transaction_ids=transaction_ids,
                config_snapshot=config_snapshot,
                preview_snapshot=preview_snapshot,
            )
            await self.uow.commit()
        return {
            "preview_id": audit.id,
            "status": audit.status,
            "source_transaction_ids": audit.source_transaction_ids,
            "config_snapshot": audit.config_snapshot,
            **audit.preview_snapshot,
        }

    async def _apply(  # noqa: C901
        self,
        actor: UserDto,
        data: HistoricalReferralRewardBackfillDto,
    ) -> dict[str, Any]:
        if data.preview_id is None or data.preview_id <= 0:
            raise ValueError("A positive preview_id is required")
        transaction_ids = self._normalized_transaction_ids(data.source_transaction_ids)
        if data.expected_config_snapshot is None:
            raise ValueError("The exact preview config snapshot is required")

        async with self.uow:
            # Every APPLY uses one global order: advisory -> settings -> audit
            # -> source transactions -> attribution users/referrals.
            await self.referral_dao.acquire_historical_backfill_lock()
            settings = await self.settings_dao.get_for_update()
            audit = await self.referral_dao.get_backfill_preview_for_update(data.preview_id)
            if audit is None:
                raise ValueError(f"Historical referral preview '{data.preview_id}' was not found")
            self._validate_audit_evidence(audit, data, transaction_ids)
            if audit.status == "APPLIED":
                await self.uow.commit()
                return {
                    "preview_id": audit.id,
                    "status": "APPLIED",
                    "created_intents": len(audit.preview_snapshot.get("intents", [])),
                    "idempotent_replay": True,
                }

            current_config = self._config_snapshot(settings)
            if (
                current_config != audit.config_snapshot
                or current_config != data.expected_config_snapshot
            ):
                raise ValueError("Referral config changed after preview; create a new preview")

            transactions = await self.transaction_dao.get_historical_referral_reward_sources(
                transaction_ids,
                for_update=True,
            )
            locked_snapshot = await self._build_plan(
                transactions,
                settings=settings,
                lock_attribution=True,
                requested_ids=transaction_ids,
            )
            if locked_snapshot != audit.preview_snapshot:
                raise ValueError(
                    "Historical referral eligibility/attribution changed after preview"
                )
            if not locked_snapshot["can_apply"]:
                raise ValueError("Preview contains blocked or ineligible transactions")

            intents = locked_snapshot["intents"]
            for intent in intents:
                created = await self.referral_dao.create_reward(
                    reward=ReferralRewardDto(
                        user_id=intent["recipient_user_id"],
                        type=settings.referral.reward.type,
                        amount=intent["amount"],
                        is_issued=False,
                        source_transaction_id=intent["source_transaction_id"],
                        origin_referral_id=intent["origin_referral_id"],
                        level=ReferralLevel(intent["level"]),
                        accrual_strategy_snapshot=settings.referral.accrual_strategy,
                        accrual_strategy=(
                            settings.referral.accrual_strategy
                            if settings.referral.accrual_strategy
                            != ReferralAccrualStrategy.ON_FIRST_PAYMENT
                            else None
                        ),
                        reward_strategy=settings.referral.reward.strategy,
                        config_value=intent["config_value"],
                        state=ReferralRewardState.PENDING,
                    ),
                    referral_id=intent["reward_referral_id"],
                )
                if created is None:
                    raise ValueError("A concurrent first-payment winner appeared after preview")
            if not await self.referral_dao.mark_backfill_preview_applied(audit.id):
                raise RuntimeError("Historical referral preview lost its apply fence")
            await self.uow.commit()

        logger.warning(
            f"{actor.log} Applied historical referral preview '{data.preview_id}' "
            f"for transactions '{transaction_ids}' as operator "
            f"'{data.operator_identity}' ({data.operator_reference})"
        )
        return {
            "preview_id": data.preview_id,
            "status": "APPLIED",
            "created_intents": len(intents),
            "idempotent_replay": False,
        }

    async def _build_plan(  # noqa: C901
        self,
        transactions: list[TransactionDto],
        *,
        settings: Any,
        lock_attribution: bool,
        requested_ids: list[int] | None,
    ) -> dict[str, Any]:
        by_id = {transaction.id: transaction for transaction in transactions}
        transaction_ids = requested_ids if requested_ids is not None else sorted(by_id)
        items: list[dict[str, Any]] = []
        all_intents: list[dict[str, Any]] = []

        for transaction_id in transaction_ids:
            transaction = by_id.get(transaction_id)
            if transaction is None:
                items.append(
                    self._plan_item(
                        transaction_id=transaction_id,
                        user_id=None,
                        fulfilled_at=None,
                        intents=[],
                        errors=["SOURCE_NOT_ELIGIBLE_OR_NOT_FOUND"],
                    )
                )
                continue

            initial_referral, initial_parent = await self.referral_dao.get_referral_chain(
                transaction.user_id
            )
            if lock_attribution:
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
                    transaction.user_id,
                    referrer_ids,
                )
                referral, parent = await self.referral_dao.get_referral_chain(transaction.user_id)
                if self._chain_signature(referral, parent) != self._chain_signature(
                    initial_referral,
                    initial_parent,
                ):
                    raise ValueError("Referral attribution changed while applying preview")
            else:
                referral, parent = initial_referral, initial_parent

            errors: list[str] = []
            intents: list[dict[str, Any]] = []
            if referral is None:
                errors.append("NO_REFERRAL_ATTRIBUTION")
            elif transaction.fulfillment_completed_at is None:
                errors.append("SOURCE_FULFILLMENT_TIMESTAMP_MISSING")
            elif not settings.referral.enable:
                errors.append("REFERRAL_PROGRAM_DISABLED")
            else:
                reward_chain: dict[ReferralLevel, tuple[UserDto, int]] = {
                    ReferralLevel.FIRST: (referral.referrer, referral.id)
                }
                direct_time_error = self._attribution_time_error(
                    referral,
                    transaction.fulfillment_completed_at,
                    label="DIRECT",
                )
                if direct_time_error:
                    errors.append(direct_time_error)
                elif parent is not None and settings.referral.level >= ReferralLevel.SECOND:
                    parent_time_error = self._attribution_time_error(
                        parent,
                        transaction.fulfillment_completed_at,
                        label="SECOND_LEVEL",
                    )
                    if parent_time_error:
                        errors.append(parent_time_error)
                    else:
                        reward_chain[ReferralLevel.SECOND] = (parent.referrer, parent.id)

                referral_ids = [item[1] for item in reward_chain.values()]
                recipient_ids = [item[0].id for item in reward_chain.values()]
                if errors:
                    pass
                elif await self.referral_dao.has_legacy_ambiguous_reward(
                    referral_ids=referral_ids,
                    recipient_user_ids=recipient_ids,
                ):
                    errors.append("LEGACY_AMBIGUOUS_REWARD_REQUIRES_RESOLUTION")
                elif (
                    settings.referral.accrual_strategy == ReferralAccrualStrategy.ON_FIRST_PAYMENT
                    and await self.transaction_dao.get_first_successful_paid_transaction_id(
                        transaction.user_id
                    )
                    != transaction.id
                ):
                    errors.append("NOT_FIRST_SUCCESSFUL_PAID_TRANSACTION")
                else:
                    existing_rewards = await self.referral_dao.get_rewards_by_source_transaction(
                        transaction.id
                    )
                    existing_levels = {
                        reward.level for reward in existing_rewards if reward.level is not None
                    }
                    expected_levels = set(reward_chain)
                    if existing_rewards and expected_levels - existing_levels:
                        # Never compose a two-level reward chain from policy snapshots
                        # captured at different times. Operators must reconcile it.
                        errors.append("PARTIAL_EXISTING_INTENTS_MANUAL_REVIEW")
                    elif not existing_rewards:
                        for level, (recipient, reward_referral_id) in reward_chain.items():
                            config_value = settings.referral.reward.config.get(level)
                            if config_value is None:
                                errors.append(f"MISSING_CONFIG_LEVEL_{level.value}")
                                continue
                            amount = await self.calculate_referral_reward.system(
                                CalculateReferralRewardDto(
                                    settings=settings.referral,
                                    transaction=transaction,
                                    config_value=config_value,
                                )
                            )
                            if not amount or amount <= 0:
                                errors.append(f"NON_POSITIVE_REWARD_LEVEL_{level.value}")
                                continue
                            intents.append(
                                {
                                    "source_transaction_id": transaction.id,
                                    "payer_user_id": transaction.user_id,
                                    "recipient_user_id": recipient.id,
                                    "origin_referral_id": referral.id,
                                    "reward_referral_id": reward_referral_id,
                                    "level": level.value,
                                    "amount": amount,
                                    "config_value": config_value,
                                    "reward_type": settings.referral.reward.type.value,
                                    "reward_strategy": settings.referral.reward.strategy.value,
                                    "accrual_strategy": settings.referral.accrual_strategy.value,
                                }
                            )
                    if not intents and not errors:
                        errors.append("NO_MISSING_DURABLE_INTENTS")

            item = self._plan_item(
                transaction_id=transaction.id,
                user_id=transaction.user_id,
                fulfilled_at=(
                    transaction.fulfillment_completed_at.isoformat()
                    if transaction.fulfillment_completed_at
                    else None
                ),
                intents=intents,
                errors=errors,
            )
            items.append(item)
            all_intents.extend(intents)

        return {
            "can_apply": bool(items)
            and bool(all_intents)
            and all(not item["errors"] for item in items),
            "transactions": items,
            "intents": all_intents,
        }

    @staticmethod
    def _plan_item(
        *,
        transaction_id: int,
        user_id: int | None,
        fulfilled_at: str | None,
        intents: list[dict[str, Any]],
        errors: list[str],
    ) -> dict[str, Any]:
        return {
            "source_transaction_id": transaction_id,
            "payer_user_id": user_id,
            "fulfillment_completed_at": fulfilled_at,
            "intents": intents,
            "errors": errors,
        }

    @staticmethod
    def _config_snapshot(settings: Any) -> dict[str, Any]:
        return {
            "enabled": settings.referral.enable,
            "max_level": settings.referral.level.value,
            "accrual_strategy": settings.referral.accrual_strategy.value,
            "reward_type": settings.referral.reward.type.value,
            "reward_strategy": settings.referral.reward.strategy.value,
            "reward_config": {
                str(level.value): value
                for level, value in sorted(
                    settings.referral.reward.config.items(),
                    key=lambda item: item[0].value,
                )
                if level <= settings.referral.level
            },
        }

    @staticmethod
    def _normalized_transaction_ids(source_ids: tuple[int, ...]) -> list[int]:
        ids = sorted(set(source_ids))
        if not ids or any(transaction_id <= 0 for transaction_id in ids):
            raise ValueError("Explicit positive source_transaction_ids are required")
        if len(ids) > 100:
            raise ValueError("At most 100 source transactions can be backfilled at once")
        return ids

    @staticmethod
    def _validate_operator_evidence(data: HistoricalReferralRewardBackfillDto) -> None:
        if not (
            data.operator_identity.strip()
            and data.operator_reference.strip()
            and data.reason.strip()
        ):
            raise ValueError("Operator identity, reference, and reason are required")

    @staticmethod
    def _validate_audit_evidence(
        audit: Any,
        data: HistoricalReferralRewardBackfillDto,
        transaction_ids: list[int],
    ) -> None:
        if (
            audit.operator_identity != data.operator_identity
            or audit.operator_reference != data.operator_reference
            or audit.reason != data.reason
            or audit.source_transaction_ids != transaction_ids
            or audit.config_snapshot != data.expected_config_snapshot
        ):
            raise ValueError("Apply evidence does not match the persisted preview")

    @staticmethod
    def _request_hash(
        *,
        transaction_ids: list[int],
        config_snapshot: dict[str, Any],
        preview_snapshot: dict[str, Any],
        operator_identity: str,
        operator_reference: str,
        reason: str,
    ) -> str:
        payload = json.dumps(
            {
                "source_transaction_ids": transaction_ids,
                "config_snapshot": config_snapshot,
                "preview_snapshot": preview_snapshot,
                "operator_identity": operator_identity,
                "operator_reference": operator_reference,
                "reason": reason,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    @staticmethod
    def _chain_signature(
        referral: ReferralDto | None,
        parent: ReferralDto | None,
    ) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
        def signature(item: ReferralDto | None) -> tuple[int, int] | None:
            return (item.id, item.referrer.id) if item is not None else None

        return signature(referral), signature(parent)

    @staticmethod
    def _attribution_time_error(
        referral: ReferralDto,
        fulfilled_at: datetime,
        *,
        label: str,
    ) -> str | None:
        if referral.created_at is None:
            return f"{label}_REFERRAL_TIMESTAMP_MISSING"
        try:
            if referral.created_at > fulfilled_at:
                return f"{label}_REFERRAL_POSTDATES_PAYMENT"
        except TypeError:
            return f"{label}_REFERRAL_TIMESTAMP_INVALID"
        return None
