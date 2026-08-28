import asyncio
import base64
import string
import traceback
from dataclasses import asdict
from typing import Any, Callable, Optional, Sequence, Union

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramMigrateToChat,
    TelegramNotFound,
    TelegramUnauthorizedError,
)
from aiogram.types import (
    BufferedInputFile,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardMarkup,
)
from aiogram.utils.formatting import Text
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger

from src.application.common import EventPublisher, Notifier, TranslatorHub
from src.application.common.dao import SettingsDao, UserDao
from src.application.dto import (
    MediaDescriptorDto,
    MessagePayloadDto,
    NotificationTaskDto,
    SettingsDto,
    SystemNotificationRouteDto,
    TempUserDto,
    UserDto,
)
from src.application.events import ErrorEvent, NotificationErrorEvent, SystemEvent
from src.application.events.base import BaseEvent, UserEvent
from src.application.events.system import (
    BlacklistRegistrationAttemptEvent,
    BotUpdateEvent,
    PromocodeActivatedEvent,
    RemnashopWelcomeEvent,
    SubscriptionRevokedEvent,
    TorrentBlockerReportEvent,
    TrialActivatedEvent,
    UserAllDevicesDeletedEvent,
    UserDevicesUpdatedEvent,
    UserFirstConnectionEvent,
    UserPurchaseEvent,
    UserRegisteredEvent,
)
from src.application.events.user import (
    GraceActivatedEvent,
    SubscriptionExpiredAgoEvent,
    SubscriptionExpiredEvent,
    SubscriptionExpiresEvent,
    SubscriptionLimitedEvent,
    TorrentBlockedEvent,
    UserNotConnectedEvent,
)
from src.core.config import AppConfig
from src.core.enums import Locale, Role
from src.core.types import AnyKeyboard, NotificationType
from src.infrastructure.services.event_bus import on_event
from src.infrastructure.services.notification_queue import NotificationWorker
from src.telegram.keyboards import (
    get_buy_keyboard,
    get_close_notification_button,
    get_contact_support_keyboard,
    get_remnashop_keyboard,
    get_remnashop_update_keyboard,
    get_renew_keyboard,
    get_user_keyboard,
)
from src.telegram.widgets import extract_color, extract_tg_emoji


