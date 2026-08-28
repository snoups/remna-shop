from typing import Optional
from uuid import UUID

from adaptix import Retort
from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, ShowMode, StartMode
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, Select
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from loguru import logger

from src.application.common import BotService, Notifier, Redirect, TranslatorRunner
from src.application.common.dao import PlanDao, SubscriptionDao, TransactionDao, UserDao
from src.application.dto import MessagePayloadDto, TelegramUserDto
from src.application.use_cases.gateways.commands.payment import RetryFailedTransaction
from src.application.use_cases.plan.commands.access import (
    ToggleUserPlanAccess,
    ToggleUserPlanAccessDto,
)
from src.application.use_cases.remnawave.commands.management import (
    DeleteUserDevice,
    DeleteUserDeviceDto,
    ReissueUserSubscription,
    ResetUserTraffic,
)
from src.application.use_cases.subscription.commands.management import (
    AddSubscriptionDuration,
    AddSubscriptionDurationDto,
    DeleteSubscription,
    ToggleExternalSquad,
    ToggleExternalSquadDto,
    ToggleInternalSquad,
    ToggleInternalSquadDto,
    ToggleSubscriptionStatus,
    UpdateDeviceLimit,
    UpdateDeviceLimitDto,
    UpdateTrafficLimit,
    UpdateTrafficLimitDto,
)
from src.application.use_cases.subscription.commands.set_plan import (
    SetUserSubscription,
    SetUserSubscriptionDto,
)
from src.application.use_cases.subscription.commands.sync import (
    CheckSubscriptionSyncState,
    SyncSubscriptionFromRemnashop,
    SyncSubscriptionFromRemnawave,
)
from src.application.use_cases.user.commands.blocking import ToggleUserBlockedStatus
from src.application.use_cases.user.commands.messaging import (
    SendMessageToUser,
    SendMessageToUserDto,
)
from src.application.use_cases.user.commands.profile_edit import (
    ChangeUserPoints,
    ChangeUserPointsDto,
    ResetUserReferralCode,
    SetUserPersonalDiscount,
    SetUserPersonalDiscountDto,
    SetUserPurchaseDiscount,
    SetUserPurchaseDiscountDto,
    ToggleUserTrialAvailable,
)
from src.application.use_cases.user.commands.roles import SetUserRole, SetUserRoleDto
from src.application.use_cases.user.queries.plans import GetAvailablePlans
from src.application.use_cases.user.queries.profile import GetUserDevices
from src.core.constants import (
    FROM_REFERRAL_USER_ID,
    TARGET_TELEGRAM_ID,
    TARGET_USER_ID,
    USER_KEY,
    USER_LIST_ORIGIN,
    USER_LIST_PAYLOAD,
)
from src.core.enums import Role
from src.core.exceptions import PurchaseError, TransactionNotRetryableError
from src.core.utils.validators import is_positive_int, parse_int
from src.telegram.keyboards import get_contact_support_keyboard
from src.telegram.states import DashboardUser, DashboardUsers
from src.telegram.utils import is_double_click

_USER_LIST_STATES = {
    DashboardUsers.RECENT_REGISTERED.state: DashboardUsers.RECENT_REGISTERED,
    DashboardUsers.RECENT_ACTIVITY.state: DashboardUsers.RECENT_ACTIVITY,
    DashboardUsers.BLACKLIST_USERS.state: DashboardUsers.BLACKLIST_USERS,
    DashboardUsers.SEARCH_RESULTS.state: DashboardUsers.SEARCH_RESULTS,
}


async def start_user_window(
    manager: DialogManager,
    target_user_id: int,
    from_referral_user_id: Optional[int] = None,
    list_origin: Optional[str] = None,
    list_payload: Optional[list] = None,
) -> None:
    data: dict = {TARGET_USER_ID: target_user_id}
    if from_referral_user_id is not None:
        data[FROM_REFERRAL_USER_ID] = from_referral_user_id
    if list_origin is not None:
        data[USER_LIST_ORIGIN] = list_origin
    if list_payload is not None:
        data[USER_LIST_PAYLOAD] = list_payload
    await manager.start(
        state=DashboardUser.MAIN,
        data=data,
        mode=StartMode.RESET_STACK,
    )


