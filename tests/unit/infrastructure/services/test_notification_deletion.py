from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import DeleteMessage, EditMessageReplyMarkup

from src.infrastructure.services.notification import NotificationService


def _service() -> NotificationService:
    service = object.__new__(NotificationService)
    service.bot = SimpleNamespace(
        delete_message=AsyncMock(),
        edit_message_reply_markup=AsyncMock(),
    )
    return service


async def test_old_notification_falls_back_to_clearing_keyboard() -> None:
    service = _service()
    service.bot.delete_message.side_effect = TelegramBadRequest(
        DeleteMessage(chat_id=1, message_id=2),
        "Bad Request: message can't be deleted for everyone",
    )

    await service.delete_notification(chat_id=1, message_id=2)

    service.bot.edit_message_reply_markup.assert_awaited_once_with(
        chat_id=1,
        message_id=2,
        reply_markup=None,
    )


async def test_already_deleted_notification_is_idempotent() -> None:
    service = _service()
    service.bot.delete_message.side_effect = TelegramBadRequest(
        DeleteMessage(chat_id=1, message_id=2),
        "Bad Request: message to delete not found",
    )

    await service.delete_notification(chat_id=1, message_id=2)

    service.bot.edit_message_reply_markup.assert_not_awaited()


async def test_already_cleared_keyboard_is_idempotent() -> None:
    service = _service()
    service.bot.edit_message_reply_markup.side_effect = TelegramBadRequest(
        EditMessageReplyMarkup(chat_id=1, message_id=2),
        "Bad Request: message is not modified",
    )

    await service._clear_reply_markup(chat_id=1, message_id=2)
