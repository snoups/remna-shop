import importlib
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql

from src.application.common.dao.payment_operation import PaymentOperationOwnerMergedError
from src.infrastructure.database.dao.payment_operation import PaymentOperationDaoImpl
from src.infrastructure.database.models import PaymentOperation


class OwnerResult:
    def __init__(self, owner: object) -> None:
        self.owner = owner

    def one_or_none(self) -> object:
        return self.owner


class OwnerSession:
    def __init__(self, merged_into_user_id: int | None) -> None:
        self.owner = SimpleNamespace(
            id=7,
            merged_into_user_id=merged_into_user_id,
        )
        self.executed: list[object] = []
        self.scalar_calls = 0

    async def execute(self, statement: object) -> OwnerResult:
        self.executed.append(statement)
        return OwnerResult(self.owner)

    async def scalar(self, statement: object) -> object:
        self.scalar_calls += 1
        raise AssertionError(f"claim must stop before insert, got {statement!r}")


def _postgresql_sql(statement: object) -> str:
    return str(
        statement.compile(  # type: ignore[attr-defined]
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_claim_owner_lock_uses_key_share() -> None:
    sql = _postgresql_sql(PaymentOperationDaoImpl._owner_lock_stmt(7)).upper()

    assert "USERS.MERGED_INTO_USER_ID" in sql
    assert "USERS.ID = 7" in sql
    assert "FOR KEY SHARE" in sql


@pytest.mark.asyncio
async def test_claim_after_user_merge_fails_before_insert() -> None:
    session = OwnerSession(merged_into_user_id=22)
    dao = PaymentOperationDaoImpl(session)  # type: ignore[arg-type]

    with pytest.raises(PaymentOperationOwnerMergedError):
        await dao.claim(
            user_id=7,
            operation="PURCHASE",
            idempotency_key="merge-safe-key",
            request_hash="a" * 64,
            provider_key="provider-key",
            lease_for=timedelta(minutes=1),
        )

    assert len(session.executed) == 1
    assert session.scalar_calls == 0


def test_payment_operation_model_uses_named_restrict_fk() -> None:
    foreign_key = next(
        foreign_key
        for foreign_key in PaymentOperation.__table__.c.user_id.foreign_keys
        if foreign_key.name == "fk_payment_operations_user_id_users"
    )

    assert foreign_key.name == "fk_payment_operations_user_id_users"
    assert foreign_key.ondelete == "RESTRICT"


def _record_operation_calls(monkeypatch: pytest.MonkeyPatch, migration: Any) -> list[tuple]:
    calls: list[tuple] = []

    def drop_constraint(*args: object, **kwargs: object) -> None:
        calls.append(("drop_constraint", args, kwargs))

    def create_foreign_key(*args: object, **kwargs: object) -> None:
        calls.append(("create_foreign_key", args, kwargs))

    def execute(statement: object) -> None:
        calls.append(("execute", statement))

    monkeypatch.setattr(migration.op, "drop_constraint", drop_constraint)
    monkeypatch.setattr(migration.op, "create_foreign_key", create_foreign_key)
    monkeypatch.setattr(migration.op, "execute", execute)
    return calls


def test_migration_installs_restrict_fk_and_serializing_trigger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = importlib.import_module(
        "src.infrastructure.database.migrations.versions."
        "0048_protect_payment_operations_on_user_merge"
    )
    calls = _record_operation_calls(monkeypatch, migration)

    migration.upgrade()

    dropped = next(call for call in calls if call[0] == "drop_constraint")
    assert dropped[1][0] == "payment_operations_user_id_fkey"
    created = next(call for call in calls if call[0] == "create_foreign_key")
    assert created[1][0] == "fk_payment_operations_user_id_users"
    assert created[2]["ondelete"] == "RESTRICT"

    executed_sql = "\n".join(str(call[1]) for call in calls if call[0] == "execute").upper()
    assert "CREATE FUNCTION ENFORCE_PAYMENT_OPERATION_ACTIVE_USER" in executed_sql
    assert "FOR KEY SHARE" in executed_sql
    assert "OWNER_MERGED_INTO_USER_ID IS NOT NULL" in executed_sql
    assert "BEFORE INSERT OR UPDATE OF USER_ID ON PAYMENT_OPERATIONS" in executed_sql
    assert "CK_PAYMENT_OPERATIONS_ACTIVE_USER" in executed_sql
    assert "CREATE FUNCTION ENFORCE_USER_MERGE_WITHOUT_PAYMENT_OPERATIONS" in executed_sql
    assert "BEFORE UPDATE OF MERGED_INTO_USER_ID ON USERS" in executed_sql
    assert "PAYMENT OPERATIONS STILL REFERENCE THE SOURCE" in executed_sql
    assert "CK_MERGED_USERS_HAVE_NO_PAYMENT_OPERATIONS" in executed_sql
    assert "MIGRATION 0048 BLOCKED" in executed_sql
    assert "BELONG TO MERGED USERS" in executed_sql

    statements = [str(call[1]).upper() for call in calls if call[0] == "execute"]
    user_trigger_index = next(
        index
        for index, statement in enumerate(statements)
        if "CREATE TRIGGER TRG_USERS_MERGE_WITHOUT_PAYMENT_OPERATIONS" in statement
    )
    preexisting_data_check_index = next(
        index
        for index, statement in enumerate(statements)
        if "MIGRATION 0048 BLOCKED" in statement
    )
    assert user_trigger_index < preexisting_data_check_index


def test_migration_downgrade_restores_cascade_fk(monkeypatch: pytest.MonkeyPatch) -> None:
    migration = importlib.import_module(
        "src.infrastructure.database.migrations.versions."
        "0048_protect_payment_operations_on_user_merge"
    )
    calls = _record_operation_calls(monkeypatch, migration)

    migration.downgrade()

    created = next(call for call in calls if call[0] == "create_foreign_key")
    assert created[1][0] == "payment_operations_user_id_fkey"
    assert created[2]["ondelete"] == "CASCADE"
    executed_sql = "\n".join(str(call[1]) for call in calls if call[0] == "execute").upper()
    assert "DROP TRIGGER IF EXISTS TRG_PAYMENT_OPERATIONS_ACTIVE_USER" in executed_sql
    assert "DROP FUNCTION IF EXISTS ENFORCE_PAYMENT_OPERATION_ACTIVE_USER" in executed_sql
    assert "DROP TRIGGER IF EXISTS TRG_USERS_MERGE_WITHOUT_PAYMENT_OPERATIONS" in executed_sql
    assert "DROP FUNCTION IF EXISTS ENFORCE_USER_MERGE_WITHOUT_PAYMENT_OPERATIONS" in executed_sql
