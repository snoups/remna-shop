import shutil
import tempfile
import zipfile
from pathlib import Path
from uuid import UUID

from aiogram.types import CallbackQuery
from aiogram_dialog import DialogManager
from aiogram_dialog.widgets.kbd import Button, Select
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from loguru import logger

from src.application.common import Notifier, Redirect
from src.application.common.dao import TransactionDao, UserDao
from src.application.dto import MediaDescriptorDto, MessagePayloadDto, TelegramUserDto
from src.application.use_cases.misc.queries.logs import GetLogs
from src.application.use_cases.user.commands.roles import RevokeRole
from src.core.constants import LOG_DIR, USER_KEY
from src.core.enums import MediaType
from src.core.exceptions import LogsToFileDisabledError
from src.core.logger import LOG_FILENAME
from src.telegram.routers.dashboard.users.user.handlers import (
    start_user_transaction_window,
    start_user_window,
)
from src.telegram.utils import is_double_click

_TELEGRAM_FILE_SIZE_LIMIT = 50 * 1024 * 1024  # 50 MB


@inject
async def on_logs_request(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    get_logs: FromDishka[GetLogs],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    tmp_dir: Path | None = None
    try:
        log_file = await get_logs(user)

        send_path = log_file.path
        send_name = log_file.display_name

        if send_path.stat().st_size > _TELEGRAM_FILE_SIZE_LIMIT:
            tmp_dir = Path(tempfile.mkdtemp())
            zip_path = tmp_dir / f"{log_file.display_name}.zip"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(send_path, log_file.display_name)
            send_path = zip_path
            send_name = zip_path.name
            logger.info(f"{user.log} Log file compressed to zip before sending")

        await notifier.notify_user(
            user=user,
            payload=MessagePayloadDto(
                i18n_key="",
                media=MediaDescriptorDto(kind="fs", value=str(send_path), filename=send_name),
                media_type=MediaType.DOCUMENT,
                delete_after=None,
                disable_default_markup=False,
            ),
        )
    except FileNotFoundError:
        logger.error(f"{user.log} Log file not found at '{LOG_DIR}/{LOG_FILENAME}'")
        await notifier.notify_user(user, i18n_key="ntf-error.log-not-found")
    except LogsToFileDisabledError:
        logger.debug(f"Logs request denied for {user.log}: file logging is off")
        await notifier.notify_user(user, i18n_key="ntf-error.logs-disabled")
    finally:
        if tmp_dir is not None:
            shutil.rmtree(tmp_dir, ignore_errors=True)


@inject
async def on_user_select(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
) -> None:
    target_user_id = int(dialog_manager.item_id)  # type: ignore[attr-defined]
    await start_user_window(manager=dialog_manager, target_user_id=target_user_id)


@inject
async def on_role_revoke(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    redirect: FromDishka[Redirect],
    revoke_role: FromDishka[RevokeRole],
    user_dao: FromDishka[UserDao],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    target_user_id = int(dialog_manager.item_id)  # type: ignore[attr-defined]

    if not is_double_click(
        dialog_manager,
        key=f"role_confirm_{target_user_id}",
        cooldown=10,
    ):
        await notifier.notify_user(user, i18n_key="ntf-common.double-click-confirm")
        logger.debug(f"Waiting for double click confirmation to revoke role for '{target_user_id}'")
        return

    await revoke_role(user, target_user_id)
    target_user = await user_dao.get_by_id(target_user_id)
    if target_user and target_user.telegram_id:
        await redirect.to_main_menu(target_user.telegram_id)


@inject
async def on_all_transaction_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_transaction: UUID,
    transaction_dao: FromDishka[TransactionDao],
) -> None:
    transaction = await transaction_dao.get_by_payment_id(selected_transaction)
    if not transaction:
        return
    await start_user_transaction_window(
        manager=dialog_manager,
        target_user_id=transaction.user_id,
        selected_transaction=transaction.payment_id,
        origin="all_transactions",
    )
