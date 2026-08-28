from typing import Optional

from adaptix import Retort
from aiogram.enums import ButtonStyle
from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, ShowMode
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, Select
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from loguru import logger

from src.application.common import Notifier
from src.application.dto import MenuButtonDto, TelegramUserDto
from src.application.use_cases.misc.commands.menu_editor import (
    ConfirmMenuButtonChanges,
    UpdateMenuButtonColor,
    UpdateMenuButtonColorDto,
    UpdateMenuButtonMedia,
    UpdateMenuButtonMediaDto,
    UpdateMenuButtonPayload,
    UpdateMenuButtonPayloadDto,
    UpdateMenuButtonText,
    UpdateMenuButtonTextDto,
)
from src.core.constants import USER_KEY
from src.core.enums import ButtonType, MediaType, Role
from src.core.exceptions import MenuEditorInvalidPayloadError
from src.telegram.states import RemnashopMenuEditor


async def on_button_selected(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_button_id: int,
) -> None:
    buttons = dialog_manager.dialog_data["buttons"]
    selected_button = next((b for b in buttons if b["index"] == selected_button_id), None)
    if selected_button is None:
        return
    dialog_manager.dialog_data["button"] = selected_button
    await dialog_manager.switch_to(RemnashopMenuEditor.BUTTON)


@inject
async def on_active_toggle(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    button = dialog_manager.dialog_data["button"]
    button = retort.load(button, MenuButtonDto)

    old_status = button.is_active
    button.is_active = not button.is_active
    dialog_manager.dialog_data["button"] = retort.dump(button)

    logger.info(
        f"{user.log} Updated menu button '{button.index}' "
        f"active status from '{old_status}' to '{button.is_active}'"
    )


@inject
async def on_subscribers_only_toggle(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    button = dialog_manager.dialog_data["button"]
    button = retort.load(button, MenuButtonDto)

    old_value = button.subscribers_only
    button.subscribers_only = not button.subscribers_only
    dialog_manager.dialog_data["button"] = retort.dump(button)

    logger.info(
        f"{user.log} Updated menu button '{button.index}' "
        f"subscribers_only from '{old_value}' to '{button.subscribers_only}'"
    )


@inject
async def on_text_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    notifier: FromDishka[Notifier],
    update_menu_button_text: FromDishka[UpdateMenuButtonText],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    if message.text is None:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    button = dialog_manager.dialog_data["button"]
    button = retort.load(button, MenuButtonDto)

    try:
        button = await update_menu_button_text(user, UpdateMenuButtonTextDto(button, message.text))
    except ValueError:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    dialog_manager.dialog_data["button"] = retort.dump(button)
    await dialog_manager.switch_to(RemnashopMenuEditor.BUTTON)


@inject
async def on_availability_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_availability: int,
    retort: FromDishka[Retort],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    button = dialog_manager.dialog_data["button"]
    button = retort.load(button, MenuButtonDto)

    old_role = button.required_role
    button.required_role = Role(selected_availability)
    dialog_manager.dialog_data["button"] = retort.dump(button)

    logger.info(
        f"{user.log} Updated menu button '{button.index}' "
        f"required role from '{old_role}' to '{button.required_role}'"
    )

    await dialog_manager.switch_to(RemnashopMenuEditor.BUTTON)


@inject
async def on_type_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_type: ButtonType,
    retort: FromDishka[Retort],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    button = dialog_manager.dialog_data["button"]
    button = retort.load(button, MenuButtonDto)

    old_type = button.type
    button.type = selected_type
    dialog_manager.dialog_data["button"] = retort.dump(button)

    logger.info(
        f"{user.log} Updated menu button '{button.index}' type from '{old_type}' to '{button.type}'"
    )

    await dialog_manager.switch_to(RemnashopMenuEditor.BUTTON)


@inject
async def on_payload_input(  # noqa: C901
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    notifier: FromDishka[Notifier],
    update_menu_button_payload: FromDishka[UpdateMenuButtonPayload],
    update_menu_button_media: FromDishka[UpdateMenuButtonMedia],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    button = dialog_manager.dialog_data["button"]
    button = retort.load(button, MenuButtonDto)

    if button.type == ButtonType.TEXT:
        media_type: Optional[MediaType] = None
        file_id: Optional[str] = None

        if message.photo:
            media_type = MediaType.PHOTO
            file_id = message.photo[-1].file_id
        elif message.video:
            media_type = MediaType.VIDEO
            file_id = message.video.file_id
        elif message.animation:
            media_type = MediaType.GIF
            file_id = message.animation.file_id
        elif message.document:
            media_type = MediaType.DOCUMENT
            file_id = message.document.file_id
        elif message.sticker:
            media_type = MediaType.DOCUMENT
            file_id = message.sticker.file_id

        text = message.html_text or ""

        if not text and not file_id:
            await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
            return

        button = await update_menu_button_media(
            user, UpdateMenuButtonMediaDto(button, file_id, media_type)
        )

        try:
            button = await update_menu_button_payload(
                user, UpdateMenuButtonPayloadDto(button, text)
            )
        except ValueError:
            await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
            return
    else:
        if message.text is None:
            await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
            return

        try:
            button = await update_menu_button_payload(
                user, UpdateMenuButtonPayloadDto(button, message.text)
            )
        except ValueError:
            await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
            return

    dialog_manager.dialog_data["button"] = retort.dump(button)
    await dialog_manager.switch_to(RemnashopMenuEditor.BUTTON)


_COLOR_MAP: dict[str, Optional[ButtonStyle]] = {
    "color_default": None,
    "color_primary": ButtonStyle.PRIMARY,
    "color_success": ButtonStyle.SUCCESS,
    "color_danger": ButtonStyle.DANGER,
}


@inject
async def on_color_select(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    update_menu_button_color: FromDishka[UpdateMenuButtonColor],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    button = dialog_manager.dialog_data["button"]
    button = retort.load(button, MenuButtonDto)

    if widget.widget_id not in _COLOR_MAP:
        return

    try:
        button = await update_menu_button_color(
            user, UpdateMenuButtonColorDto(button, _COLOR_MAP[widget.widget_id])
        )
    except ValueError:
        return

    dialog_manager.dialog_data["button"] = retort.dump(button)
    await dialog_manager.switch_to(RemnashopMenuEditor.BUTTON)


@inject
async def on_confirm(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    notifier: FromDishka[Notifier],
    confirm_menu_button_changes: FromDishka[ConfirmMenuButtonChanges],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    button = dialog_manager.dialog_data["button"]
    button = retort.load(button, MenuButtonDto)

    try:
        await confirm_menu_button_changes(user, button)
    except MenuEditorInvalidPayloadError:
        await notifier.notify_user(user, i18n_key="ntf-menu-editor.invalid-payload")
        return

    await notifier.notify_user(user, i18n_key="ntf-menu-editor.button-saved")
    await dialog_manager.reset_stack()
    await dialog_manager.start(state=RemnashopMenuEditor.MAIN)
