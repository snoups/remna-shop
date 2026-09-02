from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.application.dto import ReferralRewardBackfillAuditDto
from src.application.use_cases.referral.commands.backfill import (
    HistoricalReferralBackfillUnavailableError,
    HistoricalReferralRewardBackfillDto,
    ManageHistoricalReferralRewards,
)
from src.core.config import AppConfig
from src.core.enums import (
    ReferralAccrualStrategy,
    ReferralLevel,
    ReferralRewardStrategy,
    ReferralRewardType,
    TransactionFulfillmentStatus,
    TransactionStatus,
)


class _UnitOfWork:
    def __init__(self) -> None:
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def __aenter__(self) -> "_UnitOfWork":
        return self

    async def __aexit__(self, *args: object) -> None:
        if args[0] is not None:
            await self.rollback()


def _source() -> SimpleNamespace:
    return SimpleNamespace(
        id=77,
        user_id=9,
        is_test=False,
        status=TransactionStatus.COMPLETED,
        fulfillment_status=TransactionFulfillmentStatus.SUCCEEDED,
        fulfillment_completed_at=datetime(2025, 1, 10, tzinfo=timezone.utc),
        pricing=SimpleNamespace(is_free=False),
        plan_snapshot=SimpleNamespace(is_trial=False),
    )


def _settings(*, level: ReferralLevel = ReferralLevel.SECOND) -> SimpleNamespace:
    return SimpleNamespace(
        referral=SimpleNamespace(
            enable=True,
            level=level,
            accrual_strategy=ReferralAccrualStrategy.ON_FIRST_PAYMENT,
            reward=SimpleNamespace(
                type=ReferralRewardType.POINTS,
                strategy=ReferralRewardStrategy.AMOUNT,
                config={ReferralLevel.FIRST: 10, ReferralLevel.SECOND: 5},
            ),
        )
    )


def _dependencies(
    *,
    legacy_ambiguous: bool = False,
    level: ReferralLevel = ReferralLevel.FIRST,
    existing_rewards: list[object] | None = None,
    direct_created_at: datetime | None = datetime(2025, 1, 1, tzinfo=timezone.utc),
    parent_created_at: datetime | None = datetime(2025, 1, 1, tzinfo=timezone.utc),
    backfill_enabled: bool = True,
) -> tuple[object, ...]:
    transaction = _source()
    referral = SimpleNamespace(
        id=101,
        referrer=SimpleNamespace(id=2, remna_name="direct"),
        created_at=direct_created_at,
    )
    parent = SimpleNamespace(
        id=202,
        referrer=SimpleNamespace(id=3, remna_name="grandparent"),
        created_at=parent_created_at,
    )
    transaction_dao = SimpleNamespace(
        list_historical_referral_reward_sources=AsyncMock(return_value=[transaction]),
        get_historical_referral_reward_sources=AsyncMock(return_value=[transaction]),
        get_first_successful_paid_transaction_id=AsyncMock(return_value=transaction.id),
    )
    referral_dao = SimpleNamespace(
        get_referral_chain=AsyncMock(
            return_value=(referral, parent if level == ReferralLevel.SECOND else None)
        ),
        get_rewards_by_source_transaction=AsyncMock(return_value=existing_rewards or []),
        has_legacy_ambiguous_reward=AsyncMock(return_value=legacy_ambiguous),
        lock_referral_attribution=AsyncMock(),
        acquire_historical_backfill_lock=AsyncMock(),
        create_or_get_backfill_preview=AsyncMock(),
        get_backfill_preview_for_update=AsyncMock(),
        create_reward=AsyncMock(return_value=SimpleNamespace(id=501)),
        mark_backfill_preview_applied=AsyncMock(return_value=True),
    )
    settings = _settings(level=level)
    settings_dao = SimpleNamespace(
        get=AsyncMock(return_value=settings),
        get_for_update=AsyncMock(return_value=settings),
    )
    calculate = SimpleNamespace(system=AsyncMock(return_value=10))
    uow = _UnitOfWork()
    use_case = ManageHistoricalReferralRewards(
        uow,  # type: ignore[arg-type]
        transaction_dao,
        referral_dao,
        settings_dao,
        calculate,
        SimpleNamespace(referral_reward_backfill_enabled=backfill_enabled),
    )
    return use_case, uow, transaction_dao, referral_dao, settings_dao


