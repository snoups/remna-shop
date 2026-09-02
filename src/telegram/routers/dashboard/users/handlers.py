from io import BytesIO

from adaptix import Retort
from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, ShowMode, StartMode
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, Select
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from loguru import logger

from src.application.common import Notifier
from src.application.common.dao import SettingsDao, UserDao
from src.application.common.policy import Permission, PermissionPolicy
from src.application.dto import MessagePayloadDto, TelegramUserDto, UserDto
from src.application.use_cases.blacklist.commands.sources import (
    AddBlacklistSource,
    AddBlacklistSourceDto,
    RemoveBlacklistSource,
    SyncBlacklistSources,
)
from src.application.use_cases.blacklist.queries.fetch import FetchBlacklistIds, ParseBlacklistIds
from src.application.use_cases.user.commands.blocking import (
    BlockUsersByIds,
    ClearBlockedIds,
    UnblockAllUsers,
)
from src.application.use_cases.user.queries.search import SearchUsers, SearchUsersDto
from src.core.constants import USER_KEY
from src.core.utils.validators import is_valid_url
from src.telegram.states import DashboardUsers
from src.telegram.utils import is_double_click

from .user.handlers import start_user_window


@inject
async def on_user_search(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    notifier: FromDishka[Notifier],
    search_users: FromDishka[SearchUsers],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    if not PermissionPolicy.has_permission(user, Permission.USER_SEARCH):
        return

    search_data = SearchUsersDto(
        query=message.text,
        forward_from_id=message.forward_from.id if message.forward_from else None,
        forward_sender_name=message.forward_sender_name if message.forward_sender_name else None,
        is_forwarded_from_bot=message.forward_from.is_bot if message.forward_from else False,
    )

    found_users = await search_users(user, search_data)

    if not found_users:
        await notifier.notify_user(user, i18n_key="ntf-user.not-found")

    elif len(found_users) == 1:
        target_user = found_users[0]
        logger.info(f"{user.log} Searched user -> {target_user.log}")
        await start_user_window(manager=dialog_manager, target_user_id=target_user.id)

    else:
        await dialog_manager.start(
            state=DashboardUsers.SEARCH_RESULTS,
            data={"found_users": retort.dump(found_users, list[UserDto])},
        )


async def on_user_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_user: int,
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    logger.info(f"{user.log} User id '{selected_user}' selected")

    context = dialog_manager.current_context()
    origin = context.state
    payload = context.start_data.get("found_users") if context.start_data else None  # type: ignore[union-attr]

    await start_user_window(
        manager=dialog_manager,
        target_user_id=selected_user,
        list_origin=origin.state,
        list_payload=payload,
    )


@inject
async def on_unblock_all(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    unblock_all_users: FromDishka[UnblockAllUsers],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    if is_double_click(dialog_manager, key="unblock_all_confirm", cooldown=5):
        await unblock_all_users(user)
        await dialog_manager.start(state=DashboardUsers.BLACKLIST, mode=StartMode.RESET_STACK)
        return

    await notifier.notify_user(user, i18n_key="ntf-common.double-click-confirm")
    logger.debug(f"{user.log} Awaiting confirmation to unblock all users")


@inject
async def on_blacklist_view(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    user_dao: FromDishka[UserDao],
    notifier: FromDishka[Notifier],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    count = await user_dao.count_blocked()

    if not count:
        await notifier.notify_user(user, i18n_key="ntf-blacklist.list-empty")
        return

    await dialog_manager.switch_to(DashboardUsers.BLACKLIST_USERS)


@inject
async def on_block_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    block_users_by_ids: FromDishka[BlockUsersByIds],
    fetch_blacklist_ids: FromDishka[FetchBlacklistIds],
    parse_blacklist_ids: FromDishka[ParseBlacklistIds],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    raw = (message.text or "").strip()
    if raw and is_valid_url(raw):
        ids = await fetch_blacklist_ids.system(raw)
        if not ids:
            await notifier.notify_user(user, i18n_key="ntf-blacklist.no-ids-found")
            return
    else:
        ids = await _parse_ids_from_message(message, parse_blacklist_ids)
        if not ids:
            await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
            return

    result = await block_users_by_ids(user, ids)
    await notifier.notify_user(
        user,
        MessagePayloadDto(
            i18n_key="ntf-blacklist.block-result",
            i18n_kwargs={
                "total": result.blocked_users + result.blocked_ids + result.already_blocked,
                "blocked_users": result.blocked_users,
                "blocked_ids": result.blocked_ids,
                "already_blocked": result.already_blocked,
            },
            disable_default_markup=False,
            delete_after=None,
        ),
    )


@inject
async def on_source_delete(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    remove_blacklist_source: FromDishka[RemoveBlacklistSource],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    source_id = int(dialog_manager.item_id)  # type: ignore[attr-defined]

    if is_double_click(dialog_manager, key=f"del_source_{source_id}", cooldown=5):
        await remove_blacklist_source(user, source_id)
        await notifier.notify_user(user, i18n_key="ntf-blacklist.source-removed")
        return

    await notifier.notify_user(user, i18n_key="ntf-common.double-click-confirm")


@inject
async def on_source_sync(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    sync_blacklist_sources: FromDishka[SyncBlacklistSources],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    result = await sync_blacklist_sources(user)
    await notifier.notify_user(
        user,
        MessagePayloadDto(
            i18n_key="ntf-blacklist.block-result",
            i18n_kwargs={
                "total": result.blocked_users + result.blocked_ids + result.already_blocked,
                "blocked_users": result.blocked_users,
                "blocked_ids": result.blocked_ids,
                "already_blocked": result.already_blocked,
            },
            disable_default_markup=False,
            delete_after=None,
        ),
    )


@inject
async def on_source_add_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    add_blacklist_source: FromDishka[AddBlacklistSource],
    sync_blacklist_sources: FromDishka[SyncBlacklistSources],
    fetch_blacklist_ids: FromDishka[FetchBlacklistIds],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    raw = (message.text or "").strip()
    if not is_valid_url(raw):
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    ids = await fetch_blacklist_ids.system(raw)
    if not ids:
        await notifier.notify_user(user, i18n_key="ntf-blacklist.no-ids-found")
        return

    await add_blacklist_source(user, AddBlacklistSourceDto(url=raw))
    result = await sync_blacklist_sources(user)
    await notifier.notify_user(
        user,
        MessagePayloadDto(
            i18n_key="ntf-blacklist.block-result",
            i18n_kwargs={
                "total": result.blocked_users + result.blocked_ids + result.already_blocked,
                "blocked_users": result.blocked_users,
                "blocked_ids": result.blocked_ids,
                "already_blocked": result.already_blocked,
            },
            disable_default_markup=False,
            delete_after=None,
        ),
    )


@inject
async def on_clear_blocked_ids(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    clear_blocked_ids: FromDishka[ClearBlockedIds],
    settings_dao: FromDishka[SettingsDao],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    settings = await settings_dao.get()

    if not settings.blacklist.blocked_ids:
        await notifier.notify_user(user, i18n_key="ntf-blacklist.blocked-ids-empty")
        return

    if is_double_click(dialog_manager, key="clear_blocked_ids", cooldown=5):
        count = await clear_blocked_ids(user)
        await notifier.notify_user(
            user,
            MessagePayloadDto(
                i18n_key="ntf-blacklist.blocked-ids-cleared",
                i18n_kwargs={"count": count},
            ),
        )
        return

    await notifier.notify_user(user, i18n_key="ntf-common.double-click-confirm")


async def _parse_ids_from_message(
    message: Message,
    parse_blacklist_ids: ParseBlacklistIds,
) -> list[int]:
    if message.document:
        try:
            if message.bot is None:
                raise RuntimeError("Telegram message is not bound to a bot")
            file = await message.bot.get_file(message.document.file_id)
            if file.file_path is None:
                raise RuntimeError("Telegram did not return a downloadable file path")
            buf: BytesIO = await message.bot.download_file(file.file_path)  # type: ignore[assignment]
            text = buf.read().decode("utf-8", errors="ignore")
        except Exception as exc:
            logger.warning(f"Failed to download block-list file: {exc}")
            return []
        return await parse_blacklist_ids.system(text)

    raw = (message.text or "").strip()
    return await parse_blacklist_ids.system(raw) if raw else []
