from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, ShowMode
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.application.common import Notifier
from src.application.dto import TelegramUserDto
from src.application.use_cases.backup.commands import BackupAssets, BackupDatabase
from src.application.use_cases.settings.commands.backup import (
    ToggleBackupEnabled,
    ToggleBackupSendToChat,
    UpdateBackupInterval,
    UpdateBackupMaxFiles,
)
from src.core.constants import USER_KEY
from src.telegram.states import RemnashopBackup


@inject
async def on_active_toggle(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    toggle_backup_enabled: FromDishka[ToggleBackupEnabled],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    await toggle_backup_enabled(user)


@inject
async def on_toggle_send_to_chat(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    toggle_backup_send_to_chat: FromDishka[ToggleBackupSendToChat],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    await toggle_backup_send_to_chat(user)


@inject
async def on_interval_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    update_backup_interval: FromDishka[UpdateBackupInterval],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    input_interval_hours = message.text

    try:
        if not input_interval_hours:
            raise ValueError
        await update_backup_interval(user, input_interval_hours)
    except ValueError:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    dialog_manager.show_mode = ShowMode.DELETE_AND_SEND
    await dialog_manager.switch_to(RemnashopBackup.MAIN)


@inject
async def on_max_files_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    update_backup_max_files: FromDishka[UpdateBackupMaxFiles],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    input_max_files = message.text

    try:
        if not input_max_files:
            raise ValueError
        await update_backup_max_files(user, input_max_files)
    except ValueError:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    dialog_manager.show_mode = ShowMode.DELETE_AND_SEND
    await dialog_manager.switch_to(RemnashopBackup.MAIN)


@inject
async def on_backup_assets(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    backup_assets: FromDishka[BackupAssets],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    await backup_assets(user)


@inject
async def on_backup_database(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    backup_database: FromDishka[BackupDatabase],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    await backup_database(user)