@pytest.mark.asyncio
async def test_historical_inventory_is_read_only_and_finds_first_paid_after_trial() -> None:
    use_case, uow, transaction_dao, referral_dao, _ = _dependencies()

    result = await use_case._execute(  # type: ignore[attr-defined]
        SimpleNamespace(log="system"),
        HistoricalReferralRewardBackfillDto(action="INVENTORY"),
    )

    assert result["read_only"] is True
    assert result["candidates"][0]["source_transaction_id"] == 77
    assert result["candidates"][0]["intents"][0]["recipient_user_id"] == 2
    transaction_dao.get_first_successful_paid_transaction_id.assert_awaited_once_with(9)
    referral_dao.create_or_get_backfill_preview.assert_not_awaited()
    uow.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_preview_then_apply_is_audited_atomic_and_idempotent() -> None:
    use_case, _, _, referral_dao, settings_dao = _dependencies()
    stored: ReferralRewardBackfillAuditDto | None = None

    async def persist_preview(**kwargs: object) -> ReferralRewardBackfillAuditDto:
        nonlocal stored
        stored = ReferralRewardBackfillAuditDto(
            id=31,
            request_hash=str(kwargs["request_hash"]),
            status="PREVIEWED",
            operator_identity=str(kwargs["operator_identity"]),
            operator_reference=str(kwargs["operator_reference"]),
            reason=str(kwargs["reason"]),
            source_transaction_ids=list(kwargs["source_transaction_ids"]),  # type: ignore[arg-type]
            config_snapshot=dict(kwargs["config_snapshot"]),  # type: ignore[arg-type]
            preview_snapshot=dict(kwargs["preview_snapshot"]),  # type: ignore[arg-type]
        )
        return stored

    referral_dao.create_or_get_backfill_preview.side_effect = persist_preview
    evidence = {
        "operator_identity": "alice",
        "operator_reference": "TICKET-135",
        "reason": "Verified historical first paid purchase after trial",
    }
    preview = await use_case._execute(  # type: ignore[attr-defined]
        SimpleNamespace(log="system"),
        HistoricalReferralRewardBackfillDto(
            action="PREVIEW",
            source_transaction_ids=(77,),
            **evidence,
        ),
    )
    assert preview["can_apply"] is True
    assert stored is not None
    settings_dao.get_for_update.assert_awaited_once()
    settings_dao.get.assert_not_awaited()

    lock_order: list[str] = []

    async def acquire_backfill_lock() -> None:
        lock_order.append("advisory")

    async def get_locked_settings() -> object:
        lock_order.append("settings")
        return settings_dao.get_for_update.return_value

    referral_dao.acquire_historical_backfill_lock.side_effect = acquire_backfill_lock
    settings_dao.get_for_update.side_effect = get_locked_settings
    referral_dao.get_backfill_preview_for_update.return_value = stored
    applied = await use_case._execute(  # type: ignore[attr-defined]
        SimpleNamespace(log="system"),
        HistoricalReferralRewardBackfillDto(
            action="APPLY",
            preview_id=31,
            source_transaction_ids=(77,),
            expected_config_snapshot=preview["config_snapshot"],
            **evidence,
        ),
    )

    assert applied == {
        "preview_id": 31,
        "status": "APPLIED",
        "created_intents": 1,
        "idempotent_replay": False,
    }
    assert lock_order[:2] == ["advisory", "settings"]
    referral_dao.acquire_historical_backfill_lock.assert_awaited_once()
    referral_dao.create_reward.assert_awaited_once()
    referral_dao.mark_backfill_preview_applied.assert_awaited_once_with(31)

    referral_dao.get_backfill_preview_for_update.return_value = ReferralRewardBackfillAuditDto(
        **{**stored.__dict__, "status": "APPLIED"}
    )
    replay = await use_case._execute(  # type: ignore[attr-defined]
        SimpleNamespace(log="system"),
        HistoricalReferralRewardBackfillDto(
            action="APPLY",
            preview_id=31,
            source_transaction_ids=(77,),
            expected_config_snapshot=preview["config_snapshot"],
            **evidence,
        ),
    )
    assert replay["idempotent_replay"] is True
    referral_dao.create_reward.assert_awaited_once()
    assert settings_dao.get_for_update.await_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("level", "create_results"),
    (
        (ReferralLevel.FIRST, [None]),
        (ReferralLevel.SECOND, [SimpleNamespace(id=501), None]),
    ),
)
async def test_backfill_apply_rolls_back_if_recovery_consumed_source_after_preview(
    level: ReferralLevel,
    create_results: list[object | None],
) -> None:
    use_case, uow, _, referral_dao, _ = _dependencies(level=level)
    stored: ReferralRewardBackfillAuditDto | None = None

    async def persist_preview(**kwargs: object) -> ReferralRewardBackfillAuditDto:
        nonlocal stored
        stored = ReferralRewardBackfillAuditDto(
            id=32,
            request_hash=str(kwargs["request_hash"]),
            status="PREVIEWED",
            operator_identity=str(kwargs["operator_identity"]),
            operator_reference=str(kwargs["operator_reference"]),
            reason=str(kwargs["reason"]),
            source_transaction_ids=list(kwargs["source_transaction_ids"]),  # type: ignore[arg-type]
            config_snapshot=dict(kwargs["config_snapshot"]),  # type: ignore[arg-type]
            preview_snapshot=dict(kwargs["preview_snapshot"]),  # type: ignore[arg-type]
        )
        return stored

    referral_dao.create_or_get_backfill_preview.side_effect = persist_preview
    evidence = {
        "operator_identity": "alice",
        "operator_reference": "TICKET-135",
        "reason": "Verified source before apply",
    }
    preview = await use_case._execute(  # type: ignore[attr-defined]
        SimpleNamespace(log="system"),
        HistoricalReferralRewardBackfillDto(
            action="PREVIEW",
            source_transaction_ids=(77,),
            **evidence,
        ),
    )
    assert stored is not None
    referral_dao.get_backfill_preview_for_update.return_value = stored
    referral_dao.create_reward.side_effect = create_results

    with pytest.raises(ValueError, match="concurrent first-payment winner"):
        await use_case._execute(  # type: ignore[attr-defined]
            SimpleNamespace(log="system"),
            HistoricalReferralRewardBackfillDto(
                action="APPLY",
                preview_id=32,
                source_transaction_ids=(77,),
                expected_config_snapshot=preview["config_snapshot"],
                **evidence,
            ),
        )

    assert referral_dao.create_reward.await_count == len(create_results)
    referral_dao.mark_backfill_preview_applied.assert_not_awaited()
    uow.rollback.assert_awaited_once()
    assert uow.commit.await_count == 1  # the frozen PREVIEW only


