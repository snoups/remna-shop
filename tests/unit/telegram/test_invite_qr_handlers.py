from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.core.constants import USER_KEY
from src.telegram.routers.menu.handlers import on_show_telegram_qr, on_show_web_qr
from src.telegram.states import MainMenu

show_telegram_qr = on_show_telegram_qr.__dishka_orig_func__  # type: ignore[attr-defined]
show_web_qr = on_show_web_qr.__dishka_orig_func__  # type: ignore[attr-defined]


def _dependencies() -> dict[str, object]:
    user = SimpleNamespace(id=42, referral_code="CODE")
    return {
        "callback": SimpleNamespace(answer=AsyncMock()),
        "widget": SimpleNamespace(),
        "dialog_manager": SimpleNamespace(
            middleware_data={USER_KEY: user},
            switch_to=AsyncMock(),
        ),
        "generate_referral_qr": SimpleNamespace(system=AsyncMock(return_value="qr-base64")),
        "notifier": SimpleNamespace(notify_user=AsyncMock()),
    }


@pytest.mark.asyncio
async def test_telegram_qr_encodes_only_the_bot_referral_link() -> None:
    dependencies = _dependencies()
    bot_service = SimpleNamespace(
        get_referral_url=AsyncMock(return_value="https://t.me/bot?start=ref_CODE")
    )

    await show_telegram_qr(**dependencies, bot_service=bot_service)  # type: ignore[arg-type]

    generator = dependencies["generate_referral_qr"]
    generator.system.assert_awaited_once_with(  # type: ignore[union-attr]
        "https://t.me/bot?start=ref_CODE"
    )
    notifier = dependencies["notifier"]
    payload = notifier.notify_user.await_args.kwargs["payload"]  # type: ignore[union-attr]
    assert payload.i18n_key == "msg-invite-qr.telegram"
    dependencies["callback"].answer.assert_awaited_once_with()  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_clean_pay_qr_encodes_only_the_canonical_web_referral_link() -> None:
    dependencies = _dependencies()

    await show_web_qr(  # type: ignore[arg-type]
        **dependencies,
        config=SimpleNamespace(
            web_enabled=True,
            web_cabinet_url="https://pay.example/auth/telegram/webapp?legacy=1",
        ),
        i18n=SimpleNamespace(get=Mock(return_value="unavailable")),
    )

    generator = dependencies["generate_referral_qr"]
    generator.system.assert_awaited_once_with(  # type: ignore[union-attr]
        "https://pay.example/invite/CODE"
    )
    notifier = dependencies["notifier"]
    payload = notifier.notify_user.await_args.kwargs["payload"]  # type: ignore[union-attr]
    assert payload.i18n_key == "msg-invite-qr.clean-pay"
    dependencies["callback"].answer.assert_awaited_once_with()  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_clean_pay_qr_fails_closed_if_web_invites_become_unavailable() -> None:
    dependencies = _dependencies()

    await show_web_qr(  # type: ignore[arg-type]
        **dependencies,
        config=SimpleNamespace(web_enabled=False, web_cabinet_url=""),
        i18n=SimpleNamespace(get=Mock(return_value="unavailable")),
    )

    dependencies["generate_referral_qr"].system.assert_not_awaited()  # type: ignore[union-attr]
    dependencies["notifier"].notify_user.assert_not_awaited()  # type: ignore[union-attr]
    dependencies["callback"].answer.assert_awaited_once_with(  # type: ignore[union-attr]
        text="unavailable",
        show_alert=True,
    )
    dependencies["dialog_manager"].switch_to.assert_awaited_once_with(  # type: ignore[union-attr]
        MainMenu.INVITE
    )
