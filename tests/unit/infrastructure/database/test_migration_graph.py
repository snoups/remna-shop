import importlib
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from src.infrastructure.database.models.user import User


def _script_directory() -> ScriptDirectory:
    repository = Path(__file__).resolve().parents[4]
    config = Config()
    config.set_main_option(
        "script_location",
        str(repository / "src" / "infrastructure" / "database" / "migrations"),
    )
    return ScriptDirectory.from_config(config)


def test_migration_graph_is_unique_linear_and_preserves_production_0050_path() -> None:
    scripts = _script_directory()
    revisions = list(scripts.walk_revisions())
    revision_ids = [revision.revision for revision in revisions]

    assert len(revision_ids) == len(set(revision_ids))
    assert scripts.get_heads() == ["0058"]
    assert scripts.get_revision("0058").down_revision == "0057"
    assert scripts.get_revision("0057").down_revision == "0056"
    assert scripts.get_revision("0046").path.endswith("0046_add_password_reset_attempts.py")
    assert scripts.get_revision("0046_user_merge").down_revision == "0046"
    assert scripts.get_revision("0047").down_revision == "0046_user_merge"

    # Production already has the old integration meaning of 0050. Its forward
    # path must not replay user-merge/payment DDL from 0046_user_merge..0050.
    current = "0054"
    production_upgrade_path: list[str] = []
    while current != "0050":
        production_upgrade_path.append(current)
        down_revision = scripts.get_revision(current).down_revision
        assert isinstance(down_revision, str)
        current = down_revision

    assert production_upgrade_path == ["0054", "0053", "0052", "0051"]


def test_migration_runner_commits_between_two_phase_constraint_steps() -> None:
    repository = Path(__file__).resolve().parents[4]
    env_source = (
        repository / "src" / "infrastructure" / "database" / "migrations" / "env.py"
    ).read_text(encoding="utf-8")

    # Both online production upgrades and offline SQL generation must preserve
    # the revision boundary: otherwise 0057's ACCESS EXCLUSIVE lock would be
    # held while 0058 scans users during VALIDATE CONSTRAINT.
    assert env_source.count("transaction_per_migration=True") == 2


def test_0053_reconciles_password_attempts_without_breaking_old_app_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = importlib.import_module(
        "src.infrastructure.database.migrations.versions.0053_reconcile_password_reset_attempts"
    )
    statements: list[str] = []
    monkeypatch.setattr(migration.op, "execute", statements.append)

    migration.upgrade()

    sql = "\n".join(statements)
    assert migration.revision == "0053"
    assert migration.down_revision == "0052"
    assert statements[0].find("existing_data_type <> 'integer'") >= 0
    assert "ERRCODE = '42804'" in statements[0]
    assert "ADD COLUMN IF NOT EXISTS password_reset_attempts INTEGER DEFAULT 0" in sql
    assert "ALTER COLUMN password_reset_attempts SET DEFAULT 0" in sql
    assert "WHERE password_reset_attempts IS NULL" in sql
    assert "ALTER COLUMN password_reset_attempts SET NOT NULL" in sql


def test_password_reset_attempts_model_matches_0053_rollback_compatible_default() -> None:
    column = User.__table__.c.password_reset_attempts

    assert str(column.type) == "INTEGER"
    assert column.nullable is False
    assert column.server_default is not None
    assert str(column.server_default.arg) == "0"
