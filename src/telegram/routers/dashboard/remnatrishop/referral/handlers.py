from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, ShowMode
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, Select
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.application.common import Notifier
from src.application.dto import TelegramUserDto
from src.application.use_cases.settings.commands.referral import (
    ToggleReferralSystem,
    UpdateReferralAccrualStrategy,
    UpdateReferralLevel,
    UpdateReferralRewardConfig,
    UpdateReferralRewardStrategy,
    UpdateReferralRewardType,
)
from src.core.constants import USER_KEY
from src.core.enums import (
    ReferralAccrualStrategy,
    ReferralRewardStrategy,
    ReferralRewardType,
)
from src.telegram.states import RemnashopReferral


@inject
async def on_enable_toggle(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    toggle_referral_system: FromDishka[ToggleReferralSystem],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    await toggle_referral_system(user)


@inject
async def on_level_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_level: int,
    update_referral_level: FromDishka[UpdateReferralLevel],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    await update_referral_level(user, selected_level)
    await dialog_manager.switch_to(state=RemnashopReferral.MAIN)


@inject
async def on_reward_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_reward: ReferralRewardType,
    update_reward_type: FromDishka[UpdateReferralRewardType],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    await update_reward_type(user, selected_reward)
    await dialog_manager.switch_to(state=RemnashopReferral.MAIN)


@inject
async def on_accrual_strategy_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_strategy: ReferralAccrualStrategy,
    update_strategy: FromDishka[UpdateReferralAccrualStrategy],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    await update_strategy(user, selected_strategy)
    await dialog_manager.switch_to(state=RemnashopReferral.MAIN)


@inject
async def on_reward_strategy_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_strategy: ReferralRewardStrategy,
    update_reward_strategy: FromDishka[UpdateReferralRewardStrategy],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    await update_reward_strategy(user, selected_strategy)
    await dialog_manager.switch_to(state=RemnashopReferral.MAIN)


@inject
async def on_reward_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    update_reward_config: FromDishka[UpdateReferralRewardConfig],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    if not message.text:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    try:
        await update_reward_config(user, message.text)
    except (ValueError, KeyError, IndexError):
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
