from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy.dialects import postgresql

from src.core.enums import SubscriptionStatus
from src.infrastructure.database.dao.subscription_email_reminder import (
    CANCELED,
    FAILED,
    PROCESSING,
    SubscriptionEmailReminderDaoImpl,
)

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)


class RowsResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


class OneResult:
    def __init__(self, row: object | None) -> None:
        self._row = row

    def one_or_none(self) -> object | None:
        return self._row


def _compile(statement: object) -> tuple[str, dict[str, object]]:
    compiled = statement.compile(dialect=postgresql.dialect())  # type: ignore[attr-defined]
    return str(compiled).upper(), compiled.params


async def test_generator_sql_is_bounded_paid_current_finite_and_skips_old_thresholds() -> None:
    session = SimpleNamespace(
        execute=AsyncMock(
            return_value=RowsResult([(9, 17, NOW + timedelta(days=6))])
        ),
        scalars=AsyncMock(return_value=RowsResult([101, 102])),
    )
    dao = SubscriptionEmailReminderDaoImpl(session)  # type: ignore[arg-type]

    inserted = await dao.generate(
        now=NOW,
        days_before=(7, 3, 1),
        candidate_limit=500,
        generation_grace=timedelta(hours=1),
    )

    assert inserted == 2
    select_sql, select_params = _compile(session.execute.await_args.args[0])
    assert "USERS.CURRENT_SUBSCRIPTION_ID = SUBSCRIPTIONS.ID" in select_sql
    assert "USERS.SUBSCRIPTION_EXPIRATION_EMAIL_ENABLED IS TRUE" in select_sql
    assert "USERS.SUBSCRIPTION_EXPIRATION_EMAIL_ENABLED_AT IS NOT NULL" in select_sql
    assert "SUBSCRIPTIONS.IS_TRIAL IS FALSE" in select_sql
    assert "SUBSCRIPTIONS.STATUS" in select_sql
    assert "EXTRACT(YEAR FROM SUBSCRIPTIONS.EXPIRE_AT)" in select_sql
    assert "NOT (EXISTS" in select_sql
    assert 500 in select_params.values()

    insert_sql, insert_params = _compile(session.scalars.await_args.args[0])
    assert "ON CONFLICT ON CONSTRAINT UQ_SUBSCRIPTION_EMAIL_REMINDER_IDENTITY" in insert_sql
    inserted_thresholds = {
        value
        for key, value in insert_params.items()
        if "days_before" in key.lower()
    }
    assert inserted_thresholds == {3, 1}


async def test_claim_due_sets_bounded_processing_lease_and_uses_skip_locked() -> None:
    reminder = SimpleNamespace(
        id=41,
        user_id=17,
        subscription_id=9,
        expire_at_snapshot=NOW + timedelta(days=1),
        days_before=1,
        due_at=NOW,
        state="PENDING",
        attempt_count=4,
        next_attempt_at=NOW,
        processing_token_hash=None,
        processing_lease_expires_at=None,
        last_error_code=None,
        sent_at=None,
        canceled_at=None,
        created_at=NOW,
        updated_at=NOW,
    )
    session = SimpleNamespace(
        scalars=AsyncMock(return_value=RowsResult([reminder])),
        flush=AsyncMock(),
    )
    dao = SubscriptionEmailReminderDaoImpl(session)  # type: ignore[arg-type]

    claimed = await dao.claim_due(
        now=NOW,
        delivery_not_before=NOW - timedelta(hours=1),
        token_hash="a" * 64,
        lease_for=timedelta(minutes=10),
        max_attempts=5,
        limit=1,
    )

    sql, params = _compile(session.scalars.await_args.args[0])
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert 1 in params.values()
    assert "SUBSCRIPTION_EMAIL_REMINDERS.ATTEMPT_COUNT <" in sql
    assert "SUBSCRIPTION_EMAIL_REMINDERS.DUE_AT >=" in sql
    assert reminder.state == PROCESSING
    assert reminder.processing_token_hash == "a" * 64
    assert reminder.processing_lease_expires_at == NOW + timedelta(minutes=10)
    assert reminder.attempt_count == 5
    assert claimed[0].attempt_count == 5
    session.flush.assert_awaited_once()


async def test_sweep_terminalizes_stale_and_crashed_exhausted_rows_boundedly() -> None:
    stale = SimpleNamespace(
        id=40,
        state="RETRY_WAITING",
        due_at=NOW - timedelta(hours=1, seconds=1),
        attempt_count=2,
        processing_token_hash=None,
        processing_lease_expires_at=None,
        canceled_at=None,
        last_error_code=None,
    )
    exhausted_after_crash = SimpleNamespace(
        id=41,
        state=PROCESSING,
        due_at=NOW - timedelta(minutes=10),
        attempt_count=5,
        processing_token_hash="a" * 64,
        processing_lease_expires_at=NOW - timedelta(seconds=1),
        canceled_at=None,
        last_error_code=None,
    )
    session = SimpleNamespace(
        scalars=AsyncMock(
            return_value=RowsResult([stale, exhausted_after_crash])
        ),
        flush=AsyncMock(),
    )
    dao = SubscriptionEmailReminderDaoImpl(session)  # type: ignore[arg-type]

    terminalized = await dao.sweep_undeliverable(
        now=NOW,
        delivery_not_before=NOW - timedelta(hours=1),
        max_attempts=5,
        limit=500,
    )

    assert terminalized == 2
    assert stale.state == CANCELED
    assert stale.canceled_at == NOW
    assert stale.last_error_code == "DELIVERY_WINDOW_EXPIRED"
    assert exhausted_after_crash.state == FAILED
    assert exhausted_after_crash.last_error_code == "ATTEMPTS_EXHAUSTED"
    assert exhausted_after_crash.processing_token_hash is None
    assert exhausted_after_crash.processing_lease_expires_at is None
    sql, params = _compile(session.scalars.await_args.args[0])
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "SUBSCRIPTION_EMAIL_REMINDERS.ATTEMPT_COUNT >=" in sql
    assert "SUBSCRIPTION_EMAIL_REMINDERS.DUE_AT <" in sql
    assert 500 in params.values()
    session.flush.assert_awaited_once()