async def on_back_to_list(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
) -> None:
    origin = dialog_manager.start_data.get(USER_LIST_ORIGIN)  # type: ignore[union-attr]
    state = _USER_LIST_STATES.get(origin) if origin else None

    if state is None:
        await dialog_manager.start(state=DashboardUsers.MAIN, mode=StartMode.RESET_STACK)
        return

    data: dict = {}
    if state == DashboardUsers.SEARCH_RESULTS:
        payload = dialog_manager.start_data.get(USER_LIST_PAYLOAD)  # type: ignore[union-attr]
        if not payload:
            await dialog_manager.start(state=DashboardUsers.MAIN, mode=StartMode.RESET_STACK)
            return
        data["found_users"] = payload

    await dialog_manager.start(state=state, data=data, mode=StartMode.RESET_STACK)


async def start_user_transaction_window(
    manager: DialogManager,
    target_user_id: int,
    selected_transaction: UUID,
    origin: str = "user",
) -> None:
    await manager.start(
        state=DashboardUser.TRANSACTION,
        data={
            TARGET_USER_ID: target_user_id,
            "selected_transaction": str(selected_transaction),
            "origin": origin,
        },
        mode=StartMode.RESET_STACK,
    )


async def on_user_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_user: int,
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    logger.info(f"{user.log} User id '{selected_user}' selected")
    parent_user_id: int = dialog_manager.dialog_data[TARGET_USER_ID]
    await start_user_window(
        manager=dialog_manager,
        target_user_id=selected_user,
        from_referral_user_id=parent_user_id,
    )


async def on_back_to_referrals(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
) -> None:
    from_referral_user_id: int = dialog_manager.dialog_data[FROM_REFERRAL_USER_ID]
    await dialog_manager.start(
        state=DashboardUser.REFERRALS,
        data={TARGET_USER_ID: from_referral_user_id},
        mode=StartMode.RESET_STACK,
    )


@inject
async def on_block_toggle(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    toggle_user_blocked_status: FromDishka[ToggleUserBlockedStatus],
    redirect: FromDishka[Redirect],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]
    target_telegram_id = dialog_manager.dialog_data.get(TARGET_TELEGRAM_ID)
    await toggle_user_blocked_status(user, target_user_id)
    if target_telegram_id:
        await redirect.to_main_menu(target_telegram_id)


@inject
async def on_trial_toggle(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    toggle_user_trial_available: FromDishka[ToggleUserTrialAvailable],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]
    await toggle_user_trial_available(user, target_user_id)


@inject
async def on_referral_reset(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    reset_user_referral_code: FromDishka[ResetUserReferralCode],
    notifier: FromDishka[Notifier],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]

    if is_double_click(dialog_manager, key="referral_reset_confirm", cooldown=10):
        await reset_user_referral_code(user, target_user_id)
        await notifier.notify_user(user, i18n_key="ntf-user.referral-reset")
        return

    await notifier.notify_user(user, i18n_key="ntf-common.double-click-confirm")


@inject
async def on_role_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_role: Role,
    set_user_role: FromDishka[SetUserRole],
    redirect: FromDishka[Redirect],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]
    target_telegram_id = dialog_manager.dialog_data.get(TARGET_TELEGRAM_ID)
    await set_user_role(user, SetUserRoleDto(target_user_id, Role(selected_role)))
    if target_telegram_id:
        await redirect.to_main_menu(target_telegram_id)


@inject
async def on_current_subscription(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    subscription_dao: FromDishka[SubscriptionDao],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]

    subscription = await subscription_dao.get_current(target_user_id)

    if not subscription:
        await notifier.notify_user(user, i18n_key="ntf-user.subscription-empty")
        return

    await dialog_manager.switch_to(state=DashboardUser.SUBSCRIPTION)


@inject
async def on_active_toggle(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    toggle_subscription_status: FromDishka[ToggleSubscriptionStatus],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]
    await toggle_subscription_status(user, target_user_id)


@inject
async def on_subscription_delete(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    delete_subscription: FromDishka[DeleteSubscription],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]

    if is_double_click(dialog_manager, key="subscription_delete_confirm", cooldown=10):
        await delete_subscription(user, target_user_id)

        await notifier.notify_user(user, i18n_key="ntf-user.subscription-deleted")
        await dialog_manager.switch_to(state=DashboardUser.MAIN)
        return

    await notifier.notify_user(user, i18n_key="ntf-common.double-click-confirm")
    logger.debug(
        f"{user.log} Waiting for confirmation to delete subscription for user '{target_user_id}'"
    )


