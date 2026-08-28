from typing import Any, Callable, Final, Optional

from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram_dialog import StartMode
from aiogram_dialog.widgets.style import Style
from aiogram_dialog.widgets.text import Format
from magic_filter import F

from src.core.constants import DOCS, GOTO_PREFIX, PAYMENT_PREFIX, REPOSITORY, T_ME
from src.core.enums import ButtonType, PurchaseType
from src.telegram.states import DashboardUser, MainMenu, Notification, Subscription
from src.telegram.widgets import I18nFormat
from src.telegram.widgets.kbd import Button, CopyText, Group, ListGroup, Row, Start, Url, WebApp

CALLBACK_CHANNEL_CONFIRM: Final[str] = "channel_confirm"
CALLBACK_RULES_ACCEPT: Final[str] = "rules_accept"


def _type_and_color(btn_type: ButtonType, color: Optional[ButtonStyle]) -> Any:
    base = F["item"].type == btn_type
    return base & (F["item"].color == color)


def _style_kwargs(c: Optional[ButtonStyle]) -> dict[str, Any]:
    return {"style": Style(c)} if c is not None else {}


def build_buttons_row(row: int, text_on_click: Optional[Callable[..., Any]] = None) -> Group:
    url_widgets = [
        Url(
            text=Format("{item.text}"),
            url=Format("{item.payload}"),
            when=_type_and_color(ButtonType.URL, c),
            **_style_kwargs(c),
        )
        for c in (None, *ButtonStyle)
    ]
    copy_widgets = [
        CopyText(
            text=Format("{item.text}"),
            copy_text=Format("{item.payload}"),
            when=_type_and_color(ButtonType.COPY, c),
            **_style_kwargs(c),
        )
        for c in (None, *ButtonStyle)
    ]
    webapp_widgets = [
        WebApp(
            text=Format("{item.text}"),
            url=Format("{item.payload}"),
            when=_type_and_color(ButtonType.WEB_APP, c),
            **_style_kwargs(c),
        )
        for c in (None, *ButtonStyle)
    ]
    text_widgets = [
        Button(
            text=Format("{item.text}"),
            id=f"text_msg_{row}_{c or 'default'}",
            on_click=text_on_click,
            when=_type_and_color(ButtonType.TEXT, c),
            **_style_kwargs(c),
        )
        for c in (None, *ButtonStyle)
    ]

    return Group(
        ListGroup(
            *url_widgets,
            *copy_widgets,
            *webapp_widgets,
            *text_widgets,
            id=f"custom_buttons_row_{row}",
            items=f"row_{row}_buttons",
            item_id_getter=lambda item: item.index,
        ),
        width=2,
    )


custom_buttons = (
    build_buttons_row(1),
    build_buttons_row(2),
    build_buttons_row(3),
)


connect_buttons = (
    WebApp(
        text=I18nFormat("btn-menu.connect"),
        url=Format("{connection_url}"),
        id="connect_miniapp",
        when=F["is_mini_app"] & F["connectable"],
        style=Style(ButtonStyle.PRIMARY),
    ),
    Url(
        text=I18nFormat("btn-menu.connect-reserve"),
        url=Format("{subscription_url}"),
        id="connect_reserve",
        when=F["is_mini_app_reserve"] & F["connectable"],
    ),
    Url(
        text=I18nFormat("btn-menu.connect"),
        url=Format("{connection_url}"),
        id="connect_sub_page",
        when=~F["is_mini_app"] & F["connectable"],
        style=Style(ButtonStyle.PRIMARY),
    ),
)

main_menu_button = (
    Start(
        text=I18nFormat("btn-back.menu"),
        id="back_main_menu",
        state=MainMenu.MAIN,
        mode=StartMode.RESET_STACK,
    ),
)

back_main_menu_button = (
    Row(
        Start(
            text=I18nFormat("btn-back.menu-return"),
            id="back_main_menu",
            state=MainMenu.MAIN,
            mode=StartMode.RESET_STACK,
        ),
    ),
)


