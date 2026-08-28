from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, ShowMode
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, Select
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.application.common import Notifier
from src.application.common.dao import SettingsDao
from src.application.dto import TelegramUserDto
from src.application.use_cases.settings.commands.notifications import (
    ToggleNotification,
    UpdateDefaultNotificationRoute,
    UpdateDefaultNotificationRouteDto,
    UpdateSystemNotificationRoute,
    UpdateSystemNotificationRouteDto,
)
from src.core.constants import USER_KEY
from src.core.enums import SystemNotificationType, UserNotificationType
from src.core.utils.validators import parse_int
from src.telegram.states import RemnashopNotifications


@inject
async def on_user_type_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_type: UserNotificationType,
    toggle_notification: FromDishka[ToggleNotification],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    await toggle_notification(user, selected_type)


async def on_system_type_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_type: SystemNotificationType,
) -> None:
    dialog_manager.dialog_data["notification_type"] = selected_type
    await dialog_manager.switch_to(RemnashopNotifications.SYSTEM_TYPE)


@inject
async def on_system_type_toggle(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    toggle_notification: FromDishka[ToggleNotification],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    notification_type = dialog_manager.dialog_data["notification_type"]

    if notification_type == SystemNotificationType.SYSTEM:
        return

    await toggle_notification(user, notification_type)


@inject
async def on_route_clear(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    update_system_notification_route: FromDishka[UpdateSystemNotificationRoute],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    notification_type = dialog_manager.dialog_data["notification_type"]
    await update_system_notification_route(
        user,
        UpdateSystemNotificationRouteDto(
            notification_type=notification_type,
            chat_id=None,
            thread_id=None,
        ),
    )
    await dialog_manager.switch_to(RemnashopNotifications.SYSTEM_ROUTE)


@inject
async def on_route_chat_id_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    settings_dao: FromDishka[SettingsDao],
    update_system_notification_route: FromDishka[UpdateSystemNotificationRoute],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    notification_type = dialog_manager.dialog_data["notification_type"]

    chat_id = parse_int(message.text)
    if chat_id is None:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    settings = await settings_dao.get()
    current_route = settings.notifications.get_route(notification_type)
    thread_id = current_route.thread_id if current_route else None

    await update_system_notification_route(
        user,
        UpdateSystemNotificationRouteDto(
            notification_type=notification_type,
            chat_id=chat_id,
            thread_id=thread_id,
        ),
    )
    await dialog_manager.switch_to(RemnashopNotifications.SYSTEM_ROUTE)


@inject
async def on_route_thread_id_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    settings_dao: FromDishka[SettingsDao],
    update_system_notification_route: FromDishka[UpdateSystemNotificationRoute],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    notification_type = dialog_manager.dialog_data["notification_type"]

    thread_id = parse_int(message.text)
    if thread_id is None:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    settings = await settings_dao.get()
    current_route = settings.notifications.get_route(notification_type)
    chat_id = current_route.chat_id if current_route else None

    await update_system_notification_route(
        user,
        UpdateSystemNotificationRouteDto(
            notification_type=notification_type,
            chat_id=chat_id,
            thread_id=thread_id,
        ),
    )

    await dialog_manager.switch_to(RemnashopNotifications.SYSTEM_ROUTE)


@inject
async def on_default_route_clear(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    update_default_notification_route: FromDishka[UpdateDefaultNotificationRoute],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    await update_default_notification_route(
        user,
        UpdateDefaultNotificationRouteDto(chat_id=None, thread_id=None),
    )
    await dialog_manager.switch_to(RemnashopNotifications.SYSTEM_DEFAULT_ROUTE)


@inject
async def on_default_route_chat_id_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    settings_dao: FromDishka[SettingsDao],
    update_default_notification_route: FromDishka[UpdateDefaultNotificationRoute],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    chat_id = parse_int(message.text)
    if chat_id is None:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    settings = await settings_dao.get()
    thread_id = settings.notifications.default_route.thread_id

    await update_default_notification_route(
        user,
        UpdateDefaultNotificationRouteDto(chat_id=chat_id, thread_id=thread_id),
    )
    await dialog_manager.switch_to(RemnashopNotifications.SYSTEM_DEFAULT_ROUTE)


@inject
async def on_default_route_thread_id_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    settings_dao: FromDishka[SettingsDao],
    update_default_notification_route: FromDishka[UpdateDefaultNotificationRoute],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    thread_id = parse_int(message.text)
    if thread_id is None:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    settings = await settings_dao.get()
    chat_id = settings.notifications.default_route.chat_id

    await update_default_notification_route(
        user,
        UpdateDefaultNotificationRouteDto(chat_id=chat_id, thread_id=thread_id),
    )
    await dialog_manager.switch_to(RemnashopNotifications.SYSTEM_DEFAULT_ROUTE)