@inject
async def on_devices(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    get_user_devices: FromDishka[GetUserDevices],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]
    user_devices = await get_user_devices(user, target_user_id)

    if not user_devices.current_count:
        await notifier.notify_user(user, i18n_key="ntf-user.devices-empty")
        return

    await dialog_manager.switch_to(state=DashboardUser.DEVICES_LIST)


@inject
async def on_device_delete(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    delete_user_device: FromDishka[DeleteUserDevice],
) -> None:
    selected_short_hwid = dialog_manager.item_id  # type: ignore[attr-defined]
    hwid_map: list[dict] = dialog_manager.dialog_data.get("hwid_map")  # type: ignore[assignment]

    full_hwid = next((d["hwid"] for d in hwid_map if d["short_hwid"] == selected_short_hwid), None)

    if not full_hwid:
        raise ValueError(f"Full HWID not found for '{selected_short_hwid}'")

    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]
    has_devices = await delete_user_device(user, DeleteUserDeviceDto(target_user_id, full_hwid))

    if not has_devices:
        await dialog_manager.switch_to(state=DashboardUser.SUBSCRIPTION)


@inject
async def on_reset_traffic(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    reset_user_traffic: FromDishka[ResetUserTraffic],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]
    await reset_user_traffic(user, target_user_id)


@inject
async def on_reissue_subscription(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    reissue_user_subscription: FromDishka[ReissueUserSubscription],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]

    if is_double_click(dialog_manager, key="reissue_subscription_confirm", cooldown=10):
        await reissue_user_subscription(user, target_user_id)
        await notifier.notify_user(user, i18n_key="ntf-devices.reissued")
        return

    await notifier.notify_user(user, i18n_key="ntf-common.double-click-confirm")


@inject
async def on_personal_discount_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_discount: int,
    set_user_personal_discount: FromDishka[SetUserPersonalDiscount],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]

    await set_user_personal_discount(
        user,
        SetUserPersonalDiscountDto(target_user_id, selected_discount),
    )

    await dialog_manager.switch_to(state=DashboardUser.DISCOUNT)


@inject
async def on_personal_discount_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    set_user_personal_discount: FromDishka[SetUserPersonalDiscount],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]

    number = parse_int(message.text)
    if number is None:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    try:
        await set_user_personal_discount(
            user,
            SetUserPersonalDiscountDto(target_user_id, discount=number),
        )
        await dialog_manager.switch_to(state=DashboardUser.DISCOUNT)
    except ValueError:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")


@inject
async def on_purchase_discount_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_discount: int,
    set_user_purchase_discount: FromDishka[SetUserPurchaseDiscount],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]

    await set_user_purchase_discount(
        user,
        SetUserPurchaseDiscountDto(target_user_id, selected_discount),
    )

    await dialog_manager.switch_to(state=DashboardUser.DISCOUNT)


@inject
async def on_purchase_discount_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    set_user_purchase_discount: FromDishka[SetUserPurchaseDiscount],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]

    number = parse_int(message.text)
    if number is None:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    try:
        await set_user_purchase_discount(
            user,
            SetUserPurchaseDiscountDto(target_user_id, discount=number),
        )
        await dialog_manager.switch_to(state=DashboardUser.DISCOUNT)
    except ValueError:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")


@inject
async def on_points_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    change_user_points: FromDishka[ChangeUserPoints],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]
    number = parse_int(message.text)

    if number is None:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    try:
        await change_user_points(user, ChangeUserPointsDto(user_id=target_user_id, amount=number))
    except ValueError:
        await notifier.notify_user(
            user=user,
            payload=MessagePayloadDto(
                i18n_key="ntf-user.invalid-points",
                i18n_kwargs={"operation": "ADD" if number > 0 else "SUB"},
            ),
        )


@inject
async def on_points_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_points: int,
    notifier: FromDishka[Notifier],
    change_user_points: FromDishka[ChangeUserPoints],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    logger.info(f"{user.log} Selected points '{selected_points}'")
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]

    try:
        await change_user_points(
            user, ChangeUserPointsDto(user_id=target_user_id, amount=selected_points)
        )
    except ValueError:
        await notifier.notify_user(
            user=user,
            payload=MessagePayloadDto(
                i18n_key="ntf-user.invalid-points",
                i18n_kwargs={"operation": "ADD" if selected_points > 0 else "SUB"},
            ),
        )


