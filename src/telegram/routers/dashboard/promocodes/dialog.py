from aiogram.enums import ButtonStyle
from aiogram_dialog import Dialog, StartMode, Window
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.style import Style
from aiogram_dialog.widgets.text import Format
from magic_filter import F

from src.core.enums import BannerName
from src.telegram.keyboards import main_menu_button
from src.telegram.states import Dashboard, DashboardPromocodes
from src.telegram.widgets import Banner, I18nFormat, IgnoreUpdate
from src.telegram.widgets.kbd import Button, CopyText, ListGroup, Row, Start, SwitchTo

from .getters import (
    getter_availability_select,
    getter_code,
    getter_configurator,
    getter_expires,
    getter_max_activations,
    getter_plan_duration_select,
    getter_plan_select,
    getter_promocodes_main,
    getter_reward,
    getter_type_select,
)
from .handlers import (
    on_availability_select,
    on_code_input,
    on_code_regenerate,
    on_create_promo,
    on_delete_promo,
    on_expires_input,
    on_expires_reset,
    on_max_activations_input,
    on_max_activations_reset,
    on_page_next,
    on_page_prev,
    on_plan_duration_select,
    on_plan_open,
    on_plan_select,
    on_promo_confirm,
    on_promo_select,
    on_reward_input,
    on_toggle_active,
    on_toggle_reusable,
    on_type_select,
)

promocodes_main = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-promocodes-main"),
    Row(
        Button(
            text=I18nFormat("btn-promocodes.create"),
            id="create_promo",
            on_click=on_create_promo,
            when=F["can_manage"],
        ),
    ),
    ListGroup(
        Row(
            Button(
                text=I18nFormat(
                    "btn-promocodes.item",
                    code=F["item"]["code"],
                    promocode_type=F["item"]["reward_type"],
                ),
                id="promo_item",
                on_click=on_promo_select,
            ),
        ),
        id="promos_list",
        item_id_getter=lambda item: item["id"],
        items="promos",
    ),
    Row(
        Button(
            text=I18nFormat("btn-common.prev"),
            id="page_prev",
            on_click=on_page_prev,
            when=F["has_prev"],
        ),
        Button(
            text=I18nFormat("btn-common.next"),
            id="page_next",
            on_click=on_page_next,
            when=F["has_next"],
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
    state=DashboardPromocodes.MAIN,
    getter=getter_promocodes_main,
)

configurator = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-promocode-configurator"),
    Row(
        Button(
            text=I18nFormat("btn-promocodes.active-toggle", is_active=F["is_active"]),
            id="toggle_active",
            on_click=on_toggle_active,
            when=F["can_manage"],
        ),
        Button(
            text=I18nFormat("btn-promocodes.reusable-toggle", is_reusable=F["is_reusable"]),
            id="toggle_reusable",
            on_click=on_toggle_reusable,
            when=F["can_manage"],
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-promocodes.code"),
            id="code",
            state=DashboardPromocodes.CODE,
        ),
        SwitchTo(
            text=I18nFormat("btn-promocodes.type"),
            id="type",
            state=DashboardPromocodes.TYPE,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-promocodes.reward"),
            id="reward",
            state=DashboardPromocodes.REWARD,
            when=~F["is_subscription"],
        ),
        Button(
            text=I18nFormat("btn-promocodes.plan"),
            id="plan",
            on_click=on_plan_open,
            when=F["is_subscription"],
        ),
        SwitchTo(
            text=I18nFormat("btn-promocodes.availability"),
            id="availability",
            state=DashboardPromocodes.AVAILABILITY,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-promocodes.expires"),
            id="expires",
            state=DashboardPromocodes.EXPIRES,
        ),
        SwitchTo(
            text=I18nFormat("btn-promocodes.max-activations"),
            id="max_activations",
            state=DashboardPromocodes.MAX_ACTIVATIONS,
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-promocodes.confirm"),
            id="confirm_create",
            on_click=on_promo_confirm,
            style=Style(ButtonStyle.SUCCESS),
            when=~F["is_edit"] & F["can_manage"],
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-promocodes.save"),
            id="confirm_save",
            on_click=on_promo_confirm,
            style=Style(ButtonStyle.SUCCESS),
            when=F["is_edit"] & F["can_manage"],
        ),
        Button(
            text=I18nFormat("btn-promocodes.delete"),
            id="delete_promo",
            on_click=on_delete_promo,
            style=Style(ButtonStyle.DANGER),
            when=F["is_edit"] & F["can_manage"],
        ),
    ),
    Row(
        CopyText(
            text=I18nFormat("btn-promocodes.copy-deeplink"),
            copy_text=Format("{promo_url}"),
            when=F["promo_url"],
        ),
    ),
    Row(
        Start(
            text=I18nFormat("btn-back.general"),
            id="back_list",
            state=DashboardPromocodes.MAIN,
            mode=StartMode.RESET_STACK,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardPromocodes.CONFIGURATOR,
    getter=getter_configurator,
)

code_input = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-promocode-input-code"),
    Row(
        Button(
            text=I18nFormat("btn-promocodes.regenerate"),
            id="regenerate",
            on_click=on_code_regenerate,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardPromocodes.CONFIGURATOR,
        ),
    ),
    MessageInput(func=on_code_input),
    IgnoreUpdate(),
    state=DashboardPromocodes.CODE,
    getter=getter_code,
)

type_select = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-promocode-select-type"),
    ListGroup(
        Row(
            Button(
                text=I18nFormat("promocode-type", promocode_type=F["item"]["value"]),
                id="type_item",
                on_click=on_type_select,
            ),
        ),
        id="types_list",
        item_id_getter=lambda item: item["value"],
        items="types",
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardPromocodes.CONFIGURATOR,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardPromocodes.TYPE,
    getter=getter_type_select,
)

reward_input = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-promocode-input-reward"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardPromocodes.CONFIGURATOR,
        ),
    ),
    MessageInput(func=on_reward_input),
    IgnoreUpdate(),
    state=DashboardPromocodes.REWARD,
    getter=getter_reward,
)

