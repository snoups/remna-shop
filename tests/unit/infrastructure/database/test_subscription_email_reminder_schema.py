import importlib
from unittest.mock import Mock

import pytest

from src.infrastructure.database.models import SubscriptionEmailReminder, User


def test_reminder_schema_migrations_are_linear_two_phase_steps() -> None:
    create_migration = importlib.import_module(
        "src.infrastructure.database.migrations.versions.0057_add_subscription_email_reminders"
    )
    validate_migration = importlib.import_module(
        "src.infrastructure.database.migrations.versions.0058_validate_subscription_email_consent"
    )

    assert create_migration.revision == "0057"
    assert create_migration.down_revision == "0056"
    assert validate_migration.revision == "0058"
    assert validate_migration.down_revision == "0057"


def test_0057_creates_supporting_terminal_retention_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = importlib.import_module(
        "src.infrastructure.database.migrations.versions.0057_add_subscription_email_reminders"
    )
    create_index = Mock()
    monkeypatch.setattr(migration.op, "add_column", Mock())
    monkeypatch.setattr(migration.op, "execute", Mock())
    monkeypatch.setattr(migration.op, "create_table", Mock())
    monkeypatch.setattr(migration.op, "create_index", create_index)

    migration.upgrade()

    terminal_call = next(
        call
        for call in create_index.call_args_list
        if call.args[0] == "ix_subscription_email_reminders_terminal_retention"
    )
    assert terminal_call.args[1:] == (
        "subscription_email_reminders",
        ["updated_at", "id"],
    )
    where = str(terminal_call.kwargs["postgresql_where"])
    assert where == "state IN ('SENT', 'CANCELED', 'FAILED')"


def test_user_consent_constraints_use_two_phase_non_blocking_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_migration = importlib.import_module(
        "src.infrastructure.database.migrations.versions.0057_add_subscription_email_reminders"
    )
    validate_migration = importlib.import_module(
        "src.infrastructure.database.migrations.versions.0058_validate_subscription_email_consent"
    )
    create_events: list[tuple[str, str]] = []
    validate_statements: list[str] = []

    monkeypatch.setattr(
        create_migration.op,
        "create_table",
        lambda name, *args, **kwargs: create_events.append(("create_table", name)),
    )
    monkeypatch.setattr(
        create_migration.op,
        "create_index",
        lambda name, *args, **kwargs: create_events.append(("create_index", name)),
    )
    monkeypatch.setattr(
        create_migration.op,
        "add_column",
        lambda table, column, **kwargs: create_events.append(
            ("add_column", f"{table}.{column.name}")
        ),
    )
    monkeypatch.setattr(
        create_migration.op,
        "execute",
        lambda statement: create_events.append(("execute", str(statement))),
    )

    create_migration.upgrade()

    lock_timeout_index = next(
        index
        for index, event in enumerate(create_events)
        if event[0] == "execute" and "SET LOCAL lock_timeout" in event[1]
    )
    assert lock_timeout_index == 0
    user_alter_indexes = [
        index
        for index, event in enumerate(create_events)
        if event[0] == "add_column"
        or (event[0] == "execute" and "ALTER TABLE public.users" in event[1])
    ]
    assert user_alter_indexes
    assert all(lock_timeout_index < index for index in user_alter_indexes)
    add_constraint_sql = "\n".join(
        statement
        for operation, statement in create_events
        if operation == "execute" and "ADD CONSTRAINT" in statement
    )
    assert add_constraint_sql.count("ADD CONSTRAINT") == 2
    assert add_constraint_sql.count("NOT VALID") == 2
    assert "VALIDATE CONSTRAINT" not in add_constraint_sql
    trigger_sql = "\n".join(
        statement
        for operation, statement in create_events
        if operation == "execute" and "TRIGGER" in statement
    )
    assert "BEFORE UPDATE OF email, is_email_verified ON public.users" in trigger_sql
    function_sql = next(
        statement
        for operation, statement in create_events
        if operation == "execute" and "CREATE FUNCTION" in statement
    )
    assert "NEW.email IS DISTINCT FROM OLD.email" in function_sql
    assert "NEW.is_email_verified IS NOT TRUE" in function_sql
    assert "NEW.subscription_expiration_email_enabled := false" in function_sql
    assert "NEW.subscription_expiration_email_enabled_at := NULL" in function_sql

    monkeypatch.setattr(
        validate_migration.op,
        "execute",
        lambda statement: validate_statements.append(str(statement)),
    )
    validate_migration.upgrade()

    validate_sql = "\n".join(validate_statements)
    assert len(validate_statements) == 4
    assert "SET LOCAL lock_timeout = '5s'" in validate_statements[0]
    assert "SET LOCAL statement_timeout = '5min'" in validate_statements[1]
    assert validate_sql.count("VALIDATE CONSTRAINT") == 2
    assert "NOT VALID" not in validate_sql