@inject
async def on_traffic_limit_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_traffic: int,
    update_traffic_limit: FromDishka[UpdateTrafficLimit],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]
    await update_traffic_limit(user, UpdateTrafficLimitDto(target_user_id, selected_traffic))
    await dialog_manager.switch_to(state=DashboardUser.SUBSCRIPTION)


@inject
async def on_traffic_limit_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    update_traffic_limit: FromDishka[UpdateTrafficLimit],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]

    if not is_positive_int(message.text):
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    await update_traffic_limit(user, UpdateTrafficLimitDto(target_user_id, int(message.text)))  # type: ignore[arg-type]
    await dialog_manager.switch_to(state=DashboardUser.SUBSCRIPTION)


@inject
async def on_device_limit_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_device: int,
    update_device_limit: FromDishka[UpdateDeviceLimit],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]
    await update_device_limit(user, UpdateDeviceLimitDto(target_user_id, selected_device))
    await dialog_manager.switch_to(state=DashboardUser.SUBSCRIPTION)


@inject
async def on_device_limit_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    update_device_limit: FromDishka[UpdateDeviceLimit],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]

    if not is_positive_int(message.text):
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    await update_device_limit(user, UpdateDeviceLimitDto(target_user_id, int(message.text)))  # type: ignore[arg-type]
    await dialog_manager.switch_to(state=DashboardUser.SUBSCRIPTION)


@inject
async def on_internal_squad_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_squad: UUID,
    toggle_internal_squad: FromDishka[ToggleInternalSquad],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]
    await toggle_internal_squad(user, ToggleInternalSquadDto(target_user_id, selected_squad))


@inject
async def on_external_squad_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_squad: UUID,
    toggle_external_squad: FromDishka[ToggleExternalSquad],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]
    await toggle_external_squad(user, ToggleExternalSquadDto(target_user_id, selected_squad))


@inject
async def on_transactions(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    transaction_dao: FromDishka[TransactionDao],
    notifier: FromDishka[Notifier],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]
    transactions = await transaction_dao.get_by_user(target_user_id)

    if not transactions:
        await notifier.notify_user(user, i18n_key="ntf-user.transactions-empty")
        return

    await dialog_manager.switch_to(state=DashboardUser.TRANSACTIONS_LIST)


async def on_transaction_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_transaction: UUID,
) -> None:
    dialog_manager.dialog_data["selected_transaction"] = selected_transaction
    await dialog_manager.switch_to(state=DashboardUser.TRANSACTION)


@inject
async def on_grant_failed_subscription(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    retry_failed_transaction: FromDishka[RetryFailedTransaction],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    payment_id: UUID = dialog_manager.dialog_data["selected_transaction"]

    try:
        await retry_failed_transaction(user, payment_id)
        await notifier.notify_user(user, i18n_key="ntf-user.transaction-granted")
    except PurchaseError:
        await notifier.notify_user(user, i18n_key="ntf-user.transaction-grant-failed")
    except TransactionNotRetryableError:
        await notifier.notify_user(user, i18n_key="ntf-user.transaction-grant-stale")
    except ValueError:
        # Transaction vanished between opening the window and the click.
        logger.warning(f"{user.log} Transaction '{payment_id}' not found for grant")
        await notifier.notify_user(user, i18n_key="ntf-user.transaction-grant-stale")


async def on_go_to_user(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
) -> None:
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]
    await start_user_window(manager=dialog_manager, target_user_id=target_user_id)


@inject
async def on_give_access(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    plan_dao: FromDishka[PlanDao],
    notifier: FromDishka[Notifier],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    plans = await plan_dao.get_active_allowed_plans()

    if not plans:
        await notifier.notify_user(user, i18n_key="ntf-user.allowed-plans-empty")
        return

    await dialog_manager.switch_to(state=DashboardUser.GIVE_ACCESS)


@inject
async def on_plan_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_plan_id: int,
    toggle_access: FromDishka[ToggleUserPlanAccess],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    logger.info(f"{user.log} Selected plan '{selected_plan_id}'")
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]
    await toggle_access(
        user, ToggleUserPlanAccessDto(plan_id=selected_plan_id, user_id=target_user_id)
    )


@inject
async def on_duration_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_duration: int,
    notifier: FromDishka[Notifier],
    add_subscription_duration: FromDishka[AddSubscriptionDuration],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]

    try:
        await add_subscription_duration(
            user,
            AddSubscriptionDurationDto(user_id=target_user_id, days=selected_duration),
        )
    except ValueError:
        await notifier.notify_user(
            user=user,
            payload=MessagePayloadDto(
                i18n_key="ntf-user.invalid-expire-time",
                i18n_kwargs={"operation": "ADD" if selected_duration > 0 else "SUB"},
            ),
        )


