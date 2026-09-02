from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock

from pydantic import SecretStr

from src.core.config.bot import BotConfig

bot_provider = import_module("src.infrastructure.di.providers.bot")


def test_custom_bot_api_base_url_takes_precedence_over_proxy(monkeypatch) -> None:
    api = object()
    session = object()
    from_base = Mock(return_value=api)
    aiohttp_session = Mock(return_value=session)
    monkeypatch.setattr(
        bot_provider,
        "TelegramAPIServer",
        SimpleNamespace(from_base=from_base),
    )
    monkeypatch.setattr(bot_provider, "AiohttpSession", aiohttp_session)
    config = SimpleNamespace(
        bot=SimpleNamespace(
            api_base_url="http://telegram-mock:8081",
            proxy_url=SecretStr("socks5://proxy.example:1080"),
        )
    )

    assert bot_provider._build_bot_session(config) is session
    from_base.assert_called_once_with("http://telegram-mock:8081")
    aiohttp_session.assert_called_once_with(api=api)


def test_proxy_session_is_used_without_custom_api(monkeypatch) -> None:
    session = object()
    aiohttp_session = Mock(return_value=session)
    monkeypatch.setattr(bot_provider, "AiohttpSession", aiohttp_session)
    config = SimpleNamespace(
        bot=SimpleNamespace(
            api_base_url=None,
            proxy_url=SecretStr("socks5h://proxy.example:1080"),
        )
    )

    assert bot_provider._build_bot_session(config) is session
    aiohttp_session.assert_called_once_with(proxy="socks5://proxy.example:1080")


def test_default_bot_session_uses_aiogram_defaults() -> None:
    config = SimpleNamespace(bot=SimpleNamespace(api_base_url=None, proxy_url=None))

    assert bot_provider._build_bot_session(config) is None


def test_bot_api_base_url_is_normalized() -> None:
    assert (
        BotConfig.validate_api_base_url(" http://telegram-mock:8081/ ")
        == "http://telegram-mock:8081"
    )


def test_bot_api_base_url_rejects_credentials_and_query() -> None:
    for value in (
        "http://user:pass@telegram-mock:8081",
        "http://telegram-mock:8081?token=secret",
    ):
        try:
            BotConfig.validate_api_base_url(value)
        except ValueError as error:
            assert "valid HTTP(S) base URL" in str(error)
        else:
            raise AssertionError(f"Expected invalid BOT_API_BASE_URL: {value}")
