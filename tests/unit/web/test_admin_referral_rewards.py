from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import BaseModel, ValidationError

from src.application.dto import ReferralRewardDto
from src.application.use_cases.referral.commands.backfill import (
    HistoricalReferralBackfillUnavailableError,
)
from src.core.enums import ReferralRewardState, ReferralRewardType
from src.web.endpoints.admin.referral_rewards import (
    apply_historical_referral_rewards,
    inventory_historical_referral_rewards,
    list_manual_referral_rewards,
    preview_historical_referral_rewards,
    recover_legacy_referral_reward,
    recover_legacy_referral_rewards_batch,
    resolve_manual_referral_reward,
)
from src.web.endpoints.admin.referral_rewards import (
    router as referral_rewards_router,
)
from src.web.schemas import (
    HistoricalReferralBackfillApplyRequest,
    HistoricalReferralBackfillPreviewRequest,
    LegacyReferralRewardRecoveryBatchRequest,
    LegacyReferralRewardRecoveryRequest,
    ResolveManualReferralRewardRequest,
)

resolve_manual_referral_reward_impl = (  # type: ignore[attr-defined]
    resolve_manual_referral_reward.__dishka_orig_func__
)
inventory_historical_referral_rewards_impl = (  # type: ignore[attr-defined]
    inventory_historical_referral_rewards.__dishka_orig_func__
)
preview_historical_referral_rewards_impl = (  # type: ignore[attr-defined]
    preview_historical_referral_rewards.__dishka_orig_func__
)
apply_historical_referral_rewards_impl = (  # type: ignore[attr-defined]
    apply_historical_referral_rewards.__dishka_orig_func__
)
list_manual_referral_rewards_impl = (  # type: ignore[attr-defined]
    list_manual_referral_rewards.__dishka_orig_func__
)
recover_legacy_referral_reward_impl = (  # type: ignore[attr-defined]
    recover_legacy_referral_reward.__dishka_orig_func__
)
recover_legacy_referral_rewards_batch_impl = (  # type: ignore[attr-defined]
    recover_legacy_referral_rewards_batch.__dishka_orig_func__
)


def _backfill_request_payload() -> dict[str, object]:
    return {
        "source_transaction_ids": [77, 91],
        "operator_identity": "alice",
        "operator_reference": "TICKET-135",
        "reason": "Verified missing durable intents against payment records",
    }


def _legacy_recovery_payload(action: str = "RETRY_PROVEN_MISSING") -> dict[str, object]:
    payload: dict[str, object] = {
        "action": action,
        "expected_version": 1,
        "source_transaction_id": 77,
        "origin_referral_id": 101,
        "level": 1,
        "expected_reward_amount": 3,
        "operator_reference": "OWNER/TICKET-123",
        "reason": "Exact transaction and panel evidence prove the legacy outcome",
        "evidence_sha256": "a" * 64,
    }
    if action == "RETRY_PROVEN_MISSING":
        payload.update(
            accrual_strategy_snapshot="ON_FIRST_PAYMENT",
            reward_strategy="AMOUNT",
            config_value=3,
        )
    return payload


def _operator_recovery_payload(reward_id: int = 1342) -> dict[str, object]:
    return {
        "reward_id": reward_id,
        "action": "RETRY_OPERATOR_DIRECTED",
        "expected_version": 1,
        "source_transaction_id": 8123 + reward_id,
        "origin_referral_id": 1500,
        "level": 1,
        "source_validation": "LOCAL_COMPLETED",
        "expected_reward_amount": 14,
        "expected_user_id": 222,
        "expected_referral_id": 1500,
        "expected_created_at": datetime(2026, 7, 20, tzinfo=timezone.utc),
        "expected_participant_merge_audit_ids": [3, 17],
        "operator_reference": "OWNER/INCIDENT-2026-08-22-FULL-AUDIT",
        "reason": "FIFO timeline audit found no ADMIN day allocation",
        "evidence_sha256": "e" * 64,
    }


def _backfill_config_snapshot() -> dict[str, object]:
    return {
        "enabled": True,
        "max_level": 2,
        "accrual_strategy": "ON_FIRST_PAYMENT",
        "reward_type": "POINTS",
        "reward_strategy": "AMOUNT",
        "reward_config": {"1": 10, "2": 5},
    }


def test_manual_resolution_requires_operator_reference_and_reason() -> None:
    with pytest.raises(ValidationError):
        ResolveManualReferralRewardRequest(
            resolution="CONFIRM_ISSUED",
            operator_reference=" ",
            reason=" ",
        )


