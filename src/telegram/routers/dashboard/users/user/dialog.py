from uuid import UUID

from aiogram_dialog import Dialog, StartMode, Window
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.text import Format
from magic_filter import F

from src.core.enums import BannerName, SubscriptionStatus, TransactionStatus
from src.telegram.keyboards import back_main_menu_button
from src.telegram.routers.dashboard.broadcast.handlers import on_content_input, on_preview
from src.telegram.states import DashboardRemnashop, DashboardUser
from src.telegram.widgets import Banner, I18nFormat, IgnoreUpdate
from src.telegram.widgets.kbd import (
    Button,
    Column,
    CopyText,
    Group,
    ListGroup,
    Row,
    ScrollingGroup,
    Select,
    Start,
    SwitchTo,
)

from .getters import (
    device_limit_getter,
    devices_getter,
    discount_getter,
    expire_time_getter,
    external_squads_getter,
    give_access_getter,
    give_subscription_getter,
    internal_squads_getter,
    points_getter,
    referrals_getter,
    role_getter,
    squads_getter,
    statistics_getter,
    subscription_duration_getter,
    subscription_getter,
    sync_getter,
    traffic_limit_getter,
    transaction_getter,
    transactions_getter,
    user_getter,
)
from .handlers import (
    on_active_toggle,
    on_back_to_list,
    on_back_to_referrals,
    on_block_toggle,
    on_current_subscription,
    on_device_delete,
    on_device_limit_input,
    on_device_limit_select,
    on_devices,
    on_duration_input,
    on_duration_select,
    on_external_squad_select,
    on_give_access,
    on_give_subscription,
    on_go_to_user,
    on_grant_failed_subscription,
    on_internal_squad_select,
    on_personal_discount_input,
    on_personal_discount_select,
    on_plan_select,
    on_points_input,
    on_points_select,
    on_purchase_discount_input,
    on_purchase_discount_select,
    on_referral_reset,
    on_reissue_subscription,
    on_reset_traffic,
    on_role_select,
    on_send,
    on_subscription_delete,
    on_subscription_duration_select,
    on_subscription_select,
    on_sync,
    on_sync_from_remnashop,
    on_sync_from_remnawave,
    on_traffic_limit_input,
    on_traffic_limit_select,
    on_transaction_select,
    on_transactions,
    on_trial_toggle,
    on_user_select,
)

user = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-user-main"),
    Row(
        Button(
            text=I18nFormat("btn-user.current-subscription"),
            id="subscription",
            on_click=on_current_subscription,
        ),
        when=F["has_subscription"],
    ),
    Row(
        Button(
            text=I18nFormat("btn-user.referral-reset"),
            id="referral_reset",
            on_click=on_referral_reset,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-user.statistics"),
            id="statistics",
            state=DashboardUser.STATISTICS,
        ),
        Button(
            text=I18nFormat("btn-user.transactions"),
            id="transactions",
            on_click=on_transactions,
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-user.sync"),
            id="sync",
            on_click=on_sync,
        ),
        Button(
            text=I18nFormat("btn-user.give-subscription"),
            id="give_subscription",
            on_click=on_give_subscription,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-user.message"),
            id="message",
            state=DashboardUser.MESSAGE,
        ),
        Button(
            text=I18nFormat("btn-user.give-access"),
            id="give_access",
            on_click=on_give_access,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-user.role"),
            id="role",
            state=DashboardUser.ROLE,
            when=F["is_not_self"] & F["can_edit"],
        ),
        SwitchTo(
            text=I18nFormat("btn-user.discount"),
            id="discount",
            state=DashboardUser.DISCOUNT,
        ),
        SwitchTo(
            text=I18nFormat("btn-user.points"),
            id="points",
            state=DashboardUser.POINTS,
            when=F["show_points"],
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-user.trial-toggle"),
            id="trial_toggle",
            on_click=on_trial_toggle,
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-user.block"),
            id="block",
            on_click=on_block_toggle,
            when=F["is_not_self"] & F["can_edit"],
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-back.referrals"),
            id="back_referrals",
            on_click=on_back_to_referrals,
            when=F["from_referral_user_id"],
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-back.dashboard"),
            id="back",
            on_click=on_back_to_list,
        ),
    ),
    *back_main_menu_button,
    IgnoreUpdate(),
    state=DashboardUser.MAIN,
    getter=user_getter,
)

