from typing import Any

from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.application.common.dao import SettingsDao
from src.core.enums import SystemNotificationType
from src.core.types import NotificationType


@inject
async def user_types_getter(
    dialog_manager: DialogManager,
    settings_dao: FromDishka[SettingsDao],
    **kwargs: Any,
) -> dict[str, Any]:
    settings = await settings_dao.get()

    types = [
        {
            "notification_type": field.upper(),
            "enabled": value,
        }
        for field, value in settings.notifications.user
    ]

    return {"types": types}


@inject
async def system_types_getter(
    dialog_manager: DialogManager,
    settings_dao: FromDishka[SettingsDao],
    **kwargs: Any,
) -> dict[str, Any]:
    settings = await settings_dao.get()

    types = []
    for field, value in settings.notifications.system:
        has_route = settings.notifications.get_route(field) is not None
        is_system = field == SystemNotificationType.SYSTEM

        types.append(
            {
                "notification_type": field.upper(),
                "enabled": True if is_system else value,
                "has_route": has_route,
                "can_toggle": not is_system,
            }
        )

    return {"types": types}


@inject
async def system_type_getter(
    dialog_manager: DialogManager,
    settings_dao: FromDishka[SettingsDao],
    **kwargs: Any,
) -> dict[str, Any]:
    settings = await settings_dao.get()
    notification_type = dialog_manager.dialog_data["notification_type"]
    enabled = settings.notifications.is_enabled(notification_type)
    route = settings.notifications.get_route(notification_type)

    is_system = notification_type == SystemNotificationType.SYSTEM

    return {
        "notification_type": notification_type,
        "is_active": True if is_system else enabled,
        "can_toggle": not is_system,
        "has_route": route.is_configured if route else False,
        "chat_id": route.chat_id or False if route else False,
        "thread_id": route.thread_id or False if route else False,
    }


@inject
async def system_route_getter(
    dialog_manager: DialogManager,
    settings_dao: FromDishka[SettingsDao],
    **kwargs: Any,
) -> dict[str, Any]:
    settings = await settings_dao.get()
    notification_type: NotificationType = dialog_manager.dialog_data["notification_type"]
    route = settings.notifications.get_route(notification_type)

    return {
        "notification_type": notification_type,
        "has_route": route.chat_id or route.thread_id if route else False,
        "chat_id": route.chat_id or False if route else False,
        "thread_id": route.thread_id or False if route else False,
    }


@inject
async def system_default_route_getter(
    dialog_manager: DialogManager,
    settings_dao: FromDishka[SettingsDao],
    **kwargs: Any,
) -> dict[str, Any]:
    settings = await settings_dao.get()
    route = settings.notifications.default_route

    return {
        "has_route": route.chat_id or route.thread_id,
        "chat_id": route.chat_id or False,
        "thread_id": route.thread_id or False,
    }
