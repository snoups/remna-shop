import importlib
from typing import Any

import pytest


def _capture_execute(monkeypatch: pytest.MonkeyPatch, migration: Any) -> list[str]:
    statements: list[str] = []
    monkeypatch.setattr(
        migration.op,
        "execute",
        lambda statement: statements.append(str(statement)),
    )
    return statements


def test_0050_installs_immutable_merge_target_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    migration = importlib.import_module(
        "src.infrastructure.database.migrations.versions.0050_protect_user_merge_target"
    )
    statements = _capture_execute(monkeypatch, migration)

    migration.upgrade()

    assert migration.revision == "0050"
    assert migration.down_revision == "0049"
    sql = "\n".join(statements).upper()
    assert "CREATE FUNCTION ENFORCE_USER_MERGE_TARGET_IMMUTABLE" in sql
    assert "OLD.MERGED_INTO_USER_ID IS NOT NULL" in sql
    assert "NEW.MERGED_INTO_USER_ID IS DISTINCT FROM OLD.MERGED_INTO_USER_ID" in sql
    assert "ERRCODE = '23514'" in sql
    assert "CONSTRAINT = 'CK_USERS_MERGED_TARGET_IMMUTABLE'" in sql
    assert "CREATE TRIGGER TRG_USERS_MERGED_TARGET_IMMUTABLE" in sql
    assert "BEFORE UPDATE OF MERGED_INTO_USER_ID ON USERS" in sql


def test_0050_downgrade_removes_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    migration = importlib.import_module(
        "src.infrastructure.database.migrations.versions.0050_protect_user_merge_target"
    )
    statements = _capture_execute(monkeypatch, migration)

    migration.downgrade()

    assert statements == [
        "DROP TRIGGER IF EXISTS trg_users_merged_target_immutable ON users",
        "DROP FUNCTION IF EXISTS enforce_user_merge_target_immutable()",
    ]
