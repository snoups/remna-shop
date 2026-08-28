from aiogram.enums import ButtonStyle
from aiogram_dialog import Dialog, StartMode, Window
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.style import Style
from aiogram_dialog.widgets.text import Format
from magic_filter import F

from src.core.enums import BannerName
from src.telegram.keyboards import main_menu_button
from src.telegram.states import DashboardRemnashop, RemnashopAdvertising
from src.telegram.widgets import Banner, I18nFormat, IgnoreUpdate
from src.telegram.widgets.kbd import Button, CopyText, ListGroup, Row, Start, SwitchTo

from .getters import code_getter, configurator_getter, links_getter, name_getter, stats_getter
from .handlers import (
    on_active_toggle,
    on_code_input,
    on_code_regenerate,
    on_link_confirm,
    on_link_create,
    on_link_delete,
    on_link_select,
    on_name_input,
)

links = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-ad-links-main"),
    Row(
        Button(
            text=I18nFormat("btn-ad-links.create"),
            id="create",
            on_click=on_link_create,
        ),
    ),
    ListGroup(
        Row(
            Button(
                text=I18nFormat(
                    "btn-ad-links.title",
                    name=F["item"]["name"],
                    is_active=F["item"]["is_active"],
                ),
                id="link_select",
                on_click=on_link_select,
            ),
        ),
        id="links_list",
        item_id_getter=lambda item: item["id"],
        items="links",
    ),
    Row(
        Start(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardRemnashop.MAIN,
            mode=StartMode.RESET_STACK,
        ),
        *main_menu_button,
    ),
    IgnoreUpdate(),
    state=RemnashopAdvertising.MAIN,
    getter=links_getter,
)

configurator = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-ad-link-configurator"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-ad-links.stats"),
            id="stats",
            state=RemnashopAdvertising.STATS,
            when=F["is_edit"],
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-ad-links.active-toggle", is_active=F["is_active"]),
            id="active_toggle",
            on_click=on_active_toggle,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-ad-links.name"),
            id="name",
            state=RemnashopAdvertising.NAME,
        ),
        SwitchTo(
            text=I18nFormat("btn-ad-links.code"),
            id="code",
            state=RemnashopAdvertising.CODE,
        ),
    ),
    Row(
        CopyText(
            text=I18nFormat("btn-ad-links.url"),
            copy_text=Format("{link_url}"),
        ),
        when=F["code"] != "0",
    ),
    Row(
        Button(
            text=I18nFormat("btn-ad-links.create-confirm"),
            id="create_confirm",
            on_click=on_link_confirm,
            style=Style(ButtonStyle.SUCCESS),
        ),
        when=~F["is_edit"],
    ),
    Row(
        Button(
            text=I18nFormat("btn-ad-links.save"),
            id="save",
            on_click=on_link_confirm,
            style=Style(ButtonStyle.SUCCESS),
        ),
        Button(
            text=I18nFormat("btn-ad-links.delete"),
            id="delete_link",
            on_click=on_link_delete,
            style=Style(ButtonStyle.DANGER),
        ),
        when=F["is_edit"],
    ),
    Row(
        Start(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopAdvertising.MAIN,
            mode=StartMode.RESET_STACK,
        ),
    ),
    IgnoreUpdate(),
    state=RemnashopAdvertising.CONFIGURATOR,
    getter=configurator_getter,
)

name = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-ad-link-name"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopAdvertising.CONFIGURATOR,
        ),
    ),
    MessageInput(func=on_name_input),
    IgnoreUpdate(),
    state=RemnashopAdvertising.NAME,
    getter=name_getter,
)

code = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-ad-link-code"),
    Row(
        Button(
            text=I18nFormat("btn-ad-links.regenerate"),
            id="regenerate",
            on_click=on_code_regenerate,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopAdvertising.CONFIGURATOR,
        ),
    ),
    MessageInput(func=on_code_input),
    IgnoreUpdate(),
    state=RemnashopAdvertising.CODE,
    getter=code_getter,
)

stats = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat(
        "msg-ad-link-stats",
        name=F["name"],
        registrations=F["registrations"],
        trials=F["trials"],
        buyers=F["buyers"],
        reg_to_buy_rate=F["reg_to_buy_rate"],
        trial_to_buy_rate=F["trial_to_buy_rate"],
        revenue_lines=F["revenue_lines"],
        first_revenue_lines=F["first_revenue_lines"],
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopAdvertising.CONFIGURATOR,
        ),
    ),
    IgnoreUpdate(),
    state=RemnashopAdvertising.STATS,
    getter=stats_getter,
)

router = Dialog(links, configurator, name, code, stats)
