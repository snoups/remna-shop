import hashlib

from aiogram import F, Router
from aiogram.enums import ButtonStyle
from aiogram.types import (
    InlineKeyboardButton,
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultUnion,
    InputTextMessageContent,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from loguru import logger

from src.application.common import BotService, TranslatorRunner
from src.application.common.dao import UserDao
from src.core.constants import INLINE_QUERY_INVITE

router = Router(name=__name__)


@inject
@router.inline_query(F.query == INLINE_QUERY_INVITE)
async def handle_inline_query(
    inline_query: InlineQuery,
    user_dao: FromDishka[UserDao],
    bot_service: FromDishka[BotService],
    i18n: FromDishka[TranslatorRunner],
) -> None:
    user = await user_dao.get_by_telegram_id(inline_query.from_user.id)

    if not user:
        logger.warning(
            f"User with Telegram ID '{inline_query.from_user.id}' not found for inline query"
        )
        return

    logger.info(f"{user.log} Sent inline query {INLINE_QUERY_INVITE}")

    result_id = hashlib.md5(
        inline_query.query.strip().encode(), usedforsecurity=False
    ).hexdigest()
    referral_url = await bot_service.get_referral_url(user.referral_code)
    bot_name = await bot_service.get_my_name()

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=i18n.get("inline-invite.start"),
            style=ButtonStyle.SUCCESS,
            url=referral_url,
        )
    )

    results: list[InlineQueryResultUnion] = [
        InlineQueryResultArticle(
            id=result_id,
            thumbnail_url="https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcT6Msm80-vY25Ecm4cOhOTAG1P21zKBax8-KA&s",
            title=i18n.get("inline-invite.title"),
            description=i18n.get("inline-invite.description"),
            input_message_content=InputTextMessageContent(
                message_text=i18n.get("inline-invite.message", bot_name=bot_name)
            ),
            reply_markup=builder.as_markup(),
        )
    ]

    await inline_query.answer(results, cache_time=1, is_personal=True)
