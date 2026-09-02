import asyncio
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr, ValidationError

from src.application.dto import (
    SubscriptionEmailDeliveryDto,
    SubscriptionEmailReminderDto,
    UserDto,
)
from src.application.use_cases.notification import commands as notification_commands
from src.application.use_cases.notification.commands import (
    DELIVERY_GRACE,
    DELIVERY_LEASE,
    DELIVERY_MAX_ATTEMPTS,
    GENERATION_MAX_ROWS_PER_RUN,
    TERMINAL_CLEANUP_BATCH_SIZE,
    DeliverSubscriptionExpirationEmailReminders,
    GenerateSubscriptionExpirationEmailReminders,
    GetNotificationPreferences,
    NotificationDeliveryUnavailableError,
    NotificationEmailNotEligibleError,
    UpdateNotificationPreferences,
    UpdateNotificationPreferencesDto,
    _message_id,
)
from src.core.config.email import EmailConfig

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.active = False

    async def __aenter__(self) -> "FakeUnitOfWork":
        assert self.active is False
        self.active = True
        return self

    async def __aexit__(self, *args: object) -> None:
        self.active = False
        if args and args[0] is not None:
            await self.rollback()
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def _config(*, reminders_enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        crypt_key=SecretStr("test-message-id-secret"),
        email=SimpleNamespace(
            subscription_expiration_reminders_enabled=reminders_enabled,
            subscription_expiration_cabinet_url="https://cabinet.example.org/cabinet",
            from_email="notice@example.org",
        ),
    )


def _sender(*, enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(is_enabled=enabled, send=AsyncMock())


def _user(*, verified: bool = True, opted_in: bool = False) -> UserDto:
    return UserDto(
        id=17,
        name="User",
        email="user@example.org",
        is_email_verified=verified,
        subscription_expiration_email_enabled=opted_in,
        subscription_expiration_email_enabled_at=(
            NOW - timedelta(days=30) if opted_in else None
        ),
    )


def _preference_dao(user: UserDto) -> SimpleNamespace:
    def persist(
        user_id: int,
        *,
        enabled: bool,
    ) -> UserDto:
        assert user_id == user.id
        if enabled:
            if not user.subscription_expiration_email_enabled:
                # Production assigns this after the row lock with clock_timestamp().
                user.subscription_expiration_email_enabled_at = NOW
            user.subscription_expiration_email_enabled = True
        else:
            user.subscription_expiration_email_enabled = False
            user.subscription_expiration_email_enabled_at = None
        return user

    return SimpleNamespace(
        set_subscription_expiration_email_preference=AsyncMock(side_effect=persist)
    )


def test_reminder_cabinet_url_must_be_browser_safe_https() -> None:
    with pytest.raises(ValidationError):
        EmailConfig(subscription_expiration_cabinet_url="http://cabinet.example.org")

    config = EmailConfig(
        subscription_expiration_cabinet_url="  https://cabinet.example.org/cabinet  "
    )
    assert (
        config.subscription_expiration_cabinet_url
        == "https://cabinet.example.org/cabinet"
    )


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "https:///cabinet",
        "https://?next=/cabinet",
        "https://user@cabinet.example.org/cabinet",
        "https://user:password@cabinet.example.org/cabinet",
        "https://cabinet.example.org:99999/cabinet",
    ],
)
def test_reminder_cabinet_url_requires_host_and_rejects_userinfo(
    unsafe_url: str,
) -> None:
    with pytest.raises(ValidationError, match="hostname.*without userinfo"):
        EmailConfig(subscription_expiration_cabinet_url=unsafe_url)


async def test_preferences_keep_stored_consent_visible_when_delivery_is_unavailable() -> None:
    user = _user(opted_in=True)
    use_case = GetNotificationPreferences(
        _config(reminders_enabled=False),  # type: ignore[arg-type]
        _sender(),  # type: ignore[arg-type]
    )

    result = await use_case(user)

    assert result.subscription_expiration_email_enabled is True
    assert result.email_eligible is False
    assert result.sender_email == "notice@example.org"
    assert result.days_before == (7, 3, 1)