@pytest.mark.asyncio
async def test_backfill_mutations_are_disabled_by_default_rollout_gate() -> None:
    assert AppConfig.model_fields["referral_reward_backfill_enabled"].default is False
    use_case, _, _, referral_dao, _ = _dependencies(backfill_enabled=False)

    inventory = await use_case._execute(  # type: ignore[attr-defined]
        SimpleNamespace(log="system"),
        HistoricalReferralRewardBackfillDto(action="INVENTORY"),
    )
    assert inventory["read_only"] is True

    with pytest.raises(HistoricalReferralBackfillUnavailableError, match="disabled"):
        await use_case._execute(  # type: ignore[attr-defined]
            SimpleNamespace(log="system"),
            HistoricalReferralRewardBackfillDto(
                action="PREVIEW",
                source_transaction_ids=(77,),
                operator_identity="alice",
                operator_reference="TICKET-ROLLOUT",
                reason="Deployment is not fully upgraded",
            ),
        )
    with pytest.raises(HistoricalReferralBackfillUnavailableError, match="disabled"):
        await use_case._execute(  # type: ignore[attr-defined]
            SimpleNamespace(log="system"),
            HistoricalReferralRewardBackfillDto(
                action="APPLY",
                preview_id=31,
                source_transaction_ids=(77,),
                operator_identity="alice",
                operator_reference="TICKET-ROLLOUT",
                reason="Deployment is not fully upgraded",
                expected_config_snapshot={},
            ),
        )
    referral_dao.create_or_get_backfill_preview.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("level", "direct_created_at", "parent_created_at", "expected_error"),
    [
        (
            ReferralLevel.FIRST,
            datetime(2025, 1, 11, tzinfo=timezone.utc),
            datetime(2025, 1, 1, tzinfo=timezone.utc),
            "DIRECT_REFERRAL_POSTDATES_PAYMENT",
        ),
        (
            ReferralLevel.SECOND,
            datetime(2025, 1, 1, tzinfo=timezone.utc),
            datetime(2025, 1, 11, tzinfo=timezone.utc),
            "SECOND_LEVEL_REFERRAL_POSTDATES_PAYMENT",
        ),
    ],
)
async def test_preview_rejects_attribution_created_after_payment(
    level: ReferralLevel,
    direct_created_at: datetime,
    parent_created_at: datetime,
    expected_error: str,
) -> None:
    use_case, _, _, referral_dao, _ = _dependencies(
        level=level,
        direct_created_at=direct_created_at,
        parent_created_at=parent_created_at,
    )

    async def persist_preview(**kwargs: object) -> ReferralRewardBackfillAuditDto:
        return ReferralRewardBackfillAuditDto(
            id=40,
            request_hash=str(kwargs["request_hash"]),
            status="PREVIEWED",
            operator_identity=str(kwargs["operator_identity"]),
            operator_reference=str(kwargs["operator_reference"]),
            reason=str(kwargs["reason"]),
            source_transaction_ids=list(kwargs["source_transaction_ids"]),  # type: ignore[arg-type]
            config_snapshot=dict(kwargs["config_snapshot"]),  # type: ignore[arg-type]
            preview_snapshot=dict(kwargs["preview_snapshot"]),  # type: ignore[arg-type]
        )

    referral_dao.create_or_get_backfill_preview.side_effect = persist_preview
    preview = await use_case._execute(  # type: ignore[attr-defined]
        SimpleNamespace(log="system"),
        HistoricalReferralRewardBackfillDto(
            action="PREVIEW",
            source_transaction_ids=(77,),
            operator_identity="alice",
            operator_reference="TICKET-TIMEBOUND",
            reason="Verify attribution existed when payment fulfilled",
        ),
    )

    assert preview["can_apply"] is False
    assert preview["intents"] == []
    assert preview["transactions"][0]["errors"] == [expected_error]


