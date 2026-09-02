from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.application.events import SubscriptionExpiresEvent
from src.application.events.user import SubscriptionExpiredAgoEvent
from src.application.services.remnawave import RemnaWebhookService


def _service() -> RemnaWebhookService:
    service = object.__new__(RemnaWebhookService)
    service.event_bus = SimpleNamespace(publish=AsyncMock())
    return service


@pytest.mark.parametrize(
    ("expiration_hours", "event_type", "day"),
    [
        (-72, SubscriptionExpiresEvent, 3),
        (-24, SubscriptionExpiresEvent, 1),
        (24, SubscriptionExpiredAgoEvent, 1),
    ],
)
async def test_unified_expiration_event_uses_top_level_metadata(
    expiration_hours: int,
    event_type: type,
    day: int,
) -> None:
    service = _service()
    expire_at = datetime(2026, 8, 23, tzinfo=UTC)
    user = SimpleNamespace(id=1)
    subscription = SimpleNamespace(expire_at=expire_at, is_trial=False)
    remna_user = SimpleNamespace(expire_at=expire_at, telegram_id=42)

    await service._process_expiration(
        user,
        subscription,
        remna_user,
        expiration_hours,
    )

    event = service.event_bus.publish.await_args.args[0]
    assert isinstance(event, event_type)
    assert event.day == day
    assert event.is_trial is False


async def test_unified_expiration_event_skips_missing_metadata() -> None:
    service = _service()
    expire_at = datetime(2026, 8, 23, tzinfo=UTC)

    await service._process_expiration(
        SimpleNamespace(id=1),
        SimpleNamespace(expire_at=expire_at, is_trial=False),
        SimpleNamespace(expire_at=expire_at, telegram_id=42),
        None,
    )

    service.event_bus.publish.assert_not_awaited()


async def test_unified_expiration_event_skips_stale_notice_after_renewal() -> None:
    service = _service()
    webhook_expire_at = datetime(2026, 8, 23, tzinfo=UTC)

    await service._process_expiration(
        SimpleNamespace(id=1),
        SimpleNamespace(
            expire_at=webhook_expire_at + timedelta(days=30),
            is_trial=False,
        ),
        SimpleNamespace(expire_at=webhook_expire_at, telegram_id=42),
        -24,
    )

    service.event_bus.publish.assert_not_awaited()
