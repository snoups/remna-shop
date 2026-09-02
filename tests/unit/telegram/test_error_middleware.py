from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.types import User as AiogramUser
from aiogram_dialog.api.exceptions import UnknownIntent

from src.application.common import BotService, EventPublisher, Notifier
from src.application.common.dao import UserDao
from src.application.use_cases.misc.commands.navigation import RedirectMenu
from src.core.constants import CONFIG_KEY, CONTAINER_KEY
from src.telegram.middlewares.error import ErrorMiddleware


async def test_stale_dialog_context_is_recovered_without_rethrowing() -> None:
    bot_service = SimpleNamespace(get_support_url=lambda: "https://example.com/support")
    event_publisher = SimpleNamespace(publish=AsyncMock())
    notifier = SimpleNamespace(notify_user=AsyncMock())
    redirect_menu = SimpleNamespace(system=AsyncMock())
    user_dao = SimpleNamespace(
        get_by_telegram_id=AsyncMock(
            return_value=SimpleNamespace(is_privileged=False)
        )
    )
    dependencies = {
        BotService: bot_service,
        EventPublisher: event_publisher,
        Notifier: notifier,
        RedirectMenu: redirect_menu,
        UserDao: user_dao,
    }
    container = SimpleNamespace(
        get=AsyncMock(side_effect=lambda dependency: dependencies[dependency])
    )
    aiogram_user = AiogramUser(id=123, is_bot=False, first_name="Test")
    event = SimpleNamespace(
        exception=UnknownIntent("Context not found for intent id: stale"),
        update=SimpleNamespace(message=None),
    )
    handler = AsyncMock()

    result = await ErrorMiddleware().middleware_logic(
        handler,
        event,
        {
            CONFIG_KEY: SimpleNamespace(build=SimpleNamespace(data={})),
            CONTAINER_KEY: container,
            "event_from_user": aiogram_user,
        },
    )

    assert result is None
    handler.assert_not_awaited()
    redirect_menu.system.assert_awaited_once_with(aiogram_user.id)
    notifier.notify_user.assert_awaited_once()
    event_publisher.publish.assert_not_awaited()
