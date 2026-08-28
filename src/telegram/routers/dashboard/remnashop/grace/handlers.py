from typing import Optional
from uuid import UUID

from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, ShowMode
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, Select
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from remnapy.enums.users import TrafficLimitStrategy

from src.application.common import Notifier
from src.application.common.dao import SettingsDao
from src.application.dto import TelegramUserDto
from src.application.use_cases.settings.commands.grace import (
    SetGraceExternalSquad,
    SetGraceExternalSquadDto,
    SetGraceStrategy,
    SetGraceStrategyDto,
    ToggleGraceEnabled,
    ToggleGraceInternalSquad,
    ToggleGraceInternalSquadDto,
    UpdateGraceDuration,
    UpdateGraceDurationDto,
    UpdateGraceTag,
    UpdateGraceTagDto,
    UpdateGraceTraffic,
    UpdateGraceTrafficDto,
)
from src.core.constants import USER_KEY
from src.telegram.states import RemnashopGrace


@inject
async def on_toggle_enabled(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    toggle_grace_enabled: FromDishka[ToggleGraceEnabled],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    await toggle_grace_enabled(user)


@inject
async def on_traffic_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    update_grace_traffic: FromDishka[UpdateGraceTraffic],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    if not message.text:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    try:
        await update_grace_traffic(user, UpdateGraceTrafficDto(raw_value=message.text))
        await dialog_manager.switch_to(state=RemnashopGrace.MAIN)

    except ValueError:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")


@inject
async def on_duration_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    update_grace_duration: FromDishka[UpdateGraceDuration],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    if not message.text:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    try:
        await update_grace_duration(user, UpdateGraceDurationDto(raw_value=message.text))
        await dialog_manager.switch_to(state=RemnashopGrace.MAIN)

    except ValueError:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")


@inject
async def on_tag_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    update_grace_tag: FromDishka[UpdateGraceTag],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    if message.text is None:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    await update_grace_tag(user, UpdateGraceTagDto(raw_value=message.text))
    await dialog_manager.switch_to(state=RemnashopGrace.MAIN)


@inject
async def on_strategy_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_strategy: TrafficLimitStrategy,
    set_grace_strategy: FromDishka[SetGraceStrategy],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    await set_grace_strategy(user, SetGraceStrategyDto(strategy=selected_strategy))
    await dialog_manager.switch_to(state=RemnashopGrace.MAIN)


@inject
async def on_internal_squad_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_squad: UUID,
    toggle_grace_internal_squad: FromDishka[ToggleGraceInternalSquad],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    await toggle_grace_internal_squad(user, ToggleGraceInternalSquadDto(squad_uuid=selected_squad))


@inject
async def on_external_squad_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_squad: UUID,
    settings_dao: FromDishka[SettingsDao],
    set_grace_external_squad: FromDishka[SetGraceExternalSquad],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    current = (await settings_dao.get()).grace.external_squad
    new_value: Optional[UUID] = None if current == selected_squad else selected_squad

    await set_grace_external_squad(user, SetGraceExternalSquadDto(squad_uuid=new_value))