async def test_stored_opt_in_can_be_disabled_during_delivery_outage() -> None:
    user = _user(opted_in=True)
    user_dao = _preference_dao(user)
    uow = FakeUnitOfWork()
    use_case = UpdateNotificationPreferences(
        _config(reminders_enabled=False),  # type: ignore[arg-type]
        _sender(),  # type: ignore[arg-type]
        user_dao,  # type: ignore[arg-type]
        uow,  # type: ignore[arg-type]
    )

    result = await use_case(
        user,
        UpdateNotificationPreferencesDto(
            subscription_expiration_email_enabled=False
        ),
    )

    assert result.subscription_expiration_email_enabled is False
    assert result.email_eligible is False
    assert user.subscription_expiration_email_enabled_at is None
    assert uow.commits == 1


async def test_enabling_requires_verified_email_and_ready_delivery() -> None:
    user_dao = SimpleNamespace(
        set_subscription_expiration_email_preference=AsyncMock()
    )
    uow = FakeUnitOfWork()
    use_case = UpdateNotificationPreferences(
        _config(),  # type: ignore[arg-type]
        _sender(),  # type: ignore[arg-type]
        user_dao,  # type: ignore[arg-type]
        uow,  # type: ignore[arg-type]
    )

    with pytest.raises(NotificationEmailNotEligibleError):
        await use_case(
            _user(verified=False),
            UpdateNotificationPreferencesDto(
                subscription_expiration_email_enabled=True
            ),
        )

    unavailable = UpdateNotificationPreferences(
        _config(reminders_enabled=False),  # type: ignore[arg-type]
        _sender(),  # type: ignore[arg-type]
        user_dao,  # type: ignore[arg-type]
        uow,  # type: ignore[arg-type]
    )
    with pytest.raises(NotificationDeliveryUnavailableError):
        await unavailable(
            _user(),
            UpdateNotificationPreferencesDto(
                subscription_expiration_email_enabled=True
            ),
        )

    user_dao.set_subscription_expiration_email_preference.assert_not_awaited()


async def test_enabling_persists_explicit_consent_timestamp() -> None:
    user = _user()
    user_dao = _preference_dao(user)
    uow = FakeUnitOfWork()
    use_case = UpdateNotificationPreferences(
        _config(),  # type: ignore[arg-type]
        _sender(),  # type: ignore[arg-type]
        user_dao,  # type: ignore[arg-type]
        uow,  # type: ignore[arg-type]
    )

    result = await use_case(
        user,
        UpdateNotificationPreferencesDto(subscription_expiration_email_enabled=True),
    )

    assert result.subscription_expiration_email_enabled is True
    assert user.subscription_expiration_email_enabled is True
    assert user.subscription_expiration_email_enabled_at is not None
    assert uow.commits == 1


async def test_repeated_enable_preserves_original_consent_timestamp() -> None:
    user = _user(opted_in=True)
    original_enabled_at = user.subscription_expiration_email_enabled_at
    user_dao = _preference_dao(user)
    use_case = UpdateNotificationPreferences(
        _config(),  # type: ignore[arg-type]
        _sender(),  # type: ignore[arg-type]
        user_dao,  # type: ignore[arg-type]
        FakeUnitOfWork(),  # type: ignore[arg-type]
    )

    result = await use_case(
        user,
        UpdateNotificationPreferencesDto(subscription_expiration_email_enabled=True),
    )

    assert result.subscription_expiration_email_enabled is True
    assert user.subscription_expiration_email_enabled_at == original_enabled_at
    user_dao.set_subscription_expiration_email_preference.assert_awaited_once_with(
        user.id,
        enabled=True,
    )


async def test_atomic_enable_rejects_stale_profile_after_email_change() -> None:
    stale_user = _user(verified=True)
    user_dao = SimpleNamespace(
        set_subscription_expiration_email_preference=AsyncMock(return_value=None)
    )
    uow = FakeUnitOfWork()
    use_case = UpdateNotificationPreferences(
        _config(),  # type: ignore[arg-type]
        _sender(),  # type: ignore[arg-type]
        user_dao,  # type: ignore[arg-type]
        uow,  # type: ignore[arg-type]
    )

    with pytest.raises(NotificationEmailNotEligibleError):
        await use_case(
            stale_user,
            UpdateNotificationPreferencesDto(
                subscription_expiration_email_enabled=True
            ),
        )

    user_dao.set_subscription_expiration_email_preference.assert_awaited_once()
    assert stale_user.subscription_expiration_email_enabled is False
    assert uow.commits == 0


