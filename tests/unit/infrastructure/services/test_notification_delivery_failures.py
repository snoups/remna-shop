from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.methods import SendMessage

from src.application.dto import MessagePayloadDto, TempUserDto
from src.infrastructure.services.notification import NotificationService


def _service_with_send_error(error: Exception) -> NotificationService:
    service = object.__new__(NotificationService)
    service.bot = SimpleNamespace(send_message=AsyncMock(side_effect=error))
    service._prepare_reply_markup = lambda *_: None
    service._get_translated_text = lambda **_: "test"
    return service


def _payload() -> MessagePayloadDto:
    return MessagePayloadDto(i18n_key="raw-message", delete_after=None)


def _user() -> TempUserDto:
    return TempUserDto(telegram_id=123, name="Test")


async def test_blocked_recipient_is_expected_delivery_failure() -> None:
    error = TelegramForbiddenError(
        SendMessage(chat_id=123, text="test"),
        "Forbidden: bot was blocked by the user",
    )
    service = _service_with_send_error(error)

    result = await service.notify_user(_user(), payload=_payload())

    assert result is None


async def test_missing_chat_is_expected_delivery_failure() -> None:
    error = TelegramBadRequest(
        SendMessage(chat_id=123, text="test"),
        "Bad Request: chat not found",
    )
    service = _service_with_send_error(error)

    result = await service.notify_user(_user(), payload=_payload())

    assert result is None


async def test_other_bad_request_remains_visible() -> None:
    error = TelegramBadRequest(
        SendMessage(chat_id=123, text="test"),
        "Bad Request: malformed entities",
    )
    service = _service_with_send_error(error)

    with pytest.raises(TelegramBadRequest):
        await service.notify_user(_user(), payload=_payload())
