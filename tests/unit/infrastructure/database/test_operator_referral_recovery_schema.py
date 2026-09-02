import importlib
from typing import Any

import pytest

from src.infrastructure.database.constraints import (
    REFERRAL_REWARD_RESOLUTIONS_DECISION_CONSTRAINT_NAME,
    REFERRAL_REWARDS_DURABLE_STATE_CONSTRAINT_NAME,
)
from src.infrastructure.database.models import ReferralReward, ReferralRewardResolution


def _capture_operations(
    monkeypatch: pytest.MonkeyPatch,
    migration: Any,
) -> list[tuple[Any, ...]]:
    calls: list[tuple[Any, ...]] = []

    def recorder(name: str):  # type: ignore[no-untyped-def]
        def record(*args: Any, **kwargs: Any) -> None:
            calls.append((name, args, kwargs))

        return record

    for name in (
        "add_column",
        "create_check_constraint",
        "create_index",
        "drop_column",
        "drop_constraint",
        "drop_index",
        "execute",
    ):
        monkeypatch.setattr(migration.op, name, recorder(name))
    return calls


def test_0055_installs_durable_operator_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = importlib.import_module(
        "src.infrastructure.database.migrations.versions.0055_add_operator_referral_recovery"
    )
    calls = _capture_operations(monkeypatch, migration)

    migration.upgrade()

    assert migration.revision == "0055"
    assert migration.down_revision == "0054"
    column = next(
        args[1]
        for name, args, _ in calls
        if name == "add_column" and args[0] == "referral_rewards"
    )
    assert column.name == "operator_recovery_manifest_sha256"
    assert str(column.type) == "VARCHAR(64)"
    constraints = {
        args[0]: args[2]
        for name, args, _ in calls
        if name == "create_check_constraint"
    }
    reward_constraint = constraints[REFERRAL_REWARDS_DURABLE_STATE_CONSTRAINT_NAME]
    assert "operator_recovery_manifest_sha256 ~ '^[0-9a-f]{64}$'" in reward_constraint
    assert "source_transaction_id IS NULL" in reward_constraint
    resolution_constraint = constraints[REFERRAL_REWARD_RESOLUTIONS_DECISION_CONSTRAINT_NAME]
    assert "RETRY_OPERATOR_DIRECTED" in resolution_constraint
    assert "selected_source_transaction_id IS NOT NULL" in resolution_constraint
    recovery_index = next(
        (args, kwargs)
        for name, args, kwargs in calls
        if name == "create_index"
        and args[0] == "uq_referral_reward_resolutions_recovery_source_level"
    )
    assert recovery_index[1]["unique"] is True
    assert "RETRY_OPERATOR_DIRECTED" in str(recovery_index[1]["postgresql_where"])


def test_0055_downgrade_refuses_to_drop_consumed_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = importlib.import_module(
        "src.infrastructure.database.migrations.versions.0055_add_operator_referral_recovery"
    )
    calls = _capture_operations(monkeypatch, migration)

    migration.downgrade()

    assert calls[0][0] == "execute"
    guard = calls[0][1][0]
    assert "LOCK TABLE referral_rewards, referral_reward_resolutions" in guard
    assert "operator_recovery_manifest_sha256 IS NOT NULL" in guard
    assert "RETRY_OPERATOR_DIRECTED" in guard
    assert "ERRCODE = '55000'" in guard


def test_models_match_operator_recovery_authorization_shape() -> None:
    reward_table = ReferralReward.__table__
    digest = reward_table.c.operator_recovery_manifest_sha256
    assert digest.nullable is True
    assert digest.type.length == 64
    resolution_table = ReferralRewardResolution.__table__
    index = next(
        item
        for item in resolution_table.indexes
        if item.name == "uq_referral_reward_resolutions_recovery_source_level"
    )
    assert "RETRY_OPERATOR_DIRECTED" in str(index.dialect_options["postgresql"]["where"])
