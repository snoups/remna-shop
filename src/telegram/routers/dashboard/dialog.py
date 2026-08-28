from aiogram_dialog import Dialog, StartMode, Window
from aiogram_dialog.widgets.input import MessageInput

from src.application.common.policy import Permission
from src.core.enums import BannerName
from src.telegram.keyboards import back_main_menu_button
from src.telegram.states import (
    Dashboard,
    DashboardAccess,
    DashboardBroadcast,
    DashboardImporter,
    DashboardPromocodes,
    DashboardRemnashop,
    DashboardRemnawave,
    DashboardStatistics,
    DashboardUsers,
)
from src.telegram.utils import require_permission
from src.telegram.widgets import Banner, I18nFormat, IgnoreUpdate
from src.telegram.widgets.kbd import Button, Row, Start

from .handlers import on_smart_search, on_transactions_list

dashboard = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-dashboard-main"),
    Row(
        Start(
            text=I18nFormat("btn-dashboard.statistics"),
            id="statistics",
            state=DashboardStatistics.MAIN,
            when=require_permission(Permission.VIEW_STATISTICS),
        ),
    ),
    Row(
        Start(
            text=I18nFormat("btn-dashboard.users"),
            id="users",
            state=DashboardUsers.MAIN,
            mode=StartMode.RESET_STACK,
            when=require_permission(Permission.VIEW_USERS),
        ),
        Button(
            text=I18nFormat("btn-dashboard.transactions"),
            id="transactions",
            on_click=on_transactions_list,
            when=require_permission(Permission.VIEW_STATISTICS),
        ),
    ),
    Row(
        Start(
            text=I18nFormat("btn-dashboard.broadcast"),
            id="broadcast",
            state=DashboardBroadcast.MAIN,
            mode=StartMode.RESET_STACK,
            when=require_permission(Permission.VIEW_BROADCAST),
        ),
        Start(
            text=I18nFormat("btn-dashboard.promocodes"),
            id="promocodes",
            state=DashboardPromocodes.MAIN,
            mode=StartMode.RESET_STACK,
            when=require_permission(Permission.VIEW_PROMOCODE),
        ),
    ),
    Row(
        Start(
            text=I18nFormat("btn-dashboard.access"),
            id="access",
            state=DashboardAccess.MAIN,
            mode=StartMode.RESET_STACK,
            when=require_permission(Permission.VIEW_ACCESS),
        ),
    ),
    Row(
        Start(
            text=I18nFormat("btn-dashboard.remnawave"),
            id="remnawave",
            state=DashboardRemnawave.MAIN,
            mode=StartMode.RESET_STACK,
            when=require_permission(Permission.VIEW_REMNAWAVE),
        ),
        Start(
            text=I18nFormat("btn-dashboard.remnashop"),
            id="remnatrishop",
            state=DashboardRemnashop.MAIN,
            mode=StartMode.RESET_STACK,
            when=require_permission(Permission.VIEW_REMNASHOP),
        ),
    ),
    Row(
        Start(
            text=I18nFormat("btn-dashboard.importer"),
            id="importer",
            state=DashboardImporter.MAIN,
        ),
        when=require_permission(Permission.VIEW_IMPORTER),
    ),
    *back_main_menu_button,
    MessageInput(func=on_smart_search),
    IgnoreUpdate(),
    state=Dashboard.MAIN,
)

router = Dialog(dashboard)
