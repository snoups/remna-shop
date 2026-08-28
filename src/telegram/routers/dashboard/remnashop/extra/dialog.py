from aiogram_dialog import Dialog, StartMode, Window
from aiogram_dialog.widgets.input import MessageInput
from magic_filter import F

from src.core.enums import BannerName
from src.telegram.states import DashboardRemnashop, RemnashopExtra, RemnashopGrace
from src.telegram.widgets import Banner, I18nFormat, IgnoreUpdate
from src.telegram.widgets.kbd import Button, Row, Start, SwitchTo

from .getters import extra_getter
from .handlers import (
    on_cooldown_input,
    on_mini_app_reserve_toggle,
    on_stars_paid_requirement_toggle,
    on_toggle,
    on_trial_channel_guard_toggle,
)

main = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-extra-main"),
    Row(
        Start(
            text=I18nFormat("btn-remnashop-extra.grace", enabled=F["grace_enabled"]),
            id="grace",
            state=RemnashopGrace.MAIN,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat(
                "btn-remnashop-extra.device-single",
                enabled=F["device_single_enabled"],
            ),
            id="device_single",
            state=RemnashopExtra.DEVICE_SINGLE,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat(
                "btn-remnashop-extra.device-all",
                enabled=F["device_all_enabled"],
            ),
            id="device_all",
            state=RemnashopExtra.DEVICE_ALL,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat(
                "btn-remnashop-extra.link-reset",
                enabled=F["link_reset_enabled"],
            ),
            id="link_reset",
            state=RemnashopExtra.LINK_RESET,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat(
                "btn-remnashop-extra.referral-reset",
                enabled=F["referral_reset_enabled"],
            ),
            id="referral_reset",
            state=RemnashopExtra.REFERRAL_RESET,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat(
                "btn-remnashop-extra.trial-channel-guard",
                enabled=F["trial_channel_guard_enabled"],
            ),
            id="trial_channel_guard",
            state=RemnashopExtra.TRIAL_CHANNEL_GUARD,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat(
                "btn-remnashop-extra.mini-app-reserve",
                enabled=F["mini_app_reserve_enabled"],
            ),
            id="mini_app_reserve",
            state=RemnashopExtra.MINI_APP_RESERVE,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat(
                "btn-remnashop-extra.stars-paid-requirement",
                enabled=F["stars_paid_requirement_enabled"],
            ),
            id="stars_paid_requirement",
            state=RemnashopExtra.STARS_PAID_REQUIREMENT,
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
    state=RemnashopExtra.MAIN,
    getter=extra_getter,
)

device_single = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat(
        "msg-extra-device-single",
        enabled=F["device_single_enabled"],
        cooldown=F["device_single_cooldown"],
    ),
    Row(
        Button(
            text=I18nFormat("btn-remnashop-extra.toggle", enabled=F["device_single_enabled"]),
            id="device_single_toggle",
            on_click=on_toggle,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopExtra.MAIN,
        ),
    ),
    MessageInput(func=on_cooldown_input),
    IgnoreUpdate(),
    state=RemnashopExtra.DEVICE_SINGLE,
    getter=extra_getter,
)

device_all = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat(
        "msg-extra-device-all",
        enabled=F["device_all_enabled"],
        cooldown=F["device_all_cooldown"],
    ),
    Row(
        Button(
            text=I18nFormat("btn-remnashop-extra.toggle", enabled=F["device_all_enabled"]),
            id="device_all_toggle",
            on_click=on_toggle,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopExtra.MAIN,
        ),
    ),
    MessageInput(func=on_cooldown_input),
    IgnoreUpdate(),
    state=RemnashopExtra.DEVICE_ALL,
    getter=extra_getter,
)

link_reset = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat(
        "msg-extra-link-reset",
        enabled=F["link_reset_enabled"],
        cooldown=F["link_reset_cooldown"],
    ),
    Row(
        Button(
            text=I18nFormat("btn-remnashop-extra.toggle", enabled=F["link_reset_enabled"]),
            id="link_toggle",
            on_click=on_toggle,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopExtra.MAIN,
        ),
    ),
    MessageInput(func=on_cooldown_input),
    IgnoreUpdate(),
    state=RemnashopExtra.LINK_RESET,
    getter=extra_getter,
)

referral_reset = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat(
        "msg-extra-referral-reset",
        enabled=F["referral_reset_enabled"],
        cooldown=F["referral_reset_cooldown"],
    ),
    Row(
        Button(
            text=I18nFormat("btn-remnashop-extra.toggle", enabled=F["referral_reset_enabled"]),
            id="referral_toggle",
            on_click=on_toggle,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopExtra.MAIN,
        ),
    ),
    MessageInput(func=on_cooldown_input),
    IgnoreUpdate(),
    state=RemnashopExtra.REFERRAL_RESET,
    getter=extra_getter,
)

trial_channel_guard = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat(
        "msg-extra-trial-channel-guard",
        enabled=F["trial_channel_guard_enabled"],
    ),
    Row(
        Button(
            text=I18nFormat(
                "btn-remnashop-extra.toggle",
                enabled=F["trial_channel_guard_enabled"],
            ),
            id="trial_channel_guard_toggle",
            on_click=on_trial_channel_guard_toggle,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopExtra.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=RemnashopExtra.TRIAL_CHANNEL_GUARD,
    getter=extra_getter,
)

mini_app_reserve = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat(
        "msg-extra-mini-app-reserve",
        enabled=F["mini_app_reserve_enabled"],
    ),
    Row(
        Button(
            text=I18nFormat(
                "btn-remnashop-extra.toggle",
                enabled=F["mini_app_reserve_enabled"],
            ),
            id="mini_app_reserve_toggle",
            on_click=on_mini_app_reserve_toggle,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopExtra.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=RemnashopExtra.MINI_APP_RESERVE,
    getter=extra_getter,
)

stars_paid_requirement = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat(
        "msg-extra-stars-paid-requirement",
        enabled=F["stars_paid_requirement_enabled"],
    ),
    Row(
        Button(
            text=I18nFormat(
                "btn-remnashop-extra.toggle",
                enabled=F["stars_paid_requirement_enabled"],
            ),
            id="stars_paid_requirement_toggle",
            on_click=on_stars_paid_requirement_toggle,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopExtra.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=RemnashopExtra.STARS_PAID_REQUIREMENT,
    getter=extra_getter,
)

router = Dialog(
    main,
    device_single,
    device_all,
    link_reset,
    referral_reset,
    trial_channel_guard,
    mini_app_reserve,
    stars_paid_requirement,
)