async def test_generation_uses_paid_subscription_thresholds_and_bounded_batch() -> None:
    reminder_dao = SimpleNamespace(
        generate=AsyncMock(return_value=3),
        delete_terminal_before=AsyncMock(return_value=0),
    )
    use_case = GenerateSubscriptionExpirationEmailReminders(
        _config(),  # type: ignore[arg-type]
        _sender(),  # type: ignore[arg-type]
        reminder_dao,  # type: ignore[arg-type]
        FakeUnitOfWork(),  # type: ignore[arg-type]
    )

    assert await use_case.system() == 3

    kwargs = reminder_dao.generate.await_args.kwargs
    assert kwargs["days_before"] == (7, 3, 1)
    assert kwargs["candidate_limit"] == 500
    assert kwargs["generation_grace"] == timedelta(hours=1)
    cleanup = reminder_dao.delete_terminal_before.await_args.kwargs
    assert GENERATION_MAX_ROWS_PER_RUN == 500 * 3
    assert cleanup["limit"] == TERMINAL_CLEANUP_BATCH_SIZE
    assert cleanup["limit"] > GENERATION_MAX_ROWS_PER_RUN


async def test_terminal_cleanup_still_runs_while_delivery_is_disabled() -> None:
    reminder_dao = SimpleNamespace(
        generate=AsyncMock(),
        delete_terminal_before=AsyncMock(return_value=2),
    )
    use_case = GenerateSubscriptionExpirationEmailReminders(
        _config(reminders_enabled=False),  # type: ignore[arg-type]
        _sender(),  # type: ignore[arg-type]
        reminder_dao,  # type: ignore[arg-type]
        FakeUnitOfWork(),  # type: ignore[arg-type]
    )

    assert await use_case.system() == 0
    reminder_dao.generate.assert_not_awaited()
    cleanup = reminder_dao.delete_terminal_before.await_args.kwargs
    assert cleanup["limit"] == TERMINAL_CLEANUP_BATCH_SIZE
    assert cleanup["limit"] > GENERATION_MAX_ROWS_PER_RUN


def _claimed_reminder() -> SubscriptionEmailReminderDto:
    return SubscriptionEmailReminderDto(
        id=42,
        user_id=17,
        subscription_id=9,
        expire_at_snapshot=NOW + timedelta(days=3),
        days_before=3,
        due_at=NOW,
        state="PROCESSING",
        attempt_count=1,
        next_attempt_at=NOW,
    )


async def test_delivery_uses_stable_message_id_and_required_russian_copy() -> None:
    delivery = SubscriptionEmailDeliveryDto(
        reminder_id=42,
        recipient_email="user@example.org",
        expire_at=NOW + timedelta(days=3),
        days_before=3,
        attempt_count=1,
    )
    reminder_dao = SimpleNamespace(
        sweep_undeliverable=AsyncMock(return_value=0),
        claim_due=AsyncMock(side_effect=[[_claimed_reminder()], []]),
        prepare_delivery=AsyncMock(return_value=delivery),
        mark_sent=AsyncMock(return_value=True),
        release_failed=AsyncMock(),
    )
    sender = _sender()
    uow = FakeUnitOfWork()

    async def assert_no_open_transaction(**kwargs: object) -> None:
        assert kwargs
        assert uow.active is False
        assert uow.commits == 3

    sender.send.side_effect = assert_no_open_transaction
    use_case = DeliverSubscriptionExpirationEmailReminders(
        _config(),  # type: ignore[arg-type]
        sender,  # type: ignore[arg-type]
        reminder_dao,  # type: ignore[arg-type]
        uow,  # type: ignore[arg-type]
    )

    assert await use_case.system() == 1

    send = sender.send.await_args.kwargs
    assert send["to"] == "user@example.org"
    message_id = send["message_id"]
    assert message_id == _message_id(
        42,
        "notice@example.org",
        "test-message-id-secret",
    )
    assert "subscription-expiration-42@" not in message_id
    assert "автопродление не выполняется" in send["body"]
    assert "Если вы уже продлили подписку" in send["body"]
    assert "белый список" in send["body"]
    assert "https://cabinet.example.org/cabinet" in send["body"]
    assert uow.commits == 5
    claim = reminder_dao.claim_due.await_args_list[0].kwargs
    assert claim["limit"] == 1
    assert claim["max_attempts"] == DELIVERY_MAX_ATTEMPTS
    assert claim["lease_for"] == DELIVERY_LEASE
    assert claim["now"] - claim["delivery_not_before"] == DELIVERY_GRACE
    reminder_dao.release_failed.assert_not_awaited()