def test_two_phase_validation_keeps_safe_downgrade_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_migration = importlib.import_module(
        "src.infrastructure.database.migrations.versions.0057_add_subscription_email_reminders"
    )
    validate_migration = importlib.import_module(
        "src.infrastructure.database.migrations.versions.0058_validate_subscription_email_consent"
    )
    events: list[tuple[str, str]] = []

    monkeypatch.setattr(
        validate_migration.op,
        "execute",
        lambda statement: events.append(("execute", str(statement))),
    )
    validate_migration.downgrade()
    assert events == []

    monkeypatch.setattr(create_migration.op, "drop_index", Mock())
    monkeypatch.setattr(create_migration.op, "drop_table", Mock())
    monkeypatch.setattr(
        create_migration.op,
        "drop_constraint",
        lambda name, *args, **kwargs: events.append(("drop_constraint", name)),
    )
    monkeypatch.setattr(
        create_migration.op,
        "drop_column",
        lambda table, name, **kwargs: events.append(("drop_column", name)),
    )

    create_migration.downgrade()

    assert [event[0] for event in events] == [
        "execute",
        "execute",
        "drop_constraint",
        "drop_constraint",
        "drop_column",
        "drop_column",
    ]
    assert "DROP TRIGGER IF EXISTS" in events[0][1]
    assert "ON public.users" in events[0][1]
    assert "DROP FUNCTION IF EXISTS" in events[1][1]
    assert events[2:] == [
        ("drop_constraint", "ck_users_subscription_email_consent_timestamp"),
        ("drop_constraint", "ck_users_subscription_email_consent_eligible"),
        ("drop_column", "subscription_expiration_email_enabled_at"),
        ("drop_column", "subscription_expiration_email_enabled"),
    ]


def test_user_notification_consent_is_fail_closed_by_default() -> None:
    enabled = User.__table__.c.subscription_expiration_email_enabled
    enabled_at = User.__table__.c.subscription_expiration_email_enabled_at

    assert enabled.nullable is False
    assert enabled.server_default is not None
    assert str(enabled.server_default.arg) == "false"
    assert enabled_at.nullable is True
    constraint_names = {constraint.name for constraint in User.__table__.constraints}
    assert "ck_users_subscription_email_consent_eligible" in constraint_names
    assert "ck_users_subscription_email_consent_timestamp" in constraint_names


def test_reminder_outbox_has_durable_identity_fence_and_due_index() -> None:
    table = SubscriptionEmailReminder.__table__
    constraint_names = {constraint.name for constraint in table.constraints}
    index_names = {index.name for index in table.indexes}

    assert "uq_subscription_email_reminder_identity" in constraint_names
    assert "ck_subscription_email_reminder_days_before" in constraint_names
    assert "ck_subscription_email_reminder_state" in constraint_names
    assert "ck_subscription_email_reminder_processing_fence" in constraint_names
    assert "ix_subscription_email_reminders_due" in index_names
    assert "ix_subscription_email_reminders_terminal_retention" in index_names
    terminal_index = next(
        index
        for index in table.indexes
        if index.name == "ix_subscription_email_reminders_terminal_retention"
    )
    assert [column.name for column in terminal_index.columns] == ["updated_at", "id"]
    assert str(terminal_index.dialect_options["postgresql"]["where"]) == (
        "state IN ('SENT', 'CANCELED', 'FAILED')"
    )
    assert table.c.processing_token_hash.type.length == 64
    assert table.c.processing_lease_expires_at.nullable is True
    assert table.c.next_attempt_at.nullable is False
