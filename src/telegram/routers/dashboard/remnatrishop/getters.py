from typing import Any

from adaptix import Retort
from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.application.common.dao import TransactionDao
from src.application.dto import TelegramUserDto
from src.application.use_cases.user.commands.roles import GetAdmins, GetAdminsResultDto
from src.core.config import AppConfig
from src.core.constants import DATETIME_VIEW_FORMAT


async def remnashop_getter(
    dialog_manager: DialogManager,
    config: AppConfig,
    **kwargs: Any,
) -> dict[str, Any]:
    return {"version": config.build.tag}


@inject
async def admins_getter(
    dialog_manager: DialogManager,
    user: TelegramUserDto,
    retort: FromDishka[Retort],
    get_admins: FromDishka[GetAdmins],
    **kwargs: Any,
) -> dict[str, Any]:
    admins = await get_admins(user)
    return {"admins": retort.dump(admins, list[GetAdminsResultDto])}


@inject
async def all_transactions_getter(
    dialog_manager: DialogManager,
    transaction_dao: FromDishka[TransactionDao],
    **kwargs: Any,
) -> dict[str, Any]:
    transactions = await transaction_dao.get_all(limit=50)
    formatted = [
        {
            "payment_id": t.payment_id,
            "user_id": t.user_id,
            "status": t.status,
            "created_at": t.created_at.strftime(DATETIME_VIEW_FORMAT),  # type: ignore[union-attr]
            "gateway_type": t.gateway_type,
        }
        for t in transactions
    ]
    return {"transactions": formatted}