subscription = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-user-subscription-info"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-user.subscription-traffic-limit"),
            id="traffic",
            state=DashboardUser.TRAFFIC_LIMIT,
        ),
        SwitchTo(
            text=I18nFormat("btn-user.subscription-device-limit"),
            id="device",
            state=DashboardUser.DEVICE_LIMIT,
        ),
        when=F["can_edit"],
    ),
    Row(
        Button(
            text=I18nFormat("btn-user.subscription-traffic-reset"),
            id="reset",
            on_click=on_reset_traffic,
        ),
        Button(
            text=I18nFormat("btn-user.subscription-devices"),
            id="devices",
            on_click=on_devices,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-user.subscription-expire-time"),
            id="expire_time",
            state=DashboardUser.EXPIRE_TIME,
        ),
        SwitchTo(
            text=I18nFormat("btn-user.subscription-squads"),
            id="squads",
            state=DashboardUser.SQUADS,
            when=F["can_edit"],
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-user.subscription-active-toggle", is_active=F["is_active"]),
            id="active_toggle",
            on_click=on_active_toggle,
            when=F["subscription_status"].in_(
                [SubscriptionStatus.ACTIVE, SubscriptionStatus.DISABLED]
            ),
        ),
        Button(
            text=I18nFormat("btn-user.subscription-delete"),
            id="delete",
            on_click=on_subscription_delete,
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-user.subscription-reissue"),
            id="reissue",
            on_click=on_reissue_subscription,
        ),
    ),
    Row(
        CopyText(
            text=I18nFormat("btn-user.subscription-url"),
            copy_text=Format("{url}"),
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardUser.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardUser.SUBSCRIPTION,
    getter=subscription_getter,
)

traffic_limit = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-user-subscription-traffic-limit"),
    Group(
        Select(
            text=I18nFormat("{item[traffic_limit][0]}", value=F["item"]["traffic"]),
            id="traffic_limit_select",
            item_id_getter=lambda item: item["traffic"],
            items="traffic_count",
            type_factory=int,
            on_click=on_traffic_limit_select,
        ),
        width=3,
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardUser.SUBSCRIPTION,
        ),
    ),
    MessageInput(func=on_traffic_limit_input),
    IgnoreUpdate(),
    state=DashboardUser.TRAFFIC_LIMIT,
    getter=traffic_limit_getter,
)

device_limit = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-user-subscription-device-limit"),
    Group(
        Select(
            text=I18nFormat("unit-device", value=F["item"]),
            id="device_limit_select",
            item_id_getter=lambda item: item,
            items="devices_count",
            type_factory=int,
            on_click=on_device_limit_select,
        ),
        width=3,
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardUser.SUBSCRIPTION,
        ),
    ),
    MessageInput(func=on_device_limit_input),
    IgnoreUpdate(),
    state=DashboardUser.DEVICE_LIMIT,
    getter=device_limit_getter,
)

expire_time = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-user-subscription-expire-time"),
    Group(
        Select(
            text=Format("{item[operation]}{item[duration]}"),
            id="duration_select",
            item_id_getter=lambda item: item["days"],
            items="durations",
            type_factory=int,
            on_click=on_duration_select,
        ),
        width=2,
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardUser.SUBSCRIPTION,
        ),
    ),
    MessageInput(func=on_duration_input),
    IgnoreUpdate(),
    state=DashboardUser.EXPIRE_TIME,
    getter=expire_time_getter,
)

squads = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-user-subscription-squads"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-user.subscription-internal-squads"),
            id="internal",
            state=DashboardUser.INTERNAL_SQUADS,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-user.subscription-external-squads"),
            id="external",
            state=DashboardUser.EXTERNAL_SQUADS,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardUser.SUBSCRIPTION,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardUser.SQUADS,
    getter=squads_getter,
)