@pytest.mark.asyncio
async def test_backfill_rejects_partial_existing_l1_l2_chain() -> None:
    use_case, _, _, referral_dao, _ = _dependencies(
        level=ReferralLevel.SECOND,
        existing_rewards=[SimpleNamespace(level=ReferralLevel.FIRST)],
    )

    async def persist_preview(**kwargs: object) -> ReferralRewardBackfillAuditDto:
        return ReferralRewardBackfillAuditDto(
            id=35,
            request_hash=str(kwargs["request_hash"]),
            status="PREVIEWED",
            operator_identity=str(kwargs["operator_identity"]),
            operator_reference=str(kwargs["operator_reference"]),
            reason=str(kwargs["reason"]),
            source_transaction_ids=list(kwargs["source_transaction_ids"]),  # type: ignore[arg-type]
            config_snapshot=dict(kwargs["config_snapshot"]),  # type: ignore[arg-type]
            preview_snapshot=dict(kwargs["preview_snapshot"]),  # type: ignore[arg-type]
        )

    referral_dao.create_or_get_backfill_preview.side_effect = persist_preview
    preview = await use_case._execute(  # type: ignore[attr-defined]
        SimpleNamespace(log="system"),
        HistoricalReferralRewardBackfillDto(
            action="PREVIEW",
            source_transaction_ids=(77,),
            operator_identity="alice",
            operator_reference="TICKET-PARTIAL",
            reason="Existing L1 policy snapshot cannot be mixed with current L2 policy",
        ),
    )

    assert preview["can_apply"] is False
    assert preview["intents"] == []
    assert preview["transactions"][0]["errors"] == ["PARTIAL_EXISTING_INTENTS_MANUAL_REVIEW"]
    referral_dao.create_reward.assert_not_awaited()


