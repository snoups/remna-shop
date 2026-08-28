from adaptix import Retort
from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, ShowMode, StartMode
from aiogram_dialog.widgets.kbd import Button
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from loguru import logger

from src.application.common import BotService, Notifier, Redirect, TranslatorRunner
from src.application.common.dao import SettingsDao, SubscriptionDao
from src.application.dto import (
    MediaDescriptorDto,
    MessagePayloadDto,
    PlanSnapshotDto,
    TelegramUserDto,
)
from src.application.use_cases.referral.queries.code import GenerateReferralQr
from src.application.use_cases.remnawave.commands.management import (
    DeleteUserAllDevices,
    DeleteUserDevice,
    DeleteUserDeviceDto,
    ReissueSubscription,
)
from src.application.use_cases.subscription.commands.purchase import (
    ActivateTrialSubscription,
    ActivateTrialSubscriptionDto,
)
from src.application.use_cases.user.commands.profile_edit import ResetOwnReferralCode
from src.application.use_cases.user.queries.plans import GetAvailableTrial
from src.core.constants import USER_KEY
from src.core.enums import MediaType
from src.core.exceptions import CooldownError, TrialNotAvailableError
from src.core.utils.i18n_helpers import i18n_format_expire_time
from src.core.utils.time import get_traffic_reset_delta
from src.telegram.keyboards import CALLBACK_CHANNEL_CONFIRM, CALLBACK_RULES_ACCEPT
from src.telegram.states import MainMenu, Subscription

router = Router(name=__name__)


async def on_start_dialog(user: TelegramUserDto, dialog_manager: DialogManager) -> None:
    logger.info(f"{user.log} Started dialog")
    await dialog_manager.start(
        state=MainMenu.MAIN,
        mode=StartMode.RESET_STACK,
        show_mode=ShowMode.DELETE_AND_SEND,
    )


@router.message(CommandStart(ignore_case=True))
async def on_start_command(
    message: Message, user: TelegramUserDto, dialog_manager: DialogManager
) -> None:
    await on_start_dialog(user, dialog_manager)


@router.callback_query(F.data == CALLBACK_RULES_ACCEPT)
async def on_rules_accept(
    callback: CallbackQuery,
    user: TelegramUserDto,
    dialog_manager: DialogManager,
) -> None:
    await on_start_dialog(user, dialog_manager)


@router.callback_query(F.data == CALLBACK_CHANNEL_CONFIRM)
async def on_channel_confirm(
    callback: CallbackQuery,
    user: TelegramUserDto,
    dialog_manager: DialogManager,
) -> None:
    await on_start_dialog(user, dialog_manager)


