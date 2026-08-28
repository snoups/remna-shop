from aiogram.enums import ButtonStyle
from aiogram_dialog import Dialog, StartMode, Window
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.style import Style

from src.core.enums import BannerName
from src.telegram.states import DashboardRemnashop, RemnashopBackup
from src.telegram.widgets import Banner, I18nFormat, IgnoreUpdate
from src.telegram.widgets.kbd import Button, Row, Start, SwitchTo

from .getters import backup_getter
from .handlers import (
    on_active_toggle,
    on_backup_assets,
    on_backup_database,
    on_interval_input,
    on_max_files_input,
    on_toggle_send_to_chat,
)

main = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-backup-main"),
    Row(
        Button(
            text=I18nFormat("btn-backup.active-toggle"),
            id="active_toggle",
            on_click=on_active_toggle,
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-backup.send-toggle"),
            id="send_toggle",
            on_click=on_toggle_send_to_chat,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-backup.set-interval"),
            id="interval",
            state=RemnashopBackup.INTERVAL,
        ),
        SwitchTo(
            text=I18nFormat("btn-backup.set-max-files"),
            id="max_files",
            state=RemnashopBackup.MAX_FILES,
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-backup.backup-assets"),
            id="backup_assets",
            on_click=on_backup_assets,
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-backup.backup-db"),
            id="backup_db",
            on_click=on_backup_database,
            style=Style(ButtonStyle.PRIMARY),
        ),
    ),
    Row(
        Start(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardRemnashop.MAIN,
            mode=StartMode.RESET_STACK,
        ),
    ),
    IgnoreUpdate(),
    state=RemnashopBackup.MAIN,
    getter=backup_getter,
)

interval = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-backup-set-interval"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopBackup.MAIN,
        ),
    ),
    MessageInput(func=on_interval_input),
    IgnoreUpdate(),
    state=RemnashopBackup.INTERVAL,
    getter=backup_getter,
)

max_files = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-backup-set-max-files"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopBackup.MAIN,
        ),
    ),
    MessageInput(func=on_max_files_input),
    IgnoreUpdate(),
    state=RemnashopBackup.MAX_FILES,
    getter=backup_getter,
)

router = Dialog(
    main,
    interval,
    max_files,
)