def test_admin_compensation_refund_ack_rejects_drift_override() -> None:
    with pytest.raises(ValidationError, match="Refund acknowledgment"):
        ResolveManualReferralRewardRequest(
            resolution="ACK_ADMIN_COMPENSATED_REFUND",
            expected_version=2,
            operator_reference="INC-REF-20260822/REFUND-RR-398",
            reason="Acknowledged later refund",
            allow_drift=True,
        )


@pytest.mark.asyncio
async def test_admin_compensation_refund_ack_dispatches_distinct_action() -> None:
    resolver = SimpleNamespace(system=AsyncMock())
    body = ResolveManualReferralRewardRequest(
        resolution="ACK_ADMIN_COMPENSATED_REFUND",
        expected_version=2,
        operator_reference="INC-REF-20260822/REFUND-RR-398",
        reason="Acknowledged later refund",
    )

    await resolve_manual_referral_reward_impl(398, body, resolver, None)

    request = resolver.system.await_args.args[0]
    assert request.reward_id == 398
    assert request.confirm_issued is False
    assert request.ack_admin_compensated_refund is True
    assert request.allow_drift is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action",
    ["RETRY_PROVEN_MISSING", "CONFIRM_ADMIN_COMPENSATED"],
)
async def test_legacy_recovery_endpoint_dispatches_exact_evidence(action: str) -> None:
    recovery = SimpleNamespace(system=AsyncMock())
    body = LegacyReferralRewardRecoveryRequest.model_validate(_legacy_recovery_payload(action))

    await recover_legacy_referral_reward_impl(8, body, recovery, None)

    request = recovery.system.await_args.args[0]
    assert request.reward_id == 8
    assert request.action.value == action
    assert request.source_transaction_id == 77
    assert request.origin_referral_id == 101
    assert request.level.value == 1
    assert request.evidence_sha256 == "a" * 64
    if action == "RETRY_PROVEN_MISSING":
        assert request.accrual_strategy_snapshot.value == "ON_FIRST_PAYMENT"
        assert request.reward_strategy.value == "AMOUNT"
        assert request.config_value == 3
    else:
        assert request.accrual_strategy_snapshot is None
        assert request.reward_strategy is None
        assert request.config_value is None


@pytest.mark.asyncio
async def test_operator_recovery_endpoint_dispatches_source_and_exact_row_hints() -> None:
    recovery = SimpleNamespace(system=AsyncMock())
    payload = _operator_recovery_payload()
    reward_id = int(payload.pop("reward_id"))
    body = LegacyReferralRewardRecoveryRequest.model_validate(payload)

    await recover_legacy_referral_reward_impl(reward_id, body, recovery, None)

    request = recovery.system.await_args.args[0]
    assert request.action.value == "RETRY_OPERATOR_DIRECTED"
    assert request.source_transaction_id == 9465
    assert request.expected_user_id == 222
    assert request.expected_referral_id == 1500
    assert request.expected_created_at == datetime(2026, 7, 20, tzinfo=timezone.utc)
    assert request.expected_participant_merge_audit_ids == (3, 17)
    assert request.accrual_strategy_snapshot is None
    assert request.reward_strategy is None
    assert request.config_value is None


@pytest.mark.asyncio
async def test_operator_recovery_batch_is_ordered_and_replayable() -> None:
    recovery = SimpleNamespace(system=AsyncMock())
    body = LegacyReferralRewardRecoveryBatchRequest.model_validate(
        {"entries": [_operator_recovery_payload(1342), _operator_recovery_payload(1343)]}
    )

    await recover_legacy_referral_rewards_batch_impl(body, recovery, None)

    assert [call.args[0].reward_id for call in recovery.system.await_args_list] == [1342, 1343]


def test_operator_recovery_batch_accepts_canonical_json_timestamp() -> None:
    payload = _operator_recovery_payload()
    payload["expected_created_at"] = "2026-07-20T00:00:00+00:00"

    body = LegacyReferralRewardRecoveryBatchRequest.model_validate({"entries": [payload]})

    assert body.entries[0].expected_created_at == datetime(
        2026,
        7,
        20,
        tzinfo=timezone.utc,
    )


@pytest.mark.parametrize(
    "timestamp",
    ["2026-07-20T00:00:00", "2026-07-20T00:00:00Z"],
)
def test_operator_recovery_batch_rejects_noncanonical_json_timestamp(
    timestamp: str,
) -> None:
    payload = _operator_recovery_payload()
    payload["expected_created_at"] = timestamp

    with pytest.raises(ValidationError, match="canonical and timezone-aware"):
        LegacyReferralRewardRecoveryBatchRequest.model_validate({"entries": [payload]})


