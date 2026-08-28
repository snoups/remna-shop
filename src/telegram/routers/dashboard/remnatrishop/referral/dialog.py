from aiogram_dialog import Dialog, Window
from aiogram_dialog.widgets.input import MessageInput
from magic_filter import F

from src.core.enums import (
    BannerName,
    ReferralAccrualStrategy,
    ReferralRewardStrategy,
    ReferralRewardType,
)
from src.telegram.keyboards import main_menu_button
from src.telegram.states import DashboardRemnashop, RemnashopReferral
from src.telegram.widgets import Banner, I18nFormat, IgnoreUpdate
from src.telegram.widgets.kbd import Button, Column, Row, Select, Start, SwitchTo

from .getters import (
    accrual_strategy_getter,
    level_getter,
    referral_getter,
    reward_getter,
    reward_strategy_getter,
    reward_type_getter,
)
from .handlers import (
    on_accrual_strategy_select,
    on_enable_toggle,
    on_level_select,
    on_reward_input,
    on_reward_select,
    on_reward_strategy_select,
)

referral = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-referral-main"),
    Row(
        Button(
            text=I18nFormat("btn-referral.active-toggle"),
            id="enable",
            on_click=on_enable_toggle,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-referral.level"),
            id="level",
            state=RemnashopReferral.LEVEL,
        ),
        SwitchTo(
            text=I18nFormat("btn-referral.reward-type"),
            id="reward_type",
            state=RemnashopReferral.REWARD_TYPE,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-referral.accrual-strategy"),
            id="accrual_strategy",
            state=RemnashopReferral.ACCRUAL_STRATEGY,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-referral.reward-strategy"),
            id="reward_strategy",
            state=RemnashopReferral.REWARD_STRATEGY,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-referral.reward"),
            id="reward",
            state=RemnashopReferral.REWARD,
        ),
    ),
    Row(
        Start(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardRemnashop.MAIN,
        ),
        *main_menu_button,
    ),
    IgnoreUpdate(),
    state=RemnashopReferral.MAIN,
    getter=referral_getter,
)

level = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-referral-level"),
    Row(
        Select(
            text=I18nFormat("btn-referral.level-choice", type=F["item"]),
            id="select_level",
            item_id_getter=lambda item: item.value,
            items="levels",
            type_factory=int,
            on_click=on_level_select,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopReferral.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=RemnashopReferral.LEVEL,
    getter=level_getter,
)

reward_type = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-referral-reward-type"),
    Column(
        Select(
            text=I18nFormat("btn-referral.reward-choice", type=F["item"]),
            id="select_reward",
            item_id_getter=lambda item: item.value,
            items="rewards",
            type_factory=ReferralRewardType,
            on_click=on_reward_select,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopReferral.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=RemnashopReferral.REWARD_TYPE,
    getter=reward_type_getter,
)

reward = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-referral-reward"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopReferral.MAIN,
        ),
    ),
    MessageInput(func=on_reward_input),
    IgnoreUpdate(),
    state=RemnashopReferral.REWARD,
    getter=reward_getter,
)

accrual_strategy = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-referral-accrual-strategy"),
    Column(
        Select(
            text=I18nFormat("btn-referral.accrual-strategy-choice", type=F["item"]),
            id="select_strategy",
            item_id_getter=lambda item: item.value,
            items="strategys",
            type_factory=ReferralAccrualStrategy,
            on_click=on_accrual_strategy_select,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopReferral.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=RemnashopReferral.ACCRUAL_STRATEGY,
    getter=accrual_strategy_getter,
)

reward_strategy = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-referral-reward-strategy"),
    Column(
        Select(
            text=I18nFormat("btn-referral.reward-strategy-choice", type=F["item"]),
            id="select_strategy",
            item_id_getter=lambda item: item.value,
            items="strategys",
            type_factory=ReferralRewardStrategy,
            on_click=on_reward_strategy_select,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopReferral.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=RemnashopReferral.REWARD_STRATEGY,
    getter=reward_strategy_getter,
)

router = Dialog(
    referral,
    level,
    reward_type,
    accrual_strategy,
    reward_strategy,
    reward,
)
