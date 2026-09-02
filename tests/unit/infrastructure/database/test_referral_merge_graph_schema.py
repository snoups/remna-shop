import importlib
from typing import Any

import pytest

from src.infrastructure.database.referral_graph import (
    REFERRAL_GRAPH_ADVISORY_LOCK_ID,
)


def _capture_sql(
    monkeypatch: pytest.MonkeyPatch,
    migration: Any,
) -> list[str]:
    statements: list[str] = []

    def execute(statement: object) -> None:
        statements.append(str(statement))

    monkeypatch.setattr(migration.op, "execute", execute)
    return statements


def test_0056_repairs_canonical_referrers_and_installs_graph_invariants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = importlib.import_module(
        "src.infrastructure.database.migrations.versions.0056_harden_referral_graph_merges"
    )
    statements = _capture_sql(monkeypatch, migration)

    migration.upgrade()

    assert migration.revision == "0056"
    assert migration.down_revision == "0055"
    assert migration.REFERRAL_GRAPH_ADVISORY_LOCK_ID == REFERRAL_GRAPH_ADVISORY_LOCK_ID
    assert len(statements) == 9
    sql = "\n".join(statements)
    assert f"pg_advisory_xact_lock({REFERRAL_GRAPH_ADVISORY_LOCK_ID})" in sql
    assert "LOCK TABLE referrals IN SHARE ROW EXCLUSIVE MODE" in sql
    assert "CREATE TEMP TABLE remnashop_0056_user_canonical_map" in sql
    assert "user merge graph has a cycle or exceeds 64 hops" in sql
    assert "CREATE TEMP TABLE remnashop_0056_referral_repair" in sql
    assert "referral graph contains a cycle after canonical merge projection" in sql
    assert "SET referrer_id = repair.canonical_referrer_id" in sql
    assert "CREATE OR REPLACE FUNCTION enforce_canonical_referral_edge()" in sql
    assert "NEW.referrer_id := canonical_referrer_id" in sql
    assert "NEW.referred_id := canonical_referred_id" in sql
    assert "referral edge would create a cycle" in sql
    assert "BEFORE INSERT OR UPDATE OF referrer_id, referred_id ON referrals" in sql


def test_0056_downgrade_removes_only_runtime_guards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = importlib.import_module(
        "src.infrastructure.database.migrations.versions.0056_harden_referral_graph_merges"
    )
    statements = _capture_sql(monkeypatch, migration)

    migration.downgrade()

    assert statements == [
        "DROP TRIGGER IF EXISTS trg_referrals_canonical_edge ON referrals",
        "DROP FUNCTION IF EXISTS enforce_canonical_referral_edge()",
    ]