@inject
async def on_duration_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    add_subscription_duration: FromDishka[AddSubscriptionDuration],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]

    number = parse_int(message.text)
    if number is None:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    try:
        await add_subscription_duration(
            user,
            AddSubscriptionDurationDto(user_id=target_user_id, days=number),
        )
    except ValueError:
        await notifier.notify_user(
            user=user,
            payload=MessagePayloadDto(
                i18n_key="ntf-user.invalid-expire-time",
                i18n_kwargs={"operation": "ADD" if number > 0 else "SUB"},
            ),
        )


@inject
async def on_send(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    notifier: FromDishka[Notifier],
    send_message_to_user: FromDishka[SendMessageToUser],
    bot_service: FromDishka[BotService],
    i18n: FromDishka[TranslatorRunner],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]
    payload = dialog_manager.dialog_data.get("payload")

    if not payload:
        await notifier.notify_user(user, i18n_key="ntf-broadcast.content-empty")
        return

    payload = retort.load(payload, MessagePayloadDto)
    support_url = bot_service.get_support_url(text=i18n.get("message.help"))
    payload.reply_markup = get_contact_support_keyboard(support_url)

    if is_double_click(dialog_manager, key="message_confirm", cooldown=5):
        success = await send_message_to_user(
            user,
            SendMessageToUserDto(target_user_id, payload),
        )

        await dialog_manager.switch_to(state=DashboardUser.MAIN)

        i18n_key = "ntf-user.message-success" if success else "ntf-user.message-failed"
        await notifier.notify_user(user, i18n_key=i18n_key)
        return

    await notifier.notify_user(user, i18n_key="ntf-common.double-click-confirm")
    logger.debug(f"{user.log} Awaiting confirmation for message send")


@inject
async def on_sync(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    check_subscription_sync_state: FromDishka[CheckSubscriptionSyncState],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]

    try:
        needs_sync = await check_subscription_sync_state(user, target_user_id)

        if not needs_sync:
            await notifier.notify_user(user, i18n_key="ntf-user.sync-already")
            return

        await dialog_manager.switch_to(state=DashboardUser.SYNC)

    except ValueError:
        await notifier.notify_user(user, i18n_key="ntf-user.sync-missing-data")


@inject
async def on_sync_from_remnawave(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    sync_subscription_from_remnawave: FromDishka[SyncSubscriptionFromRemnawave],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]
    await sync_subscription_from_remnawave(user, target_user_id)
    await notifier.notify_user(user, i18n_key="ntf-user.sync-success")
    await dialog_manager.switch_to(state=DashboardUser.MAIN)


@inject
async def on_sync_from_remnashop(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    sync_subscription_from_remnashop: FromDishka[SyncSubscriptionFromRemnashop],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]
    await sync_subscription_from_remnashop(user, target_user_id)
    await notifier.notify_user(user, i18n_key="ntf-user.sync-success")
    await dialog_manager.switch_to(state=DashboardUser.MAIN)


@inject
async def on_give_subscription(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    user_dao: FromDishka[UserDao],
    get_available_plans: FromDishka[GetAvailablePlans],
    notifier: FromDishka[Notifier],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]
    target_user = await user_dao.get_by_id(target_user_id)

    if not target_user:
        raise ValueError(f"User '{target_user_id}' not found")

    plans = await get_available_plans.system(target_user)

    if not plans:
        await notifier.notify_user(user, i18n_key="ntf-user.plans-empty")
        return

    await dialog_manager.switch_to(state=DashboardUser.GIVE_SUBSCRIPTION)


@inject
async def on_subscription_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_plan_id: int,
) -> None:
    dialog_manager.dialog_data["selected_plan_id"] = selected_plan_id
    await dialog_manager.switch_to(state=DashboardUser.SUBSCRIPTION_DURATION)


@inject
async def on_subscription_duration_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_duration: int,
    set_user_subscription: FromDishka[SetUserSubscription],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    target_user_id = dialog_manager.dialog_data[TARGET_USER_ID]
    plan_id = dialog_manager.dialog_data["selected_plan_id"]
    await set_user_subscription(
        user,
        SetUserSubscriptionDto(target_user_id, plan_id, selected_duration),
    )
    await dialog_manager.switch_to(state=DashboardUser.MAIN)