def test_message_id_is_stable_opaque_and_domain_scoped() -> None:
    first = _message_id(42, "notice@example.org", "test-message-id-secret")
    repeated = _message_id(42, "notice@example.org", "test-message-id-secret")
    different_row = _message_id(43, "notice@example.org", "test-message-id-secret")

    assert first == repeated
    assert first != different_row
    assert re.fullmatch(
        r"<subscription-expiration-[0-9a-f]{64}@example\.org>",
        first,
    )
    assert "subscription-expiration-42@" not in first


async def test_delivery_failure_is_retried_with_safe_non_pii_error_code() -> None:
    delivery = SubscriptionEmailDeliveryDto(
        reminder_id=42,
        recipient_email="user@example.org",
        expire_at=NOW + timedelta(days=3),
        days_before=3,
        attempt_count=2,
    )
    reminder_dao = SimpleNamespace(
        sweep_undeliverable=AsyncMock(return_value=0),
        claim_due=AsyncMock(side_effect=[[_claimed_reminder()], []]),
        prepare_delivery=AsyncMock(return_value=delivery),
        mark_sent=AsyncMock(),
        release_failed=AsyncMock(return_value=True),
    )
    sender = _sender()
    sender.send.side_effect = RuntimeError("private user@example.org SMTP detail")
    use_case = DeliverSubscriptionExpirationEmailReminders(
        _config(),  # type: ignore[arg-type]
        sender,  # type: ignore[arg-type]
        reminder_dao,  # type: ignore[arg-type]
        FakeUnitOfWork(),  # type: ignore[arg-type]
    )

    assert await use_case.system() == 0

    retry = reminder_dao.release_failed.await_args.kwargs
    assert retry["error_code"] == "EMAIL_RUNTIMEERROR"
    assert "user@example.org" not in retry["error_code"]
    assert retry["retry_after"] == timedelta(minutes=2)
    reminder_dao.mark_sent.assert_not_awaited()


async def test_long_running_delivery_renews_fenced_lease_before_finalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        notification_commands,
        "DELIVERY_HEARTBEAT_INTERVAL",
        timedelta(milliseconds=1),
    )
    delivery = SubscriptionEmailDeliveryDto(
        reminder_id=42,
        recipient_email="user@example.org",
        expire_at=NOW + timedelta(days=3),
        days_before=3,
        attempt_count=1,
    )
    lease_renewed = asyncio.Event()
    renewal_in_progress = False
    uow = FakeUnitOfWork()

    async def renew_lease(*args: object, **kwargs: object) -> bool:
        nonlocal renewal_in_progress
        assert args == (42,)
        assert kwargs["lease_for"] == DELIVERY_LEASE
        assert uow.active is True
        renewal_in_progress = True
        await asyncio.sleep(0)
        renewal_in_progress = False
        lease_renewed.set()
        return True

    async def wait_for_renewal(**kwargs: object) -> None:
        assert kwargs
        await lease_renewed.wait()

    async def mark_sent(*args: object, **kwargs: object) -> bool:
        assert args == (42,)
        assert kwargs
        assert lease_renewed.is_set()
        assert renewal_in_progress is False
        return True

    reminder_dao = SimpleNamespace(
        sweep_undeliverable=AsyncMock(return_value=0),
        claim_due=AsyncMock(side_effect=[[_claimed_reminder()], []]),
        prepare_delivery=AsyncMock(return_value=delivery),
        renew_processing_lease=AsyncMock(side_effect=renew_lease),
        mark_sent=AsyncMock(side_effect=mark_sent),
        release_failed=AsyncMock(),
    )
    sender = _sender()
    sender.send.side_effect = wait_for_renewal
    use_case = DeliverSubscriptionExpirationEmailReminders(
        _config(),  # type: ignore[arg-type]
        sender,  # type: ignore[arg-type]
        reminder_dao,  # type: ignore[arg-type]
        uow,  # type: ignore[arg-type]
    )

    assert await use_case.system() == 1

    assert reminder_dao.renew_processing_lease.await_count >= 1
    reminder_dao.mark_sent.assert_awaited_once()
    reminder_dao.release_failed.assert_not_awaited()


