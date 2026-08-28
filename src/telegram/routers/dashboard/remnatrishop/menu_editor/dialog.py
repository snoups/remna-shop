from aiogram.enums import ButtonStyle
from aiogram_dialog import Dialog, StartMode, Window
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.style import Style
from magic_filter import F

from src.core.enums import BannerName, ButtonType
from src.telegram.keyboards import main_menu_button
from src.telegram.states import DashboardRemnashop, RemnashopMenuEditor
from src.telegram.widgets import Banner, I18nFormat, IgnoreUpdate
from src.telegram.widgets.kbd import Button, Column, Group, Row, Select, Start, SwitchTo

from .getters import availability_getter, button_getter, menu_editor_getter, type_getter
from .handlers import (
    on_active_toggle,
    on_availability_select,
    on_button_selected,
    on_color_select,
    on_confirm,
    on_payload_input,
    on_subscribers_only_toggle,
    on_text_input,
    on_type_select,
)

menu_editor = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-menu-editor-main"),
    Group(
        Select(
            text=I18nFormat(
                "btn-menu-editor.button",
                text=F["item"]["text"],
                is_active=F["item"]["is_active"],
            ),
            id="menu_grid",
            item_id_getter=lambda x: x["index"],
            items="buttons",
            type_factory=int,
            on_click=on_button_selected,
        ),
        width=2,
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
    state=RemnashopMenuEditor.MAIN,
    getter=menu_editor_getter,
)

button = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-menu-editor-button", button_type=F["type"], role=F["required_role"]),
    Row(
        Button(
            text=I18nFormat("btn-menu-editor.active-toggle", is_active=F["is_active"]),
            id="active_toggle",
            on_click=on_active_toggle,
        ),
    ),
    Row(
        Button(
            text=I18nFormat(
                "btn-menu-editor.subscribers-only-toggle",
                subscribers_only=F["subscribers_only"],
            ),
            id="subscribers_only_toggle",
            on_click=on_subscribers_only_toggle,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-menu-editor.text"),
            id="text",
            state=RemnashopMenuEditor.TEXT,
        ),
        SwitchTo(
            text=I18nFormat("btn-menu-editor.availability"),
            id="availability",
            state=RemnashopMenuEditor.AVAILABILITY,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-menu-editor.type"),
            id="type",
            state=RemnashopMenuEditor.TYPE,
        ),
        SwitchTo(
            text=I18nFormat("btn-menu-editor.payload"),
            id="payload",
            state=RemnashopMenuEditor.PAYLOAD,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-menu-editor.color"),
            id="color",
            state=RemnashopMenuEditor.COLOR,
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-menu-editor.confirm"),
            id="confirm",
            on_click=on_confirm,
        ),
    ),
    Row(
        Start(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopMenuEditor.MAIN,
            mode=StartMode.RESET_STACK,
        ),
    ),
    IgnoreUpdate(),
    state=RemnashopMenuEditor.BUTTON,
    getter=button_getter,
)

button_text = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-menu-editor-button-text"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopMenuEditor.BUTTON,
        ),
    ),
    MessageInput(func=on_text_input),
    IgnoreUpdate(),
    state=RemnashopMenuEditor.TEXT,
)

button_availability = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-menu-editor-button-availability"),
    Column(
        Select(
            text=I18nFormat("role", role=F["item"]),
            id="availability_select",
            item_id_getter=lambda item: item.value,
            items="availability",
            type_factory=int,
            on_click=on_availability_select,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopMenuEditor.BUTTON,
        ),
    ),
    IgnoreUpdate(),
    state=RemnashopMenuEditor.AVAILABILITY,
    getter=availability_getter,
)

button_type = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-menu-editor-button-type"),
    Column(
        Select(
            text=I18nFormat(
                "button-type",
                button_type=F["item"],
            ),
            id="type_select",
            item_id_getter=lambda item: item,
            items="types",
            type_factory=ButtonType,
            on_click=on_type_select,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopMenuEditor.BUTTON,
        ),
    ),
    IgnoreUpdate(),
    state=RemnashopMenuEditor.TYPE,
    getter=type_getter,
)

button_payload = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-menu-editor-button-payload", button_type=F["type"]),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopMenuEditor.BUTTON,
        ),
    ),
    MessageInput(func=on_payload_input),
    IgnoreUpdate(),
    state=RemnashopMenuEditor.PAYLOAD,
    getter=button_getter,
)

button_color = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-menu-editor-button-color"),
    Row(
        Button(
            text=I18nFormat("btn-menu-editor.color-default"),
            id="color_default",
            on_click=on_color_select,
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-menu-editor.color-primary"),
            id="color_primary",
            on_click=on_color_select,
            style=Style(ButtonStyle.PRIMARY),
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-menu-editor.color-success"),
            id="color_success",
            on_click=on_color_select,
            style=Style(ButtonStyle.SUCCESS),
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-menu-editor.color-danger"),
            id="color_danger",
            on_click=on_color_select,
            style=Style(ButtonStyle.DANGER),
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopMenuEditor.BUTTON,
        ),
    ),
    IgnoreUpdate(),
    state=RemnashopMenuEditor.COLOR,
)

router = Dialog(
    menu_editor,
    button,
    button_text,
    button_availability,
    button_type,
    button_payload,
    button_color,
)