internal_squads = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-user-subscription-internal-squads"),
    Column(
        Select(
            text=I18nFormat(
                "btn-common.squad-choice",
                name=F["item"]["name"],
                selected=F["item"]["selected"],
            ),
            id="select_squad",
            item_id_getter=lambda item: item["uuid"],
            items="squads",
            type_factory=UUID,
            on_click=on_internal_squad_select,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardUser.SQUADS,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardUser.INTERNAL_SQUADS,
    getter=internal_squads_getter,
)

external_squads = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-user-subscription-external-squads"),
    Column(
        Select(
            text=I18nFormat(
                "btn-common.squad-choice",
                name=F["item"]["name"],
                selected=F["item"]["selected"],
            ),
            id="select_squad",
            item_id_getter=lambda item: item["uuid"],
            items="squads",
            type_factory=UUID,
            on_click=on_external_squad_select,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardUser.SQUADS,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardUser.EXTERNAL_SQUADS,
    getter=external_squads_getter,
)

devices_list = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-user-devices"),
    ListGroup(
        Row(
            CopyText(
                text=Format("{item[platform]} - {item[device_model]}"),
                copy_text=Format("{item[hwid]}"),
            ),
            Button(
                text=Format("❌"),
                id="delete",
                on_click=on_device_delete,
            ),
        ),
        id="devices_list",
        item_id_getter=lambda item: item["short_hwid"],
        items="devices",
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardUser.SUBSCRIPTION,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardUser.DEVICES_LIST,
    getter=devices_getter,
)

sync = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-user-sync"),
    Column(
        Button(
            text=I18nFormat("btn-user.sync-remnashop"),
            id="sync_from_remnashop",
            on_click=on_sync_from_remnashop,
        ),
        Button(
            text=I18nFormat("btn-user.sync-remnawave"),
            id="sync_from_remnawave",
            on_click=on_sync_from_remnawave,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardUser.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardUser.SYNC,
    getter=sync_getter,
)

sync_waiting = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-user-sync-waiting"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardUser.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardUser.SYNC_WAITING,
    getter=sync_getter,
)

give_subscription = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-user-give-subscription"),
    Column(
        Select(
            text=Format("{item[plan_name]}"),
            id="plan_select",
            item_id_getter=lambda item: item["plan_id"],
            items="plans",
            type_factory=int,
            on_click=on_subscription_select,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardUser.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardUser.GIVE_SUBSCRIPTION,
    getter=give_subscription_getter,
)

subscription_duration = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-user-give-subscription-duration"),
    Group(
        Select(
            text=I18nFormat("btn-common.duration", value=F["item"]["days"]),
            id="duration_select",
            item_id_getter=lambda item: item["days"],
            items="durations",
            type_factory=int,
            on_click=on_subscription_duration_select,
        ),
        width=2,
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardUser.GIVE_SUBSCRIPTION,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardUser.SUBSCRIPTION_DURATION,
    getter=subscription_duration_getter,
)

statistics = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-user-statistics"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-user.referrals"),
            id="referrals",
            state=DashboardUser.REFERRALS,
        ),
        when=F["has_referrals"],
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardUser.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardUser.STATISTICS,
    getter=statistics_getter,
)

referrals = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-user-referrals"),
    ScrollingGroup(
        Select(
            text=Format("{item[telegram_id]} ({item[name]})"),
            id="referral_select",
            item_id_getter=lambda item: item["id"],
            items="referrals",
            type_factory=int,
            on_click=on_user_select,
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
            state=DashboardUser.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardUser.REFERRALS,
    getter=referrals_getter,
)

transactions_list = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-user-transactions"),
    ScrollingGroup(
        Select(
            text=I18nFormat(
                "btn-user.transaction",
                status=F["item"]["status"],
                created_at=F["item"]["created_at"],
                gateway_type=F["item"]["gateway_type"],
            ),
            id="transaction_select",
            item_id_getter=lambda item: item["payment_id"],
            items="transactions",
            type_factory=UUID,
            on_click=on_transaction_select,
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
            state=DashboardUser.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardUser.TRANSACTIONS_LIST,
    getter=transactions_getter,
)

transaction = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-user-transaction-info"),
    Row(
        Button(
            text=I18nFormat("btn-goto.user-profile"),
            id="go_to_user",
            on_click=on_go_to_user,
            when=F["is_from_all_transactions"],
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-user.transaction-grant"),
            id="grant_failed",
            on_click=on_grant_failed_subscription,
            when=F["transaction_status"] == TransactionStatus.FAILED,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardUser.TRANSACTIONS_LIST,
            when=~F["is_from_all_transactions"],
        ),
        Start(
            text=I18nFormat("btn-back.general"),
            id="back_all_transactions",
            state=DashboardRemnashop.TRANSACTIONS,
            mode=StartMode.RESET_STACK,
            when=F["is_from_all_transactions"],
        ),
    ),
    IgnoreUpdate(),
    state=DashboardUser.TRANSACTION,
    getter=transaction_getter,
)

message = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-user-message"),
    Row(
        Button(
            I18nFormat("btn-user.message-preview"),
            id="preview",
            on_click=on_preview,
        ),
    ),
    Row(
        Button(
            I18nFormat("btn-user.message-confirm"),
            id="confirm",
            on_click=on_send,
        ),
    ),
    Row(
        SwitchTo(
            I18nFormat("btn-back.general"),
            id="back",
            state=DashboardUser.MAIN,
        ),
    ),
    MessageInput(func=on_content_input),
    IgnoreUpdate(),
    state=DashboardUser.MESSAGE,
)