async def test_delivery_does_not_finalize_after_heartbeat_loses_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        notification_commands,
        "DELIVERY_HEARTBEAT_INTERVAL",
        timedelta(milliseconds=1),
    )
    delivery = SubscriptionEmailDeliveryDto(
        reminder_id=42,
        recipient_email="user@example.org",
        expire_at=NOW + timedelta(days=3),
        days_before=3,
        attempt_count=1,
    )
    renewal_attempted = asyncio.Event()

    async def lose_fence(*args: object, **kwargs: object) -> bool:
        assert args == (42,)
        assert kwargs
        renewal_attempted.set()
        return False

    async def finish_after_heartbeat(**kwargs: object) -> None:
        assert kwargs
        await renewal_attempted.wait()

    reminder_dao = SimpleNamespace(
        sweep_undeliverable=AsyncMock(return_value=0),
        claim_due=AsyncMock(side_effect=[[_claimed_reminder()], []]),
        prepare_delivery=AsyncMock(return_value=delivery),
        renew_processing_lease=AsyncMock(side_effect=lose_fence),
        mark_sent=AsyncMock(),
        release_failed=AsyncMock(),
    )
    sender = _sender()
    sender.send.side_effect = finish_after_heartbeat
    use_case = DeliverSubscriptionExpirationEmailReminders(
        _config(),  # type: ignore[arg-type]
        sender,  # type: ignore[arg-type]
        reminder_dao,  # type: ignore[arg-type]
        FakeUnitOfWork(),  # type: ignore[arg-type]
    )

    assert await use_case.system() == 0

    reminder_dao.renew_processing_lease.assert_awaited_once()
    reminder_dao.mark_sent.assert_not_awaited()
    reminder_dao.release_failed.assert_not_awaited()


async def test_delivery_heartbeat_retries_safe_transient_database_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        notification_commands,
        "DELIVERY_HEARTBEAT_INTERVAL",
        timedelta(milliseconds=1),
    )
    delivery = SubscriptionEmailDeliveryDto(
        reminder_id=42,
        recipient_email="user@example.org",
        expire_at=NOW + timedelta(days=3),
        days_before=3,
        attempt_count=1,
    )
    lease_renewed = asyncio.Event()
    renewal_attempts = 0

    async def transient_then_renew(*args: object, **kwargs: object) -> bool:
        nonlocal renewal_attempts
        assert args == (42,)
        assert kwargs
        renewal_attempts += 1
        if renewal_attempts == 1:
            raise RuntimeError("private user@example.org database detail")
        lease_renewed.set()
        return True

    async def finish_after_renewal(**kwargs: object) -> None:
        assert kwargs
        await lease_renewed.wait()

    reminder_dao = SimpleNamespace(
        sweep_undeliverable=AsyncMock(return_value=0),
        claim_due=AsyncMock(side_effect=[[_claimed_reminder()], []]),
        prepare_delivery=AsyncMock(return_value=delivery),
        renew_processing_lease=AsyncMock(side_effect=transient_then_renew),
        mark_sent=AsyncMock(return_value=True),
        release_failed=AsyncMock(),
    )
    sender = _sender()
    sender.send.side_effect = finish_after_renewal
    uow = FakeUnitOfWork()
    use_case = DeliverSubscriptionExpirationEmailReminders(
        _config(),  # type: ignore[arg-type]
        sender,  # type: ignore[arg-type]
        reminder_dao,  # type: ignore[arg-type]
        uow,  # type: ignore[arg-type]
    )

    assert await use_case.system() == 1

    assert reminder_dao.renew_processing_lease.await_count >= 2
    assert uow.rollbacks == 1
    reminder_dao.mark_sent.assert_awaited_once()


async def test_delivery_maintenance_runs_fail_closed_when_sending_is_disabled() -> None:
    reminder_dao = SimpleNamespace(
        sweep_undeliverable=AsyncMock(return_value=4),
        claim_due=AsyncMock(),
    )
    sender = _sender()
    use_case = DeliverSubscriptionExpirationEmailReminders(
        _config(reminders_enabled=False),  # type: ignore[arg-type]
        sender,  # type: ignore[arg-type]
        reminder_dao,  # type: ignore[arg-type]
        FakeUnitOfWork(),  # type: ignore[arg-type]
    )

    assert await use_case.system() == 0

    sweep = reminder_dao.sweep_undeliverable.await_args.kwargs
    assert sweep["now"] - sweep["delivery_not_before"] == DELIVERY_GRACE
    assert sweep["max_attempts"] == DELIVERY_MAX_ATTEMPTS
    assert sweep["limit"] == 500
    reminder_dao.claim_due.assert_not_awaited()
    sender.send.assert_not_awaited()