@pytest.mark.parametrize(
    "payload",
    [
        _legacy_recovery_payload("RETRY_PROVEN_MISSING") | {"accrual_strategy_snapshot": None},
        _legacy_recovery_payload("CONFIRM_ADMIN_COMPENSATED")
        | {
            "accrual_strategy_snapshot": "ON_FIRST_PAYMENT",
            "reward_strategy": "AMOUNT",
            "config_value": 3,
        },
        _legacy_recovery_payload("RETRY_PROVEN_MISSING") | {"evidence_sha256": "A" * 64},
    ],
)
def test_legacy_recovery_schema_rejects_ambiguous_evidence(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        LegacyReferralRewardRecoveryRequest.model_validate(payload)


@pytest.mark.parametrize(
    "merge_audit_ids",
    [[17, 3], [3, 3], [0], [-1]],
)
def test_operator_recovery_schema_requires_canonical_merge_audit_ids(
    merge_audit_ids: list[int],
) -> None:
    payload = _operator_recovery_payload()
    payload.pop("reward_id")
    payload["expected_participant_merge_audit_ids"] = merge_audit_ids

    with pytest.raises(ValidationError, match="positive, sorted, and unique"):
        LegacyReferralRewardRecoveryRequest.model_validate(payload)


def test_nonoperator_recovery_rejects_participant_merge_audit_ids() -> None:
    payload = _legacy_recovery_payload()
    payload["expected_participant_merge_audit_ids"] = [3]

    with pytest.raises(ValidationError, match="operator row hints"):
        LegacyReferralRewardRecoveryRequest.model_validate(payload)


def test_legacy_recovery_uses_only_neutral_authenticated_route() -> None:
    paths = {route.path for route in referral_rewards_router.routes}
    assert "/referral-rewards/{reward_id}/recover-legacy" in paths
    assert "/referral-rewards/{reward_id}/retry-proven-missing" not in paths
    assert "/referral-rewards/{reward_id}/legacy-recovery" not in paths


@pytest.mark.asyncio
async def test_manual_rewards_dispatches_pagination_and_returns_referral_id() -> None:
    reward = ReferralRewardDto(
        id=8,
        user_id=2,
        referral_id=101,
        type=ReferralRewardType.POINTS,
        amount=10,
        state=ReferralRewardState.MANUAL_REQUIRED,
    )
    referral_dao = SimpleNamespace(get_manual_required_rewards=AsyncMock(return_value=[reward]))

    result = await list_manual_referral_rewards_impl(
        referral_dao,
        limit=25,
        offset=50,
        _=None,
    )

    referral_dao.get_manual_required_rewards.assert_awaited_once_with(
        limit=25,
        offset=50,
    )
    assert len(result) == 1
    assert result[0].referral_id == 101


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("limit", "offset"),
    [(0, 0), (501, 0), (100, -1)],
)
async def test_manual_rewards_rejects_invalid_pagination(limit: int, offset: int) -> None:
    referral_dao = SimpleNamespace(get_manual_required_rewards=AsyncMock())

    with pytest.raises(HTTPException) as exc_info:
        await list_manual_referral_rewards_impl(
            referral_dao,
            limit=limit,
            offset=offset,
            _=None,
        )

    assert exc_info.value.status_code == 422
    referral_dao.get_manual_required_rewards.assert_not_awaited()


@pytest.mark.parametrize(
    "schema",
    [HistoricalReferralBackfillPreviewRequest, HistoricalReferralBackfillApplyRequest],
)
@pytest.mark.parametrize(
    "field",
    ["operator_identity", "operator_reference", "reason"],
)
def test_historical_backfill_schema_requires_operator_evidence(
    schema: type[BaseModel],
    field: str,
) -> None:
    payload = _backfill_request_payload()
    if schema is HistoricalReferralBackfillApplyRequest:
        payload["expected_config_snapshot"] = _backfill_config_snapshot()

    missing = dict(payload)
    missing.pop(field)
    with pytest.raises(ValidationError):
        schema.model_validate(missing)

    blank = dict(payload)
    blank[field] = " "
    with pytest.raises(ValidationError):
        schema.model_validate(blank)


@pytest.mark.parametrize(
    "schema",
    [HistoricalReferralBackfillPreviewRequest, HistoricalReferralBackfillApplyRequest],
)
def test_historical_backfill_schema_requires_explicit_source_ids(
    schema: type[BaseModel],
) -> None:
    payload = _backfill_request_payload()
    if schema is HistoricalReferralBackfillApplyRequest:
        payload["expected_config_snapshot"] = _backfill_config_snapshot()

    payload.pop("source_transaction_ids")
    with pytest.raises(ValidationError):
        schema.model_validate(payload)

    payload["source_transaction_ids"] = []
    with pytest.raises(ValidationError):
        schema.model_validate(payload)


