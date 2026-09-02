from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.telegram.routers.menu.getters import invite_getter

invite_getter_impl = invite_getter.__dishka_orig_func__  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_telegram_invite_shows_bot_and_clean_pay_links_without_subscription_or_email() -> (
    None
):
    bot_service = SimpleNamespace(
        get_referral_url=AsyncMock(return_value="https://t.me/shop_bot?start=invite-CODE"),
        get_support_url=Mock(return_value="https://t.me/support"),
    )
    data = await invite_getter_impl(  # type: ignore[arg-type]
        dialog_manager=SimpleNamespace(),
        config=SimpleNamespace(
            web_enabled=True,
            web_cabinet_url="https://pay.example.com/auth/telegram/webapp?legacy=1",
        ),
        user=SimpleNamespace(
            id=42,
            referral_code="CODE",
            points=0,
            # Telegram identity is the trusted boundary; no email/subscription
            # fields are needed to render either invitation path.
        ),
        bot_service=bot_service,
        i18n=SimpleNamespace(get=Mock(return_value="Withdraw")),
        settings_dao=SimpleNamespace(
            get=AsyncMock(
                return_value=SimpleNamespace(
                    referral=SimpleNamespace(reward=SimpleNamespace(type="POINTS", is_points=True)),
                    extra=SimpleNamespace(referral_reset=SimpleNamespace(enabled=False)),
                )
            )
        ),
        referral_dao=SimpleNamespace(
            get_referrals_count=AsyncMock(return_value=0),
            get_referrals_with_payment_count=AsyncMock(return_value=0),
        ),
    )

    assert data["referral_url"] == "https://t.me/shop_bot?start=invite-CODE"
    assert data["web_referral_url"] == "https://pay.example.com/invite/CODE"
    assert data["has_web_referral_url"] == 1
