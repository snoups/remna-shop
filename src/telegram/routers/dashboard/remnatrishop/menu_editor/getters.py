from typing import Any

from adaptix import Retort
from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.application.common import TranslatorRunner
from src.application.common.dao import SettingsDao
from src.application.dto import MenuButtonDto
from src.core.enums import ButtonType, Role


@inject
async def menu_editor_getter(
    dialog_manager: DialogManager,
    i18n: FromDishka[TranslatorRunner],
    retort: FromDishka[Retort],
    settings_dao: FromDishka[SettingsDao],
    **kwargs: Any,
) -> dict[str, Any]:
    settings = await settings_dao.get()
    buttons = retort.dump(settings.menu.buttons, list[MenuButtonDto])
    dialog_manager.dialog_data["buttons"] = buttons
    return {
        "buttons": [{**button, "text": i18n.get(button["text"])} for button in buttons],
    }


@inject
async def button_getter(
    dialog_manager: DialogManager,
    i18n: FromDishka[TranslatorRunner],
    **kwargs: Any,
) -> dict[str, Any]:
    button = dialog_manager.dialog_data["button"]
    return {
        **button,
        "text": i18n.get(button["text"]),
        "color": button.get("color") or "",
    }


async def availability_getter(
    dialog_manager: DialogManager,
    **kwargs: Any,
) -> dict[str, Any]:
    availability = list(Role)
    availability.remove(Role.PREVIEW)
    availability.remove(Role.SYSTEM)
    return {"availability": availability}


async def type_getter(
    dialog_manager: DialogManager,
    **kwargs: Any,
) -> dict[str, Any]:
    return {"types": list(ButtonType)}
