from uuid import UUID

from aiogram_dialog import Dialog, StartMode, Window
from aiogram_dialog.widgets.input import MessageInput
from magic_filter import F
from remnapy.enums.users import TrafficLimitStrategy

from src.core.enums import BannerName
from src.telegram.states import DashboardRemnashop, RemnashopGrace
from src.telegram.widgets import Banner, I18nFormat, IgnoreUpdate
from src.telegram.widgets.kbd import Button, Column, Row, Select, Start, SwitchTo

from .getters import (
    grace_external_squads_getter,
    grace_getter,
    grace_internal_squads_getter,
    grace_strategy_getter,
    grace_value_getter,
)
from .handlers import (
    on_duration_input,
    on_external_squad_select,
    on_internal_squad_select,
    on_strategy_select,
    on_tag_input,
    on_toggle_enabled,
    on_traffic_input,
)

main = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat(
        "msg-remnashop-grace",
        enabled=F["enabled"],
        traffic_mb=F["traffic_mb"],
        strategy_type=F["strategy"],
        value=F["duration_days"],
        tag=F["tag"],
        internal_squads=F["internal_squads"],
        external_squad=F["external_squad"],
    ),
    Row(
        Button(
            text=I18nFormat("btn-remnashop-grace.toggle", enabled=F["enabled"]),
            id="grace_toggle",
            on_click=on_toggle_enabled,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-remnashop-grace.traffic"),
            id="traffic",
            state=RemnashopGrace.TRAFFIC_INPUT,
        ),
        SwitchTo(
            text=I18nFormat("btn-remnashop-grace.strategy"),
            id="strategy",
            state=RemnashopGrace.STRATEGY,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-remnashop-grace.duration"),
            id="duration",
            state=RemnashopGrace.DURATION_INPUT,
        ),
        SwitchTo(
            text=I18nFormat("btn-remnashop-grace.tag"),
            id="tag",
            state=RemnashopGrace.TAG_INPUT,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-remnashop-grace.internal-squads"),
            id="internal_squads",
            state=RemnashopGrace.INTERNAL_SQUADS,
        ),
        SwitchTo(
            text=I18nFormat("btn-remnashop-grace.external-squad"),
            id="external_squad",
            state=RemnashopGrace.EXTERNAL_SQUAD,
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
    state=RemnashopGrace.MAIN,
    getter=grace_getter,
)

traffic_input = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-remnashop-grace-traffic", traffic_mb=F["traffic_mb"]),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopGrace.MAIN,
        ),
    ),
    MessageInput(func=on_traffic_input),
    IgnoreUpdate(),
    state=RemnashopGrace.TRAFFIC_INPUT,
    getter=grace_value_getter,
)

duration_input = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-remnashop-grace-duration", value=F["duration_days"]),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopGrace.MAIN,
        ),
    ),
    MessageInput(func=on_duration_input),
    IgnoreUpdate(),
    state=RemnashopGrace.DURATION_INPUT,
    getter=grace_value_getter,
)

tag_input = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-remnashop-grace-tag", tag=F["tag"]),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopGrace.MAIN,
        ),
    ),
    MessageInput(func=on_tag_input),
    IgnoreUpdate(),
    state=RemnashopGrace.TAG_INPUT,
    getter=grace_value_getter,
)

strategy = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-remnashop-grace-strategy"),
    Column(
        Select(
            text=I18nFormat(
                "btn-plans.traffic-strategy-choice",
                strategy_type=F["item"]["strategy"],
                selected=F["item"]["selected"],
            ),
            id="strategy_select",
            item_id_getter=lambda item: item["strategy"].value,
            items="strategys",
            type_factory=TrafficLimitStrategy,
            on_click=on_strategy_select,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopGrace.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=RemnashopGrace.STRATEGY,
    getter=grace_strategy_getter,
)

internal_squads = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-remnashop-grace-internal-squads"),
    Column(
        Select(
            text=I18nFormat(
                "btn-common.squad-choice",
                name=F["item"]["name"],
                selected=F["item"]["selected"],
            ),
            id="squad_select",
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
            state=RemnashopGrace.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=RemnashopGrace.INTERNAL_SQUADS,
    getter=grace_internal_squads_getter,
)

external_squad = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-remnashop-grace-external-squad"),
    Column(
        Select(
            text=I18nFormat(
                "btn-common.squad-choice",
                name=F["item"]["name"],
                selected=F["item"]["selected"],
            ),
            id="squad_select",
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
            state=RemnashopGrace.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=RemnashopGrace.EXTERNAL_SQUAD,
    getter=grace_external_squads_getter,
)

router = Dialog(
    main,
    traffic_input,
    duration_input,
    tag_input,
    strategy,
    internal_squads,
    external_squad,
)