def test_historical_backfill_apply_schema_requires_explicit_config_snapshot() -> None:
    with pytest.raises(ValidationError):
        HistoricalReferralBackfillApplyRequest.model_validate(_backfill_request_payload())


@pytest.mark.parametrize(
    "config_snapshot",
    [
        _backfill_config_snapshot() | {"enabled": 1},
        _backfill_config_snapshot() | {"max_level": True},
        _backfill_config_snapshot() | {"max_level": "2"},
        _backfill_config_snapshot() | {"reward_config": {"1": 10, "2": True}},
        _backfill_config_snapshot() | {"unexpected": "value"},
    ],
)
def test_historical_backfill_config_snapshot_rejects_type_spoofing(
    config_snapshot: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        HistoricalReferralBackfillApplyRequest.model_validate(
            _backfill_request_payload() | {"expected_config_snapshot": config_snapshot}
        )


@pytest.mark.asyncio
async def test_historical_backfill_inventory_dispatches_pagination() -> None:
    backfill = SimpleNamespace(system=AsyncMock(return_value={"read_only": True}))

    result = await inventory_historical_referral_rewards_impl(
        backfill,
        limit=25,
        offset=50,
        _=None,
    )

    assert result == {"read_only": True}
    request = backfill.system.await_args.args[0]
    assert request.action == "INVENTORY"
    assert request.limit == 25
    assert request.offset == 50
    assert request.source_transaction_ids == ()


@pytest.mark.asyncio
async def test_historical_backfill_preview_dispatches_explicit_evidence() -> None:
    backfill = SimpleNamespace(system=AsyncMock(return_value={"preview_id": 31}))
    body = HistoricalReferralBackfillPreviewRequest.model_validate(_backfill_request_payload())

    result = await preview_historical_referral_rewards_impl(body, backfill, None)

    assert result == {"preview_id": 31}
    request = backfill.system.await_args.args[0]
    assert request.action == "PREVIEW"
    assert request.source_transaction_ids == (77, 91)
    assert request.operator_identity == "alice"
    assert request.operator_reference == "TICKET-135"
    assert request.reason == "Verified missing durable intents against payment records"


@pytest.mark.asyncio
async def test_historical_backfill_disabled_is_explicitly_unavailable() -> None:
    backfill = SimpleNamespace(
        system=AsyncMock(
            side_effect=HistoricalReferralBackfillUnavailableError("backfill disabled")
        )
    )
    body = HistoricalReferralBackfillPreviewRequest.model_validate(_backfill_request_payload())

    with pytest.raises(HTTPException) as exc_info:
        await preview_historical_referral_rewards_impl(body, backfill, None)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "backfill disabled"


@pytest.mark.asyncio
async def test_historical_backfill_apply_dispatches_preview_id_and_exact_config() -> None:
    backfill = SimpleNamespace(system=AsyncMock(return_value={"status": "APPLIED"}))
    config_snapshot = _backfill_config_snapshot()
    body = HistoricalReferralBackfillApplyRequest.model_validate(
        _backfill_request_payload() | {"expected_config_snapshot": config_snapshot}
    )

    result = await apply_historical_referral_rewards_impl(31, body, backfill, None)

    assert result == {"status": "APPLIED"}
    request = backfill.system.await_args.args[0]
    assert request.action == "APPLY"
    assert request.preview_id == 31
    assert request.source_transaction_ids == (77, 91)
    assert request.operator_identity == "alice"
    assert request.operator_reference == "TICKET-135"
    assert request.reason == "Verified missing durable intents against payment records"
    assert request.expected_config_snapshot == config_snapshot


@pytest.mark.asyncio
async def test_manual_resolution_endpoint_replays_identical_evidence_idempotently() -> None:
    resolver = SimpleNamespace(system=AsyncMock())
    body = ResolveManualReferralRewardRequest(
        resolution="CONFIRM_ISSUED",
        expected_version=3,
        operator_reference="alice/TICKET-123",
        reason="Verified Remnawave target and local balance",
        allow_drift=True,
    )

    await resolve_manual_referral_reward_impl(8, body, resolver, None)  # type: ignore[arg-type]
    await resolve_manual_referral_reward_impl(8, body, resolver, None)  # type: ignore[arg-type]

    assert resolver.system.await_count == 2
    first, second = resolver.system.await_args_list
    assert first.args[0] == second.args[0]
    assert first.args[0].operator_reference == "alice/TICKET-123"
    assert first.args[0].expected_version == 3
    assert first.args[0].allow_drift is True
