import importlib
from typing import Any

import pytest


def _capture_operations(monkeypatch: pytest.MonkeyPatch, migration: Any) -> list[tuple[Any, ...]]:
    calls: list[tuple[Any, ...]] = []

    for name in ("execute", "alter_column", "create_check_constraint", "drop_constraint"):
        monkeypatch.setattr(
            migration.op,
            name,
            lambda *args, _name=name, **kwargs: calls.append((_name, args, kwargs)),
        )

    return calls


def test_0051_permanently_finalizes_global_rollout_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = importlib.import_module(
        "src.infrastructure.database.migrations.versions.0051_finalize_payment_rollout"
    )
    calls = _capture_operations(monkeypatch, migration)

    migration.upgrade()

    assert migration.revision == "0051"
    assert migration.down_revision == "0050"
    statements = [args[0] for name, args, _kwargs in calls if name == "execute"]
    assert any("SET legacy_rollout_gate_active = false" in sql for sql in statements)
    guard = next(sql for sql in statements if "CREATE OR REPLACE FUNCTION" in sql)
    assert "payment_runtime_control" not in guard
    assert "cannot merge user during active payment work" in guard
    assert "payment_operations" in guard
    assert "transactions" in guard
    assert (
        "create_check_constraint",
        (
            "ck_payment_runtime_control_rollout_finalized",
            "payment_runtime_control",
            "legacy_rollout_gate_active = false",
        ),
        {},
    ) in calls
    assert any(
        name == "alter_column"
        and args[:2] == ("payment_runtime_control", "legacy_rollout_gate_active")
        and kwargs["server_default"] == "false"
        for name, args, kwargs in calls
    )


def test_0051_downgrade_restores_fail_closed_rollout_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = importlib.import_module(
        "src.infrastructure.database.migrations.versions.0051_finalize_payment_rollout"
    )
    calls = _capture_operations(monkeypatch, migration)

    migration.downgrade()

    statements = [args[0] for name, args, _kwargs in calls if name == "execute"]
    guard = next(sql for sql in statements if "CREATE OR REPLACE FUNCTION" in sql)
    assert "user merge disabled during payment rollout gate" in guard
    assert "payment_runtime_control" in guard
    assert any("SET legacy_rollout_gate_active = true" in sql for sql in statements)
    assert (
        "drop_constraint",
        ("ck_payment_runtime_control_rollout_finalized", "payment_runtime_control"),
        {"type_": "check"},
    ) in calls
    assert any(
        name == "alter_column"
        and args[:2] == ("payment_runtime_control", "legacy_rollout_gate_active")
        and kwargs["server_default"] == "true"
        for name, args, kwargs in calls
    )