@inject
async def on_get_trial(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    redirect: FromDishka[Redirect],
    retort: FromDishka[Retort],
    get_available_trial: FromDishka[GetAvailableTrial],
    activate_trial_subscription: FromDishka[ActivateTrialSubscription],
    settings_dao: FromDishka[SettingsDao],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    plan = await get_available_trial.system(user)

    if not plan:
        # Trial button came from a stale menu (bot restart / late re-click). Re-render the menu
        # so the outdated button disappears, then inform the user — this is expected, not an error.
        logger.info(f"{user.log} Trial no longer available at click time")
        await notifier.notify_user(user=user, i18n_key="ntf-common.trial-unavailable")
        if user.telegram_id is not None:
            await redirect.to_main_menu(user.telegram_id)
        return

    settings = await settings_dao.get()
    currency = settings.default_currency
    raw_price = plan.durations[0].get_price(currency)

    if raw_price == 0:
        trial = PlanSnapshotDto.from_plan(plan, plan.durations[0].days)

        try:
            await activate_trial_subscription.system(ActivateTrialSubscriptionDto(user, trial))
        except TrialNotAvailableError:
            # Concurrent double-click: another click already activated the trial. It exists, so
            # route to success instead of a misleading failure screen.
            logger.info(f"{user.log} Trial already activated (double-click)")
            if user.telegram_id is not None:
                await redirect.to_success_trial(user.telegram_id)
            return
        except Exception:
            logger.exception(f"{user.log} Trial activation failed")
            if user.telegram_id is not None:
                await redirect.to_failed_payment(user.telegram_id)
            return

        if user.telegram_id is not None:
            await redirect.to_success_trial(user.telegram_id)
        return

    await dialog_manager.start(
        state=Subscription.MAIN,
        data={
            "trial_plan": retort.dump(plan),
            "trial_duration": plan.durations[0].days,
        },
    )


async def on_device_delete_request(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
) -> None:
    selected_index = int(dialog_manager.item_id)  # type: ignore[attr-defined]
    hwid_map = dialog_manager.dialog_data.get("hwid_map", [])
    device = hwid_map[selected_index] if selected_index < len(hwid_map) else None

    if not device:
        raise ValueError(f"Device not found at index '{selected_index}'")

    dialog_manager.dialog_data["selected_hwid"] = device["hwid"]
    dialog_manager.dialog_data["selected_device_model"] = device["device_model"] or ""
    dialog_manager.dialog_data["selected_platform"] = device["platform"] or ""
    dialog_manager.dialog_data["selected_platform_icon"] = device["platform_icon"]
    dialog_manager.dialog_data["selected_created_at"] = device["created_at"]
    await dialog_manager.switch_to(state=MainMenu.DEVICE_CONFIRM_DELETE)


@inject
async def on_device_delete_confirm(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    delete_user_device: FromDishka[DeleteUserDevice],
    notifier: FromDishka[Notifier],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    full_hwid = dialog_manager.dialog_data.get("selected_hwid")

    if not full_hwid:
        raise ValueError("Missing selected device data")

    try:
        await delete_user_device(user, DeleteUserDeviceDto(user_id=user.id, hwid=full_hwid))
    except CooldownError as e:
        await notifier.notify_user(
            user=user,
            payload=MessagePayloadDto(
                i18n_key="ntf-common.cooldown-active",
                i18n_kwargs={"available_at": i18n_format_expire_time(e.available_at)},
            ),
        )
        return
    await notifier.notify_user(user=user, i18n_key="ntf-devices.deleted")
    await dialog_manager.switch_to(state=MainMenu.DEVICES)


@inject
async def on_device_delete_all_confirm(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    delete_user_all_devices: FromDishka[DeleteUserAllDevices],
    notifier: FromDishka[Notifier],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    try:
        await delete_user_all_devices(user)
    except CooldownError as e:
        await notifier.notify_user(
            user=user,
            payload=MessagePayloadDto(
                i18n_key="ntf-common.cooldown-active",
                i18n_kwargs={"available_at": i18n_format_expire_time(e.available_at)},
            ),
        )
        return
    await notifier.notify_user(user=user, i18n_key="ntf-devices.all-deleted")
    await dialog_manager.switch_to(state=MainMenu.DEVICES)


@inject
async def on_reissue_subscription_confirm(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    reissue_subscription: FromDishka[ReissueSubscription],
    notifier: FromDishka[Notifier],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    try:
        await reissue_subscription(user)
    except CooldownError as e:
        await notifier.notify_user(
            user=user,
            payload=MessagePayloadDto(
                i18n_key="ntf-common.cooldown-active",
                i18n_kwargs={"available_at": i18n_format_expire_time(e.available_at)},
            ),
        )
        return
    await notifier.notify_user(user=user, i18n_key="ntf-devices.reissued")
    await dialog_manager.switch_to(state=MainMenu.DEVICES)


@inject
async def show_reason(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    i18n: FromDishka[TranslatorRunner],
    subscription_dao: FromDishka[SubscriptionDao],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    subscription = await subscription_dao.get_current(user.id)

    if subscription:
        kwargs = {
            "status": subscription.current_status,
            "is_trial": subscription.is_trial,
            "traffic_strategy": subscription.traffic_limit_strategy,
            "reset_time": i18n_format_expire_time(
                get_traffic_reset_delta(
                    subscription.traffic_limit_strategy,
                    subscription.created_at,
                )
            ),
        }
    else:
        kwargs = {"status": False}

    await callback.answer(
        text=i18n.get("ntf-common.connect-not-available", **kwargs),
        show_alert=True,
    )


@inject
async def on_show_qr(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    bot_service: FromDishka[BotService],
    generate_referral_qr: FromDishka[GenerateReferralQr],
    notifier: FromDishka[Notifier],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    referral_url = await bot_service.get_referral_url(user.referral_code)
    referral_qr = await generate_referral_qr.system(referral_url)

    await notifier.notify_user(
        user=user,
        payload=MessagePayloadDto(
            i18n_key="",
            media=MediaDescriptorDto(kind="bytes", value=referral_qr, filename="qr.png"),
            media_type=MediaType.PHOTO,
            disable_default_markup=False,
            delete_after=None,
        ),
    )


@inject
async def on_text_button_click(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    settings_dao: FromDishka[SettingsDao],
    notifier: FromDishka[Notifier],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    button_index = int(dialog_manager.item_id)  # type: ignore[attr-defined]
    settings = await settings_dao.get()
    button = next((b for b in settings.menu.buttons if b.index == button_index), None)

    if not button or not (button.payload or button.media_file_id):
        return

    await notifier.notify_user(
        user=user,
        payload=MessagePayloadDto(
            i18n_key="raw-message",
            i18n_kwargs={"content": button.payload},
            media=MediaDescriptorDto(kind="file_id", value=button.media_file_id)
            if button.media_file_id
            else None,
            media_type=button.media_type,
            disable_default_markup=False,
            delete_after=None,
        ),
    )


@inject
async def on_withdraw_points(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    await notifier.notify_user(user=user, i18n_key="ntf-common.withdraw-points")


@inject
async def on_invite(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    settings_dao: FromDishka[SettingsDao],
) -> None:
    settings = await settings_dao.get()
    if settings.referral.enable:
        await dialog_manager.switch_to(state=MainMenu.INVITE)
    return


@inject
async def on_reset_referral_code(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    reset_own_referral_code: FromDishka[ResetOwnReferralCode],
    notifier: FromDishka[Notifier],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    try:
        await reset_own_referral_code(user)
    except CooldownError as e:
        await notifier.notify_user(
            user=user,
            payload=MessagePayloadDto(
                i18n_key="ntf-common.cooldown-active",
                i18n_kwargs={"available_at": i18n_format_expire_time(e.available_at)},
            ),
        )
        return
    await notifier.notify_user(user=user, i18n_key="ntf-invite.referral-reset")