@pytest.mark.asyncio
async def test_apply_rejects_config_or_eligibility_drift_from_persisted_preview() -> None:
    use_case, _, _, referral_dao, settings_dao = _dependencies()
    evidence = {
        "operator_identity": "alice",
        "operator_reference": "TICKET-DRIFT",
        "reason": "Verified source before apply",
    }
    preview_snapshot = {
        "can_apply": True,
        "transactions": [],
        "intents": [],
    }
    config_snapshot = use_case._config_snapshot(  # type: ignore[attr-defined]
        settings_dao.get_for_update.return_value
    )
    stored = ReferralRewardBackfillAuditDto(
        id=33,
        request_hash="h" * 64,
        status="PREVIEWED",
        source_transaction_ids=[77],
        config_snapshot=config_snapshot,
        preview_snapshot=preview_snapshot,
        **evidence,
    )
    referral_dao.get_backfill_preview_for_update.return_value = stored

    with pytest.raises(ValueError, match="evidence does not match"):
        await use_case._execute(  # type: ignore[attr-defined]
            SimpleNamespace(log="system"),
            HistoricalReferralRewardBackfillDto(
                action="APPLY",
                preview_id=33,
                source_transaction_ids=(77,),
                expected_config_snapshot=config_snapshot | {"max_level": 2},
                **evidence,
            ),
        )

    changed_settings = _settings(level=ReferralLevel.SECOND)
    settings_dao.get_for_update.return_value = changed_settings
    with pytest.raises(ValueError, match="config changed"):
        await use_case._execute(  # type: ignore[attr-defined]
            SimpleNamespace(log="system"),
            HistoricalReferralRewardBackfillDto(
                action="APPLY",
                preview_id=33,
                source_transaction_ids=(77,),
                expected_config_snapshot=config_snapshot,
                **evidence,
            ),
        )

    referral_dao.create_reward.assert_not_awaited()


def test_backfill_preview_hash_includes_exact_computed_snapshot() -> None:
    common = {
        "transaction_ids": [77],
        "config_snapshot": {"enabled": True},
        "operator_identity": "alice",
        "operator_reference": "TICKET-135",
        "reason": "Verified source",
    }

    first = ManageHistoricalReferralRewards._request_hash(
        preview_snapshot={"intents": [{"amount": 10}]},
        **common,
    )
    second = ManageHistoricalReferralRewards._request_hash(
        preview_snapshot={"intents": [{"amount": 20}]},
        **common,
    )

    assert first != second


