from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.application.services.remnawave import RemnaUserEvent, RemnaWebhookService


async def test_traffic_reset_is_acknowledged_without_local_mutation() -> None:
    service = object.__new__(RemnaWebhookService)
    service.user_dao = SimpleNamespace(get_by_remna_uuid=AsyncMock())
    service.subscription_dao = SimpleNamespace(get_current=AsyncMock())
    service.sync_user = SimpleNamespace(system=AsyncMock())

    await service.handle_user_event(
        RemnaUserEvent.TRAFFIC_RESET,
        SimpleNamespace(telegram_id=42, uuid="uuid"),
    )

    service.user_dao.get_by_remna_uuid.assert_not_awaited()
    service.subscription_dao.get_current.assert_not_awaited()
    service.sync_user.system.assert_not_awaited()
