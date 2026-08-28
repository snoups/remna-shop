from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, ShowMode
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.application.common import Notifier
from src.application.dto import TelegramUserDto
from src.application.use_cases.settings.commands.extra import (
    ToggleMiniAppReserve,
    ToggleResetFeature,
    ToggleResetFeatureDto,
    ToggleStarsPaidRequirement,
    ToggleTrialChannelGuard,
    UpdateResetCooldown,
    UpdateResetCooldownDto,
)
from src.core.constants import USER_KEY
from src.telegram.states import RemnashopExtra

_STATE_TO_FEATURE = {
    RemnashopExtra.DEVICE_SINGLE: "device_single_reset",
    RemnashopExtra.DEVICE_ALL: "device_all_reset",
    RemnashopExtra.LINK_RESET: "link_reset",
    RemnashopExtra.REFERRAL_RESET: "referral_reset",
}


@inject
async def on_toggle(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    toggle_reset_feature: FromDishka[ToggleResetFeature],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    feature = _STATE_TO_FEATURE.get(dialog_manager.current_context().state, "")
    await toggle_reset_feature(user, ToggleResetFeatureDto(feature=feature))


@inject
async def on_trial_channel_guard_toggle(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    toggle_trial_channel_guard: FromDishka[ToggleTrialChannelGuard],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    await toggle_trial_channel_guard(user)


@inject
async def on_mini_app_reserve_toggle(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    toggle_mini_app_reserve: FromDishka[ToggleMiniAppReserve],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    await toggle_mini_app_reserve(user)


@inject
async def on_stars_paid_requirement_toggle(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    toggle_stars_paid_requirement: FromDishka[ToggleStarsPaidRequirement],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    await toggle_stars_paid_requirement(user)


@inject
async def on_cooldown_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    update_reset_cooldown: FromDishka[UpdateResetCooldown],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    feature = _STATE_TO_FEATURE.get(dialog_manager.current_context().state, "")
    raw_value = message.text

    try:
        if not raw_value or not feature:
            raise ValueError
        await update_reset_cooldown(
            user, UpdateResetCooldownDto(feature=feature, raw_value=raw_value)
        )
    except ValueError:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    dialog_manager.show_mode = ShowMode.DELETE_AND_SEND