class NotificationService(Notifier):
    def __init__(
        self,
        bot: Bot,
        config: AppConfig,
        translator_hub: TranslatorHub,
        user_dao: UserDao,
        settings_dao: SettingsDao,
        worker: NotificationWorker,
        event_publisher: EventPublisher,
    ) -> None:
        self.bot = bot
        self.config = config
        self.translator_hub = translator_hub
        self.user_dao = user_dao
        self.settings_dao = settings_dao
        self.worker = worker
        self.event_publisher = event_publisher

    async def notify_user(
        self,
        user: Union[TempUserDto, UserDto],
        payload: Optional[MessagePayloadDto] = None,
        i18n_key: Optional[str] = None,
    ) -> Optional[Message]:
        if not payload and i18n_key:
            payload = MessagePayloadDto(i18n_key=i18n_key)

        if not payload:
            raise ValueError(
                f"Failed to notify user '{user.telegram_id}' because no payload or key provided"
            )

        return await self._send_message(user, payload)

    async def notify_admins(
        self,
        payload: MessagePayloadDto,
        roles: list[Role] = [Role.OWNER, Role.DEV, Role.ADMIN],
    ) -> None:
        await self.worker.enqueue(NotificationTaskDto(payload=payload, roles=roles))

    def _resolve_keyboard(self, event: "BaseEvent") -> "Optional[AnyKeyboard]":
        if isinstance(
            event,
            (
                SubscriptionLimitedEvent,
                SubscriptionExpiredEvent,
                SubscriptionExpiredAgoEvent,
                SubscriptionExpiresEvent,
                GraceActivatedEvent,
            ),
        ):
            return get_buy_keyboard() if event.is_trial else get_renew_keyboard()
        if isinstance(event, UserNotConnectedEvent):
            return get_contact_support_keyboard(event.support_url)
        if isinstance(event, TorrentBlockedEvent):
            return get_contact_support_keyboard(event.support_url)
        if isinstance(event, TorrentBlockerReportEvent):
            return get_user_keyboard(event.user_id)
        if isinstance(event, RemnashopWelcomeEvent):
            return get_remnashop_keyboard()
        if isinstance(event, BotUpdateEvent):
            return get_remnashop_update_keyboard()
        if isinstance(event, UserRegisteredEvent):
            return get_user_keyboard(event.user_id, event.referrer_user_id)
        if isinstance(event, BlacklistRegistrationAttemptEvent):
            return get_user_keyboard(event.user_id)
        if isinstance(
            event,
            (
                UserFirstConnectionEvent,
                UserDevicesUpdatedEvent,
                UserAllDevicesDeletedEvent,
                UserPurchaseEvent,
                TrialActivatedEvent,
                SubscriptionRevokedEvent,
                PromocodeActivatedEvent,
            ),
        ):
            return get_user_keyboard(event.user_id)
        return None

    @on_event(RemnashopWelcomeEvent)
    async def on_remnashop_welcome_event(self, event: RemnashopWelcomeEvent) -> None:
        logger.info(f"Received '{event.event_type}' event")
        payload = event.as_payload()
        payload.reply_markup = self._resolve_keyboard(event)
        await self.notify_admins(payload, roles=[Role.OWNER, Role.DEV])

    @on_event(NotificationErrorEvent)
    async def on_notification_error_event(self, event: NotificationErrorEvent) -> None:
        logger.info(f"Received '{event.event_type}' event")
        await self.notify_admins(event.as_payload(), roles=[Role.OWNER, Role.DEV])

    @on_event(UserEvent)
    async def on_user_event(self, event: UserEvent) -> None:
        logger.info(f"Received '{event.event_type}' event")

        settings: SettingsDto = await self.settings_dao.get()
        if not settings.notifications.is_enabled(event.notification_type):
            logger.info(f"Notification for '{event.notification_type}' is disabled, skipping")
            return

        payload = event.as_payload()
        payload.reply_markup = self._resolve_keyboard(event)
        await self.notify_user(event.user, payload)

    @on_event(SystemEvent)
    async def on_system_event(self, event: SystemEvent) -> None:
        logger.info(f"Received '{event.event_type}' event")

        if isinstance(event, NotificationErrorEvent):
            return

        settings: SettingsDto = await self.settings_dao.get()
        if not settings.notifications.is_enabled(event.notification_type):
            logger.info(f"Notification for '{event.notification_type}' is disabled, skipping")
            return

        payload = event.as_payload()
        payload.reply_markup = self._resolve_keyboard(event)
        await self.notify_system(payload, notification_type=event.notification_type)

    @on_event(ErrorEvent)
    async def on_error_event(self, event: ErrorEvent) -> None:
        logger.info(f"Received '{event.event_type}' event")

        error_type = type(event.exception).__name__
        error_message = Text(str(event.exception)[:512])

        traceback_str = "".join(
            traceback.format_exception(
                type(event.exception),
                event.exception,
                event.exception.__traceback__,
            )
        )

        from src.core.logger import log_buffer  # noqa: PLC0415

        log_context = log_buffer.get_context()
        file_content = (
            "=== LOG CONTEXT (last 100 lines) ===\n\n"
            f"{log_context}\n\n"
            "=== EXCEPTION ===\n\n"
            f"{traceback_str}"
        )

        media = MediaDescriptorDto(
            kind="bytes",
            value=base64.b64encode(file_content.encode("utf-8")).decode(),
            filename=f"error_{event.event_id}.txt",
        )

        await self.notify_system(
            event.as_payload(media, error_type, error_message),
            roles=[Role.OWNER, Role.DEV],
            notification_type=event.notification_type,
        )

    async def notify_system(
        self,
        payload: MessagePayloadDto,
        roles: list[Role] = [Role.OWNER, Role.DEV, Role.ADMIN],
        notification_type: Optional[NotificationType] = None,
    ) -> None:
        route = None
        if notification_type:
            settings: SettingsDto = await self.settings_dao.get()
            route = settings.notifications.resolve_route(notification_type)

        if route and route.is_configured:
            await self._send_to_route(payload, route)
        else:
            await self.notify_admins(payload, roles=roles)

    async def _send_to_route(
        self,
        payload: MessagePayloadDto,
        route: SystemNotificationRouteDto,
    ) -> None:
        chat_id = route.chat_id
        thread_id = route.effective_thread_id

        locale = self.config.default_locale
        text = self._get_translated_text(
            locale=locale,
            i18n_key=payload.i18n_key,
            i18n_kwargs=payload.i18n_kwargs,
        )

        reply_markup = (
            self._translate_keyboard_text(payload.reply_markup, locale)
            if payload.reply_markup is not None
            else None
        )

        try:
            if payload.is_text:
                await self.bot.send_message(
                    chat_id=chat_id,  # type:ignore[arg-type]
                    text=text,
                    message_thread_id=thread_id,
                    disable_web_page_preview=True,
                    disable_notification=payload.disable_notification,
                    reply_markup=reply_markup,
                )
            elif payload.media:
                method = self._get_media_method(payload)
                if not method:
                    logger.warning(f"Unknown media type for payload '{payload}'")
                    return
                media = self._build_media(payload.media)
                await method(
                    chat_id,
                    media,
                    caption=text,
                    message_thread_id=thread_id,
                    disable_notification=payload.disable_notification,
                    reply_markup=reply_markup,
                )
            else:
                logger.error(f"Payload must contain text or media for route {chat_id}:{thread_id}")

        except (
            TelegramForbiddenError,
            TelegramBadRequest,
            TelegramNotFound,
            TelegramMigrateToChat,
            TelegramUnauthorizedError,
        ) as e:
            logger.error(f"Failed to send system notification to route {chat_id}:{thread_id}: {e}")
            await self.event_publisher.publish(
                NotificationErrorEvent(
                    chat_id=chat_id,
                    thread_id=thread_id,
                    reason=str(e),
                )
            )

    async def delete_notification(self, chat_id: int, message_id: int) -> None:
        try:
            await self.bot.delete_message(chat_id=chat_id, message_id=message_id)
            logger.debug(f"Notification '{message_id}' for chat '{chat_id}' deleted")
        except Exception as e:
            logger.error(f"Failed to delete notification '{message_id}': {e}")
            await self._clear_reply_markup(chat_id, message_id)

    async def _process_task(self, task: NotificationTaskDto) -> None:
        users = await self.user_dao.filter_by_role(task.roles)

        if not users:
            temp_owner = [TempUserDto.as_temp_owner(telegram_id=self.config.bot.owner_id)]

        await self._broadcast(users or temp_owner, task.payload)

    async def _broadcast(
        self,
        users: Sequence[Union[TempUserDto, UserDto]],
        payload: MessagePayloadDto,
    ) -> None:
        logger.debug(f"Starting broadcast to '{len(users)}' users")

        results = await asyncio.gather(
            *(self._send_message(user, payload) for user in users),
            return_exceptions=True,
        )

        for user, result in zip(users, results):
            if isinstance(result, Exception):
                logger.error(f"Broadcast failed for user {user.log}: {result}")

    async def _send_message(
        self,
        user: Union[TempUserDto, UserDto],
        payload: MessagePayloadDto,
    ) -> Optional[Message]:
        if user.telegram_id is None:
            logger.debug(f"Skipping notification for web-only user {user.log}")
            return None

        render_kwargs = payload.i18n_kwargs.copy()

        if isinstance(user, UserDto) and payload.i18n_key == "raw-message":
            user_data = asdict(user)
            render_kwargs = {**user_data, **payload.i18n_kwargs}

        reply_markup = self._prepare_reply_markup(
            payload.reply_markup,
            payload.disable_default_markup,
            payload.delete_after,
            user.language,
            user.telegram_id,
        )

        text = self._get_translated_text(
            locale=user.language,
            i18n_key=payload.i18n_key,
            i18n_kwargs=render_kwargs,
        )

        kwargs: dict[str, Any] = {
            "disable_notification": payload.disable_notification,
            "message_effect_id": payload.message_effect,
            "reply_markup": reply_markup,
        }

        try:
            if payload.is_text:
                message = await self.bot.send_message(
                    chat_id=user.telegram_id,
                    text=text,
                    disable_web_page_preview=True,
                    **kwargs,
                )
            elif payload.media:
                method = self._get_media_method(payload)
                media = self._build_media(payload.media)

                if not method:
                    logger.warning(f"Unknown media type for payload '{payload}'")
                    return None

                message = await method(user.telegram_id, media, caption=text, **kwargs)
            else:
                logger.error(f"Payload must contain text or media for user {user.log}")
                return None

            if message and payload.delete_after:
                asyncio.create_task(
                    self._schedule_message_deletion(
                        chat_id=user.telegram_id,
                        message_id=message.message_id,
                        delay=payload.delete_after,
                    )
                )

            return message

        except TelegramForbiddenError:
            logger.warning(f"Bot was blocked by user {user.log}")
            return None
        except Exception as e:
            logger.exception(f"Failed to send notification to {user.log}: {e}")
            raise

    def _get_media_method(self, payload: MessagePayloadDto) -> Optional[Callable[..., Any]]:
        if payload.is_photo:
            return self.bot.send_photo

        if payload.is_video:
            return self.bot.send_video

        if payload.is_document:
            return self.bot.send_document

        if payload.is_animation:
            return self.bot.send_animation

        return None

    def _get_translated_text(
        self,
        locale: Locale,
        i18n_key: str,
        i18n_kwargs: dict[str, Any] = {},
    ) -> str:
        if not i18n_key:
            return ""

        i18n = self.translator_hub.get_translator_by_locale(locale)
        translated_text = i18n.get(i18n_key, **i18n_kwargs)

        if i18n_key == "raw-message":
            if "$" in translated_text and i18n_kwargs:
                template = string.Template(translated_text)
                return template.safe_substitute(i18n_kwargs)

        return translated_text

    def _prepare_reply_markup(
        self,
        reply_markup: Optional[AnyKeyboard],
        disable_default_markup: bool,
        delete_after: Optional[int],
        locale: Locale,
        chat_id: int,
    ) -> Optional[AnyKeyboard]:
        close_keyboard = self._get_default_keyboard(get_close_notification_button())

        if reply_markup is None:
            if not disable_default_markup and delete_after is None:
                return self._translate_keyboard_text(close_keyboard, locale)
            return None

        translated_markup = self._translate_keyboard_text(reply_markup, locale)

        if disable_default_markup or delete_after is not None:
            return translated_markup

        if isinstance(translated_markup, InlineKeyboardMarkup):
            builder = InlineKeyboardBuilder.from_markup(translated_markup)
            builder.row(get_close_notification_button())
            return self._translate_keyboard_text(builder.as_markup(), locale)

        logger.warning(
            f"Unsupported reply_markup type '{type(reply_markup).__name__}' "
            f"for chat '{chat_id}', close button skipped"
        )
        return translated_markup

    def _get_default_keyboard(self, button: InlineKeyboardButton) -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder([[button]])
        return builder.as_markup()

    def _translate_keyboard_text(self, keyboard: AnyKeyboard, locale: Locale) -> AnyKeyboard:
        if isinstance(keyboard, InlineKeyboardMarkup):
            i_rows = []
            for i_row in keyboard.inline_keyboard:
                i_buttons = []
                for i_btn in i_row:
                    btn_dict = i_btn.model_dump()
                    translated = self._get_translated_text(locale, i_btn.text) or i_btn.text
                    clean_text, emoji_id = extract_tg_emoji(translated)
                    clean_text, color = extract_color(clean_text)
                    btn_dict["text"] = clean_text
                    if color is not None:
                        btn_dict["style"] = color
                    if emoji_id and not btn_dict.get("icon_custom_emoji_id"):
                        btn_dict["icon_custom_emoji_id"] = emoji_id
                    i_buttons.append(InlineKeyboardButton(**btn_dict))
                i_rows.append(i_buttons)
            return InlineKeyboardMarkup(inline_keyboard=i_rows)

        if isinstance(keyboard, ReplyKeyboardMarkup):
            r_rows = []
            for r_row in keyboard.keyboard:
                r_buttons = []
                for r_btn in r_row:
                    btn_dict = r_btn.model_dump()
                    translated = self._get_translated_text(locale, r_btn.text) or r_btn.text
                    clean_text, _ = extract_tg_emoji(translated)
                    btn_dict["text"], _ = extract_color(clean_text)
                    r_buttons.append(type(r_btn)(**btn_dict))
                r_rows.append(r_buttons)
            return ReplyKeyboardMarkup(keyboard=r_rows, **keyboard.model_dump(exclude={"keyboard"}))

        return keyboard

    async def _schedule_message_deletion(self, chat_id: int, message_id: int, delay: int) -> None:
        logger.debug(f"Schedule msg '{message_id}' deletion in chat '{chat_id}' after '{delay}'s")
        await asyncio.sleep(delay)
        await self.delete_notification(chat_id, message_id)

    async def _clear_reply_markup(self, chat_id: int, message_id: int) -> None:
        try:
            logger.debug(f"Attempting to remove keyboard from notification '{message_id}'")
            await self.bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=None,
            )
            logger.debug(f"Keyboard removed from notification '{message_id}'")
        except Exception as e:
            logger.error(f"Failed to remove keyboard from '{message_id}': {e}")

    def _build_media(self, media: MediaDescriptorDto) -> Union[str, BufferedInputFile, FSInputFile]:
        if media.kind == "file_id":
            return media.value

        if media.kind == "fs":
            return FSInputFile(
                path=media.value,
                filename=media.filename,
            )

        if media.kind == "bytes":
            return BufferedInputFile(
                file=base64.b64decode(media.value),
                filename=media.filename or "file.bin",
            )

        raise ValueError(f"Unsupported media kind '{media.kind}'")
