import importlib
from types import SimpleNamespace
from typing import Any

import pytest

from src.infrastructure.database.dao.payment_operation import PaymentOperationDaoImpl
from src.infrastructure.database.models import PaymentOperation, Transaction


def _capture_migration(monkeypatch: pytest.MonkeyPatch, migration: Any) -> list[tuple[Any, ...]]:
    calls: list[tuple[Any, ...]] = []

    def recorder(name: str) -> Any:
        def record(*args: object, **kwargs: object) -> None:
            calls.append((name, args, kwargs))

        return record

    for name in (
        "add_column",
        "alter_column",
        "create_check_constraint",
        "create_foreign_key",
        "create_index",
        "create_table",
        "create_unique_constraint",
        "drop_column",
        "drop_constraint",
        "drop_index",
        "drop_table",
        "execute",
    ):
        monkeypatch.setattr(migration.op, name, recorder(name))
    monkeypatch.setattr(migration.op, "get_bind", lambda: object())
    monkeypatch.setattr(
        migration.postgresql.ENUM,
        "create",
        lambda self, *args, **kwargs: calls.append(("create_enum", args, kwargs)),
    )
    return calls


def test_0049_installs_owner_fence_and_exact_only_backfill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = importlib.import_module(
        "src.infrastructure.database.migrations.versions.0049_add_payment_reconciliation"
    )
    calls = _capture_migration(monkeypatch, migration)

    migration.upgrade()

    assert migration.revision == "0049"
    assert migration.down_revision == "0048"
    owner_fk = next(
        call
        for call in calls
        if call[0] == "create_foreign_key"
        and call[1][0] == "fk_payment_operations_transaction_owner"
    )
    assert owner_fk[1][3:5] == (["transaction_id", "user_id"], ["id", "user_id"])
    assert owner_fk[2] == {
        "ondelete": "RESTRICT",
        "deferrable": True,
        "initially": "DEFERRED",
    }

    check_names = {call[1][0] for call in calls if call[0] == "create_check_constraint"}
    assert {
        "ck_payment_operations_status",
        "ck_payment_operations_lease",
        "ck_payment_operations_recovery_mode",
        "ck_payment_operations_gateway_type",
        "ck_payment_operations_reconcile_lease",
        "ck_payment_operations_reconcile_attempt_count",
    } <= check_names
    gateway_check = next(
        str(call[1][2])
        for call in calls
        if call[0] == "create_check_constraint"
        and call[1][0] == "ck_payment_operations_gateway_type"
    )
    assert "'ROLLYPAY'" in gateway_check

    executed = "\n".join(str(call[1][0]) for call in calls if call[0] == "execute").upper()
    assert "T.PAYMENT_ID::TEXT = PO.RESPONSE ->> 'PAYMENT_ID'" in executed
    assert "T.USER_ID = PO.USER_ID" in executed
    assert "SET STATUS = 'MANUAL_REQUIRED'" in executed
    assert "FULFILLMENT_COMPLETED_AT = UPDATED_AT" not in executed
    legacy_backfill = next(
        str(call[1][0]).upper()
        for call in calls
        if call[0] == "execute"
        and "UPDATE PAYMENT_OPERATIONS AS PO" in str(call[1][0]).upper()
    )
    assert "FINAL_AMOUNT" not in legacy_backfill
    assert "PLAN_SNAPSHOT" not in legacy_backfill


def test_models_expose_deferred_same_owner_constraint() -> None:
    owner_fk = next(
        constraint
        for constraint in PaymentOperation.__table__.foreign_key_constraints
        if constraint.name == "fk_payment_operations_transaction_owner"
    )
    assert owner_fk.ondelete == "RESTRICT"
    assert owner_fk.deferrable is True
    assert owner_fk.initially == "DEFERRED"
    assert [column.name for column in owner_fk.columns] == ["transaction_id", "user_id"]
    assert [element.column.name for element in owner_fk.elements] == ["id", "user_id"]

    transaction_owner_key = next(
        constraint
        for constraint in Transaction.__table__.constraints
        if constraint.name == "uq_transactions_id_user_id"
    )
    assert [column.name for column in transaction_owner_key.columns] == ["id", "user_id"]


class _StatementSession:
    def __init__(self) -> None:
        self.statements: list[object] = []

    async def execute(self, statement: object) -> SimpleNamespace:
        self.statements.append(statement)
        return SimpleNamespace(rowcount=1)


@pytest.mark.asyncio
async def test_completion_and_reconciliation_updates_are_fenced() -> None:
    session = _StatementSession()
    dao = PaymentOperationDaoImpl(session)  # type: ignore[arg-type]

    assert await dao.complete(9, {"payment_id": "00000000-0000-0000-0000-000000000009"})
    assert await dao.complete_reconciliation(
        9,
        token_hash="a" * 64,
        transaction_id=17,
        response={"payment_id": "00000000-0000-0000-0000-000000000009"},
    )

    normal_sql = str(session.statements[0].compile()).upper()  # type: ignore[attr-defined]
    reconcile_sql = str(session.statements[1].compile()).upper()  # type: ignore[attr-defined]
    assert "PAYMENT_OPERATIONS.TRANSACTION_ID IS NOT NULL" in normal_sql
    assert "PAYMENT_OPERATIONS.STATUS" in normal_sql
    assert "PAYMENT_OPERATIONS.RECONCILE_TOKEN_HASH" in reconcile_sql
    assert "PAYMENT_OPERATIONS.TRANSACTION_ID IS NULL" in reconcile_sql
    assert "PAYMENT_OPERATIONS.TRANSACTION_ID =" in reconcile_sql
