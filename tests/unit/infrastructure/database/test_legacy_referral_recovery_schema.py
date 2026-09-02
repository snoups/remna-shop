import importlib
from typing import Any

import pytest

from src.infrastructure.database.constraints import (
    REFERRAL_REWARD_RESOLUTIONS_DECISION_CONSTRAINT_NAME,
)
from src.infrastructure.database.models import ReferralRewardResolution


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
        "create_foreign_key",
        "create_index",
        "drop_column",
        "drop_constraint",
        "drop_index",
        "execute",
    ):
        monkeypatch.setattr(migration.op, name, recorder(name))
    return calls


def test_0054_installs_immutable_legacy_recovery_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = importlib.import_module(
        "src.infrastructure.database.migrations.versions.0054_add_legacy_referral_reward_recovery"
    )
    calls = _capture_operations(monkeypatch, migration)

    migration.upgrade()

    assert migration.revision == "0054"
    assert migration.down_revision == "0053"
    columns = {
        args[1].name: args[1]
        for name, args, _ in calls
        if name == "add_column" and args[0] == "referral_reward_resolutions"
    }
    assert set(columns) == {
        "selected_provenance",
        "evidence_sha256",
        "selected_source_transaction_id",
        "selected_origin_referral_id",
        "selected_level",
        "authorization_manifest_sha256",
    }
    assert str(columns["selected_provenance"].type) == "JSONB"
    assert str(columns["evidence_sha256"].type) == "VARCHAR(64)"
    assert str(columns["selected_source_transaction_id"].type) == "INTEGER"
    assert str(columns["selected_origin_referral_id"].type) == "INTEGER"
    assert str(columns["selected_level"].type) == "VARCHAR"
    assert str(columns["authorization_manifest_sha256"].type) == "VARCHAR(64)"
    constraint = next(
        args[2]
        for name, args, _ in calls
        if name == "create_check_constraint"
        and args[0] == REFERRAL_REWARD_RESOLUTIONS_DECISION_CONSTRAINT_NAME
    )
    assert "RETRY_PROVEN_MISSING" in constraint
    assert "CONFIRM_ADMIN_COMPENSATED" in constraint
    assert "ACK_ADMIN_COMPENSATED_REFUND" in constraint
    assert "jsonb_typeof(selected_provenance) = 'object'" in constraint
    assert "evidence_sha256 IS NOT NULL" in constraint
    assert "evidence_sha256 ~ '^[0-9a-f]{64}$'" in constraint
    assert "selected_source_transaction_id IS NOT NULL" in constraint
    assert "selected_origin_referral_id IS NOT NULL" in constraint
    assert "selected_level IS NOT NULL" in constraint
    assert "authorization_manifest_sha256 IS NOT NULL" in constraint
    assert "source_status = 'REFUNDED'" in constraint
    recovery_index = next(
        (args, kwargs)
        for name, args, kwargs in calls
        if name == "create_index"
        and args[0] == "uq_referral_reward_resolutions_recovery_source_level"
    )
    assert recovery_index[0][2] == ["selected_source_transaction_id", "selected_level"]
    assert recovery_index[1]["unique"] is True
    assert "CONFIRM_ADMIN_COMPENSATED" in str(recovery_index[1]["postgresql_where"])


def test_0054_downgrade_refuses_to_drop_existing_recovery_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = importlib.import_module(
        "src.infrastructure.database.migrations.versions.0054_add_legacy_referral_reward_recovery"
    )
    calls = _capture_operations(monkeypatch, migration)

    migration.downgrade()

    assert calls[0][0] == "execute"
    guard = calls[0][1][0]
    assert "LOCK TABLE referral_reward_resolutions IN SHARE MODE" in guard
    assert "RETRY_PROVEN_MISSING" in guard
    assert "CONFIRM_ADMIN_COMPENSATED" in guard
    assert "ACK_ADMIN_COMPENSATED_REFUND" in guard
    assert "ERRCODE = '55000'" in guard


def test_resolution_model_matches_0054_evidence_shape() -> None:
    table = ReferralRewardResolution.__table__
    assert table.c.selected_provenance.nullable is True
    assert str(table.c.selected_provenance.type) == "JSONB"
    assert table.c.evidence_sha256.nullable is True
    assert table.c.evidence_sha256.type.length == 64
    assert table.c.selected_source_transaction_id.nullable is True
    assert table.c.selected_origin_referral_id.nullable is True
    assert table.c.selected_level.nullable is True
    assert table.c.authorization_manifest_sha256.nullable is True
    assert table.c.authorization_manifest_sha256.type.length == 64
    source_fk = next(iter(table.c.selected_source_transaction_id.foreign_keys))
    origin_fk = next(iter(table.c.selected_origin_referral_id.foreign_keys))
    assert source_fk.target_fullname == "transactions.id"
    assert source_fk.ondelete == "RESTRICT"
    assert origin_fk.target_fullname == "referrals.id"
    assert origin_fk.ondelete == "RESTRICT"
    recovery_index = next(
        index
        for index in table.indexes
        if index.name == "uq_referral_reward_resolutions_recovery_source_level"
    )
    assert recovery_index.unique is True
    assert [column.name for column in recovery_index.columns] == [
        "selected_source_transaction_id",
        "selected_level",
    ]
    constraint = next(
        item
        for item in table.constraints
        if item.name == REFERRAL_REWARD_RESOLUTIONS_DECISION_CONSTRAINT_NAME
    )
    sql = str(constraint.sqltext)
    assert "RETRY_PROVEN_MISSING" in sql
    assert "CONFIRM_ADMIN_COMPENSATED" in sql
    assert "ACK_ADMIN_COMPENSATED_REFUND" in sql
