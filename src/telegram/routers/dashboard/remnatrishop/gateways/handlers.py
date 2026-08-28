from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, ShowMode
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, Select
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from loguru import logger

from src.application.common import Notifier
from src.application.common.dao import PaymentGatewayDao
from src.application.dto import MessagePayloadDto, TelegramUserDto
from src.application.use_cases.gateways.commands.configuration import (
    MovePaymentGatewayUp,
    ResetPaymentGatewaySettingsDto,
    ResetPaymentGatewaySettingsField,
    TogglePaymentGatewayActive,
    UpdatePaymentGatewaySettings,
    UpdatePaymentGatewaySettingsDto,
)
from src.application.use_cases.gateways.commands.payment import CreateTestPayment
from src.application.use_cases.settings.commands.currency import UpdateDefaultCurrency
from src.core.constants import USER_KEY
from src.core.enums import Currency
from src.core.exceptions import GatewayNotConfiguredError
from src.telegram.states import RemnashopGateways


@inject
async def on_gateway_select(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    payment_gateway_dao: FromDishka[PaymentGatewayDao],
    notifier: FromDishka[Notifier],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    gateway_id = int(dialog_manager.item_id)  # type: ignore[attr-defined]
    gateway = await payment_gateway_dao.get_by_id(gateway_id)

    if not gateway:
        raise ValueError(f"Attempted to select non-existent gateway '{gateway_id}'")

    logger.info(f"{user.log} Gateway '{gateway_id}' selected")

    if not gateway.settings:
        await notifier.notify_user(user, i18n_key="ntf-gateway.not-configurable")
        return

    dialog_manager.dialog_data["gateway_id"] = gateway_id
    await dialog_manager.switch_to(state=RemnashopGateways.SETTINGS)


@inject
async def on_gateway_test(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    payment_gateway_dao: FromDishka[PaymentGatewayDao],
    create_test_payment: FromDishka[CreateTestPayment],
    notifier: FromDishka[Notifier],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    gateway_id = int(dialog_manager.item_id)  # type: ignore[attr-defined]
    gateway = await payment_gateway_dao.get_by_id(gateway_id)

    if not gateway:
        raise ValueError(f"Attempted to test non-existent gateway '{gateway_id}'")

    if gateway.settings and not gateway.settings.is_configured:
        logger.warning(f"{user.log} Gateway '{gateway_id}' is not configured")
        await notifier.notify_user(user, i18n_key="ntf-gateway.not-configured")
        return

    logger.info(f"{user.log} Testing gateway '{gateway_id}'")

    try:
        payment = await create_test_payment(user, gateway.type)
        await notifier.notify_user(
            user=user,
            payload=MessagePayloadDto(
                i18n_key="ntf-gateway.test-payment-created",
                i18n_kwargs={"url": payment.url},
            ),
        )

    except Exception as e:
        logger.exception(
            f"{user.log} Test payment failed for gateway '{gateway_id}'. Exception: {e}"
        )
        await notifier.notify_user(user, i18n_key="ntf-gateway.test-payment-error")


@inject
async def on_active_toggle(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    toggle_payment_gateway_active: FromDishka[TogglePaymentGatewayActive],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    gateway_id = int(dialog_manager.item_id)  # type: ignore[attr-defined]

    try:
        await toggle_payment_gateway_active(user, gateway_id)
    except GatewayNotConfiguredError:
        await notifier.notify_user(user, i18n_key="ntf-gateway.not-configured")


async def on_field_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_field: str,
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    dialog_manager.dialog_data["selected_field"] = selected_field
    logger.info(f"{user.log} Selected field '{selected_field}' for editing")
    await dialog_manager.switch_to(state=RemnashopGateways.FIELD)


@inject
async def on_field_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    update_payment_gateway_settings: FromDishka[UpdatePaymentGatewaySettings],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    gateway_id = dialog_manager.dialog_data["gateway_id"]
    selected_field = dialog_manager.dialog_data["selected_field"]

    if not message.text:
        logger.warning(f"{user.log} Empty input for field '{selected_field}'")
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    # display_name may carry custom (premium) emoji, preserved as <tg-emoji> tags
    value = message.html_text if selected_field == "display_name" else message.text

    try:
        await update_payment_gateway_settings(
            user,
            UpdatePaymentGatewaySettingsDto(
                gateway_id=gateway_id,
                field_name=selected_field,
                value=value,
            ),
        )
        await dialog_manager.switch_to(state=RemnashopGateways.SETTINGS)
    except ValueError:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")


@inject
async def on_field_reset(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    reset_field: FromDishka[ResetPaymentGatewaySettingsField],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    gateway_id = dialog_manager.dialog_data["gateway_id"]
    selected_field = dialog_manager.dialog_data["selected_field"]

    deactivated = await reset_field(
        user,
        ResetPaymentGatewaySettingsDto(gateway_id=gateway_id, field_name=selected_field),
    )

    i18n_key = "ntf-gateway.field-reset-deactivated" if deactivated else "ntf-gateway.field-reset"
    await notifier.notify_user(user, i18n_key=i18n_key)
    await dialog_manager.switch_to(state=RemnashopGateways.SETTINGS)


@inject
async def on_default_currency_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_currency: Currency,
    update_default_currency: FromDishka[UpdateDefaultCurrency],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    await update_default_currency(user, selected_currency)


@inject
async def on_gateway_move(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    move_payment_gateway_up: FromDishka[MovePaymentGatewayUp],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    gateway_id = int(dialog_manager.item_id)  # type: ignore[attr-defined]
    await move_payment_gateway_up(user, gateway_id)