@pytest.mark.asyncio
async def test_apply_rejects_eligibility_drift_after_preview() -> None:
    use_case, _, _, referral_dao, _ = _dependencies()
    stored: ReferralRewardBackfillAuditDto | None = None

    async def persist_preview(**kwargs: object) -> ReferralRewardBackfillAuditDto:
        nonlocal stored
        stored = ReferralRewardBackfillAuditDto(
            id=34,
            request_hash=str(kwargs["request_hash"]),
            status="PREVIEWED",
            operator_identity=str(kwargs["operator_identity"]),
            operator_reference=str(kwargs["operator_reference"]),
            reason=str(kwargs["reason"]),
            source_transaction_ids=list(kwargs["source_transaction_ids"]),  # type: ignore[arg-type]
            config_snapshot=dict(kwargs["config_snapshot"]),  # type: ignore[arg-type]
            preview_snapshot=dict(kwargs["preview_snapshot"]),  # type: ignore[arg-type]
        )
        return stored

    referral_dao.create_or_get_backfill_preview.side_effect = persist_preview
    evidence = {
        "operator_identity": "alice",
        "operator_reference": "TICKET-DRIFT-2",
        "reason": "Verified before a concurrent normal intent appeared",
    }
    preview = await use_case._execute(  # type: ignore[attr-defined]
        SimpleNamespace(log="system"),
        HistoricalReferralRewardBackfillDto(
            action="PREVIEW",
            source_transaction_ids=(77,),
            **evidence,
        ),
    )
    assert stored is not None
    referral_dao.get_backfill_preview_for_update.return_value = stored
    referral_dao.get_rewards_by_source_transaction.return_value = [
        SimpleNamespace(level=ReferralLevel.FIRST)
    ]

    with pytest.raises(ValueError, match="eligibility/attribution changed"):
        await use_case._execute(  # type: ignore[attr-defined]
            SimpleNamespace(log="system"),
            HistoricalReferralRewardBackfillDto(
                action="APPLY",
                preview_id=34,
                source_transaction_ids=(77,),
                expected_config_snapshot=preview["config_snapshot"],
                **evidence,
            ),
        )

    referral_dao.create_reward.assert_not_awaited()


@pytest.mark.asyncio
async def test_any_legacy_ambiguous_reward_is_previewed_but_never_applied() -> None:
    use_case, _, _, referral_dao, _ = _dependencies(legacy_ambiguous=True)
    captured: dict[str, object] = {}
    stored: ReferralRewardBackfillAuditDto | None = None

    async def persist_preview(**kwargs: object) -> ReferralRewardBackfillAuditDto:
        nonlocal stored
        captured.update(kwargs)
        stored = ReferralRewardBackfillAuditDto(
            id=32,
            request_hash=str(kwargs["request_hash"]),
            status="PREVIEWED",
            operator_identity=str(kwargs["operator_identity"]),
            operator_reference=str(kwargs["operator_reference"]),
            reason=str(kwargs["reason"]),
            source_transaction_ids=[77],
            config_snapshot=dict(kwargs["config_snapshot"]),  # type: ignore[arg-type]
            preview_snapshot=dict(kwargs["preview_snapshot"]),  # type: ignore[arg-type]
        )
        return stored

    referral_dao.create_or_get_backfill_preview.side_effect = persist_preview
    preview = await use_case._execute(  # type: ignore[attr-defined]
        SimpleNamespace(log="system"),
        HistoricalReferralRewardBackfillDto(
            action="PREVIEW",
            source_transaction_ids=(77,),
            operator_identity="alice",
            operator_reference="TICKET-LEGACY",
            reason="Inventory only; ambiguous legacy row requires reconciliation",
        ),
    )

    assert preview["can_apply"] is False
    assert preview["transactions"][0]["errors"] == ["LEGACY_AMBIGUOUS_REWARD_REQUIRES_RESOLUTION"]
    assert captured["preview_snapshot"] == {
        "can_apply": False,
        "transactions": preview["transactions"],
        "intents": [],
    }

    assert stored is not None
    referral_dao.get_backfill_preview_for_update.return_value = stored
    with pytest.raises(ValueError, match="blocked or ineligible"):
        await use_case._execute(  # type: ignore[attr-defined]
            SimpleNamespace(log="system"),
            HistoricalReferralRewardBackfillDto(
                action="APPLY",
                preview_id=32,
                source_transaction_ids=(77,),
                operator_identity="alice",
                operator_reference="TICKET-LEGACY",
                reason="Inventory only; ambiguous legacy row requires reconciliation",
                expected_config_snapshot=preview["config_snapshot"],
            ),
        )
    referral_dao.create_reward.assert_not_awaited()