plan_select = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-promocode-select-plan"),
    ListGroup(
        Row(
            Button(
                text=Format("{item[name]}"),
                id="plan_item",
                on_click=on_plan_select,
            ),
        ),
        id="plans_list",
        item_id_getter=lambda item: item["id"],
        items="plans",
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardPromocodes.CONFIGURATOR,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardPromocodes.PLAN,
    getter=getter_plan_select,
)

plan_duration_select = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-promocode-select-plan-duration"),
    ListGroup(
        Row(
            Button(
                text=I18nFormat("btn-promocodes.plan-duration", days=F["item"]["days"]),
                id="plan_duration_item",
                on_click=on_plan_duration_select,
            ),
        ),
        id="plan_durations_list",
        item_id_getter=lambda item: item["days"],
        items="durations",
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardPromocodes.PLAN,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardPromocodes.PLAN_DURATION,
    getter=getter_plan_duration_select,
)

availability_select = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-promocode-select-availability"),
    ListGroup(
        Row(
            Button(
                text=I18nFormat("availability-type", availability_type=F["item"]["value"]),
                id="avail_item",
                on_click=on_availability_select,
            ),
        ),
        id="availability_list",
        item_id_getter=lambda item: item["value"],
        items="availability_types",
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardPromocodes.CONFIGURATOR,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardPromocodes.AVAILABILITY,
    getter=getter_availability_select,
)

expires_input = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-promocode-input-expires"),
    Row(
        Button(
            text=I18nFormat("btn-promocodes.reset"),
            id="reset",
            on_click=on_expires_reset,
            when=F["has_expires"],
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardPromocodes.CONFIGURATOR,
        ),
    ),
    MessageInput(func=on_expires_input),
    IgnoreUpdate(),
    state=DashboardPromocodes.EXPIRES,
    getter=getter_expires,
)

max_activations_input = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-promocode-input-max-activations"),
    Row(
        Button(
            text=I18nFormat("btn-promocodes.reset"),
            id="reset",
            on_click=on_max_activations_reset,
            when=F["has_max_activations"],
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardPromocodes.CONFIGURATOR,
        ),
    ),
    MessageInput(func=on_max_activations_input),
    IgnoreUpdate(),
    state=DashboardPromocodes.MAX_ACTIVATIONS,
    getter=getter_max_activations,
)

router = Dialog(
    promocodes_main,
    configurator,
    code_input,
    type_select,
    reward_input,
    plan_select,
    plan_duration_select,
    availability_select,
    expires_input,
    max_activations_input,
)