discount = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-user-discount"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-user.discount-personal"),
            id="discount_personal",
            state=DashboardUser.PERSONAL_DISCOUNT,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-user.discount-purchase"),
            id="discount_purchase",
            state=DashboardUser.PURCHASE_DISCOUNT,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardUser.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardUser.DISCOUNT,
)

personal_discount = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-user-discount-personal"),
    Group(
        Select(
            text=Format("{item}%"),
            id="personal_discount_select",
            item_id_getter=lambda item: item,
            items="percentages",
            type_factory=int,
            on_click=on_personal_discount_select,
        ),
        width=3,
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardUser.DISCOUNT,
        ),
    ),
    MessageInput(func=on_personal_discount_input),
    IgnoreUpdate(),
    state=DashboardUser.PERSONAL_DISCOUNT,
    getter=discount_getter,
)

purchase_discount = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-user-discount-purchase"),
    Group(
        Select(
            text=Format("{item}%"),
            id="purchase_discount_select",
            item_id_getter=lambda item: item,
            items="percentages",
            type_factory=int,
            on_click=on_purchase_discount_select,
        ),
        width=3,
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardUser.DISCOUNT,
        ),
    ),
    MessageInput(func=on_purchase_discount_input),
    IgnoreUpdate(),
    state=DashboardUser.PURCHASE_DISCOUNT,
    getter=discount_getter,
)

points = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-user-points"),
    Group(
        Select(
            text=Format("{item[operation]}{item[points]} 💎"),
            id="points_select",
            item_id_getter=lambda item: item["points"],
            items="points",
            type_factory=int,
            on_click=on_points_select,
        ),
        width=2,
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardUser.MAIN,
        ),
    ),
    MessageInput(func=on_points_input),
    IgnoreUpdate(),
    state=DashboardUser.POINTS,
    getter=points_getter,
)

give_access = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-user-give-access"),
    Column(
        Select(
            text=I18nFormat(
                "btn-user.allowed-plan-choice",
                plan_name=F["item"]["plan_name"],
                selected=F["item"]["selected"],
            ),
            id="plan_select",
            item_id_getter=lambda item: item["plan_id"],
            items="plans",
            type_factory=int,
            on_click=on_plan_select,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardUser.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardUser.GIVE_ACCESS,
    getter=give_access_getter,
)

role = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-user-role"),
    Column(
        Select(
            text=I18nFormat("role", role=F["item"]),
            id="role_select",
            item_id_getter=lambda item: item.value,
            items="roles",
            type_factory=int,
            on_click=on_role_select,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardUser.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardUser.ROLE,
    getter=role_getter,
)

router = Dialog(
    user,
    subscription,
    traffic_limit,
    device_limit,
    expire_time,
    squads,
    internal_squads,
    external_squads,
    devices_list,
    sync,
    sync_waiting,
    give_subscription,
    subscription_duration,
    statistics,
    referrals,
    transactions_list,
    transaction,
    message,
    discount,
    personal_discount,
    purchase_discount,
    points,
    give_access,
    role,
)