async def test_lease_heartbeat_is_server_timed_and_fenced() -> None:
    session = SimpleNamespace(scalar=AsyncMock(return_value=41))
    dao = SubscriptionEmailReminderDaoImpl(session)  # type: ignore[arg-type]

    renewed = await dao.renew_processing_lease(
        41,
        token_hash="a" * 64,
        lease_for=timedelta(minutes=10),
    )

    assert renewed is True
    sql, params = _compile(session.scalar.await_args.args[0])
    assert "UPDATE SUBSCRIPTION_EMAIL_REMINDERS" in sql
    assert "SUBSCRIPTION_EMAIL_REMINDERS.STATE =" in sql
    assert "SUBSCRIPTION_EMAIL_REMINDERS.PROCESSING_TOKEN_HASH =" in sql
    assert "PROCESSING_LEASE_EXPIRES_AT > CLOCK_TIMESTAMP()" in sql
    assert "PROCESSING_LEASE_EXPIRES_AT=(CLOCK_TIMESTAMP() +" in sql
    assert PROCESSING in params.values()
    assert "a" * 64 in params.values()
    assert timedelta(minutes=10) in params.values()


def _delivery_record(
    *,
    enabled_at: datetime | None,
    due_at: datetime = NOW,
) -> tuple[SimpleNamespace, SimpleNamespace, SimpleNamespace]:
    reminder = SimpleNamespace(
        id=42,
        user_id=17,
        subscription_id=9,
        expire_at_snapshot=NOW + timedelta(days=3),
        days_before=3,
        due_at=due_at,
        state=PROCESSING,
        attempt_count=1,
        processing_token_hash="b" * 64,
        processing_lease_expires_at=NOW + timedelta(minutes=10),
        canceled_at=None,
        last_error_code=None,
    )
    user = SimpleNamespace(
        id=17,
        merged_into_user_id=None,
        is_blocked=False,
        email="user@example.org",
        is_email_verified=True,
        subscription_expiration_email_enabled=True,
        subscription_expiration_email_enabled_at=enabled_at,
        current_subscription_id=9,
    )
    subscription = SimpleNamespace(
        id=9,
        user_id=17,
        status=SubscriptionStatus.ACTIVE,
        is_trial=False,
        expire_at=NOW + timedelta(days=3),
    )
    return reminder, user, subscription


async def test_prepare_delivery_cancels_outbox_due_before_latest_opt_in() -> None:
    record = _delivery_record(enabled_at=NOW + timedelta(minutes=1))
    session = SimpleNamespace(
        execute=AsyncMock(return_value=OneResult(record)),
        flush=AsyncMock(),
    )
    dao = SubscriptionEmailReminderDaoImpl(session)  # type: ignore[arg-type]

    delivery = await dao.prepare_delivery(42, token_hash="b" * 64, now=NOW)

    assert delivery is None
    assert record[0].state == CANCELED
    assert record[0].last_error_code == "STALE_OR_INELIGIBLE"
    assert record[0].processing_token_hash is None
    session.flush.assert_awaited_once()


async def test_prepare_delivery_accepts_consent_that_predates_threshold() -> None:
    record = _delivery_record(enabled_at=NOW - timedelta(days=1))
    session = SimpleNamespace(
        execute=AsyncMock(return_value=OneResult(record)),
        flush=AsyncMock(),
    )
    dao = SubscriptionEmailReminderDaoImpl(session)  # type: ignore[arg-type]

    delivery = await dao.prepare_delivery(42, token_hash="b" * 64, now=NOW)

    assert delivery is not None
    assert delivery.reminder_id == 42
    assert delivery.recipient_email == "user@example.org"
    session.flush.assert_not_awaited()


async def test_retention_cleanup_is_bounded_to_old_terminal_states() -> None:
    session = SimpleNamespace(scalars=AsyncMock(return_value=RowsResult([1, 2])))
    dao = SubscriptionEmailReminderDaoImpl(session)  # type: ignore[arg-type]

    deleted = await dao.delete_terminal_before(
        before=NOW - timedelta(days=90),
        limit=500,
    )

    assert deleted == 2
    sql, params = _compile(session.scalars.await_args.args[0])
    assert "DELETE FROM SUBSCRIPTION_EMAIL_REMINDERS" in sql
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "STATE IN ('SENT', 'CANCELED', 'FAILED')" in sql
    assert "UPDATED_AT <" in sql
    assert "ORDER BY SUBSCRIPTION_EMAIL_REMINDERS.UPDATED_AT" in sql
    assert "SUBSCRIPTION_EMAIL_REMINDERS.ID" in sql
    assert 500 in params.values()
    state_values = set(params.values()) & {
        "SENT",
        "CANCELED",
        "FAILED",
        "PENDING",
        "PROCESSING",
        "RETRY_WAITING",
    }
    assert state_values == set()
