from collections.abc import AsyncIterable

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram_dialog import BgManagerFactory
from dishka import Provider, Scope, from_context, provide
from loguru import logger

from src.core.config import AppConfig


def _normalize_proxy_url(url: str) -> str:
    # aiohttp_socks doesn't recognize the socks5h/socks4a schemes; aiogram always
    # resolves DNS remotely (rdns=True), so they're equivalent to socks5/socks4.
    if url.startswith("socks5h://"):
        return url.replace("socks5h://", "socks5://", 1)
    if url.startswith("socks4a://"):
        return url.replace("socks4a://", "socks4://", 1)
    return url


class BotProvider(Provider):
    scope = Scope.APP

    bg_manager_factory = from_context(provides=BgManagerFactory)

    @provide
    async def get_bot(self, config: AppConfig) -> AsyncIterable[Bot]:
        logger.debug("Initializing Bot instance")

        session = _build_bot_session(config)

        async with Bot(
            token=config.bot.token.get_secret_value(),
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            session=session,
        ) as bot:
            yield bot


def _build_bot_session(config: AppConfig) -> AiohttpSession | None:
    if config.bot.api_base_url:
        logger.info("Using custom Telegram Bot API base URL")
        return AiohttpSession(api=TelegramAPIServer.from_base(config.bot.api_base_url))

    if config.bot.proxy_url:
        logger.info("Using SOCKS5 proxy for Telegram")
        proxy = _normalize_proxy_url(config.bot.proxy_url.get_secret_value())
        return AiohttpSession(proxy=proxy)

    return None