CLOSE_BUTTON_ID: Final[int] = -1


def get_close_notification_button() -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text="btn-common.notification-close",
        callback_data=Notification.CLOSE.state,
    )


def get_broadcast_buttons(support_url: str, is_referral_enable: bool) -> list[InlineKeyboardButton]:
    buttons = [
        InlineKeyboardButton(
            text="btn-goto.contact-support",
            url=support_url,
        ),
        InlineKeyboardButton(
            text="btn-goto.subscription",
            callback_data=f"{GOTO_PREFIX}{Subscription.MAIN.state}",
        ),
        InlineKeyboardButton(
            text="btn-goto.promocode",
            callback_data=f"{GOTO_PREFIX}{Subscription.PROMOCODE.state}",
        ),
    ]

    if is_referral_enable:
        buttons.append(
            InlineKeyboardButton(
                text="btn-goto.invite",
                callback_data=f"{GOTO_PREFIX}{MainMenu.INVITE.state}",
            )
        )

    buttons.append(get_close_notification_button())

    return buttons


def get_renew_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="btn-goto.subscription-renew",
            callback_data=f"{GOTO_PREFIX}{PAYMENT_PREFIX}{PurchaseType.RENEW}",
        ),
    )
    return builder.as_markup()


def get_buy_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="btn-goto.subscription",
            callback_data=f"{GOTO_PREFIX}{PAYMENT_PREFIX}{PurchaseType.NEW}",
        ),
    )
    return builder.as_markup()


def get_channel_keyboard(channel_url: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="btn-requirement.channel-join",
            url=channel_url,
            style=ButtonStyle.PRIMARY,
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="btn-requirement.channel-confirm",
            callback_data=CALLBACK_CHANNEL_CONFIRM,
            style=ButtonStyle.SUCCESS,
        ),
    )
    return builder.as_markup()


def get_rules_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="btn-requirement.rules-accept",
            callback_data=CALLBACK_RULES_ACCEPT,
            style=ButtonStyle.SUCCESS,
        ),
    )
    return builder.as_markup()


def get_contact_support_keyboard(support_url: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="btn-goto.contact-support", url=support_url))
    return builder.as_markup()


def get_remnatrishop_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(text="btn-remnashop-info.github", url=REPOSITORY),
        InlineKeyboardButton(text="btn-remnashop-info.telegram", url=f"{T_ME}remna_shop"),
    )

    builder.row(
        InlineKeyboardButton(
            text="btn-remnashop-info.docs",
            url=DOCS,
        )
    )

    builder.row(
        InlineKeyboardButton(
            text="btn-remnashop-info.donate",
            url="https://boosty.to/snoups",
        )
    )

    return builder.as_markup()


def get_remnatrishop_update_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(
            text="btn-remnashop-info.release-latest",
            url=DOCS,
            style=ButtonStyle.PRIMARY,
        ),
        InlineKeyboardButton(
            text="btn-remnashop-info.how-upgrade",
            url=f"{DOCS}/docs/ru/install/update",
            style=ButtonStyle.PRIMARY,
        ),
    )

    return builder.as_markup()


def get_user_keyboard(
    user_id: Optional[int],
    referrer_user_id: Optional[int] = None,
) -> Optional[InlineKeyboardMarkup]:
    if not user_id:
        return None

    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(
            text="btn-goto.user-profile",
            callback_data=f"{GOTO_PREFIX}{DashboardUser.MAIN.state}:{user_id}",
        ),
    )

    if referrer_user_id:
        builder.row(
            InlineKeyboardButton(
                text="btn-goto.referrer-profile",
                callback_data=f"{GOTO_PREFIX}{DashboardUser.MAIN.state}:{referrer_user_id}",
            ),
        )

    return builder.as_markup()


def get_boosty_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(
            text="⚡ BOOSTY",
            url="https://boosty.to/snoups",
        ),
    )

    return builder.as_markup()
