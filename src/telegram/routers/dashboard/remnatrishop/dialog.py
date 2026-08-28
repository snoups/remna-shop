from uuid import UUID

from aiogram_dialog import Dialog, StartMode, Window
from aiogram_dialog.widgets.text import Format
from magic_filter import F

from src.application.common.policy import Permission
from src.core.enums import BannerName
from src.telegram.keyboards import main_menu_button
from src.telegram.states import (
    Dashboard,
    DashboardRemnashop,
    RemnashopAdvertising,
    RemnashopBackup,
    RemnashopExtra,
    RemnashopGateways,
    RemnashopMenuEditor,
    RemnashopNotifications,
    RemnashopPlans,
    RemnashopReferral,
)
from src.telegram.utils import require_permission
from src.telegram.widgets import Banner, I18nFormat, IgnoreUpdate
from src.telegram.widgets.kbd import Button, ListGroup, Row, ScrollingGroup, Select, Start, SwitchTo

from .getters import admins_getter, all_transactions_getter, remnashop_getter
from .handlers import on_all_transaction_select, on_logs_request, on_role_revoke, on_user_select

remnashop = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-remnashop-main"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-remnashop.admins"),
            id="admins",
            state=DashboardRemnashop.ADMINS,
            when=require_permission(Permission.VIEW_ADMINS),
        ),
    ),
    Row(
        Start(
            text=I18nFormat("btn-remnashop.gateways"),
            id="gateways",
            state=RemnashopGateways.MAIN,
            when=require_permission(Permission.VIEW_GATEWAYS),
        ),
    ),
    Row(
        Start(
            text=I18nFormat("btn-remnashop.referral"),
            id="referral",
            state=RemnashopReferral.MAIN,
            when=require_permission(Permission.VIEW_REFERRAL),
        ),
        Start(
            text=I18nFormat("btn-remnashop.advertising"),
            id="advertising",
            state=RemnashopAdvertising.MAIN,
            when=require_permission(Permission.VIEW_ADVERTISING),
        ),
    ),
    Row(
        Start(
            text=I18nFormat("btn-remnashop.plans"),
            id="plans",
            state=RemnashopPlans.MAIN,
            mode=StartMode.RESET_STACK,
            when=require_permission(Permission.VIEW_PLANS),
        ),
        Start(
            text=I18nFormat("btn-remnashop.notifications"),
            id="notifications",
            state=RemnashopNotifications.MAIN,
            when=require_permission(Permission.VIEW_NOTIFICATIONS),
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-remnashop.logs"),
            id="logs",
            on_click=on_logs_request,
            when=require_permission(Permission.VIEW_LOGS),
        ),
        Start(
            text=I18nFormat("btn-remnashop.backup"),
            id="backup",
            state=RemnashopBackup.MAIN,
            when=require_permission(Permission.VIEW_BACKUP),
        ),
    ),
    Row(
        Start(
            text=I18nFormat("btn-remnashop.menu-editor"),
            id="menu_editor",
            state=RemnashopMenuEditor.MAIN,
            when=require_permission(Permission.VIEW_MENU_EDITOR),
        ),
    ),
    Row(
        Start(
            text=I18nFormat("btn-remnashop.extra"),
            id="extra",
            state=RemnashopExtra.MAIN,
            when=require_permission(Permission.VIEW_EXTRA_SETTINGS),
        ),
    ),
    Row(
        Start(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=Dashboard.MAIN,
            mode=StartMode.RESET_STACK,
        ),
        *main_menu_button,
    ),
    IgnoreUpdate(),
    state=DashboardRemnashop.MAIN,
    getter=remnashop_getter,
)

admins = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-admins-main"),
    ListGroup(
        Row(
            Button(
                text=Format("{item[telegram_id]} ({item[name]})"),
                id="user_select",
                on_click=on_user_select,
            ),
            Button(
                text=Format("❌"),
                id="role_revoke",
                on_click=on_role_revoke,
                when=F["item"]["is_deletable"],
            ),
        ),
        id="admins_list",
        item_id_getter=lambda item: item["user_id"],
        items="admins",
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
    state=DashboardRemnashop.ADMINS,
    getter=admins_getter,
)

all_transactions = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-remnashop-transactions"),
    ScrollingGroup(
        Select(
            text=I18nFormat(
                "btn-remnashop-transaction",
                status=F["item"]["status"],
                user_id=F["item"]["user_id"],
                created_at=F["item"]["created_at"],
                gateway_type=F["item"]["gateway_type"],
            ),
            id="transaction_select",
            item_id_getter=lambda item: item["payment_id"],
            items="transactions",
            type_factory=UUID,
            on_click=on_all_transaction_select,
        ),
        id="scroll",
        width=1,
        height=7,
        hide_on_single_page=True,
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardRemnashop.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardRemnashop.TRANSACTIONS,
    getter=all_transactions_getter,
)

router = Dialog(
    remnashop,
    admins,
    all_transactions,
)
