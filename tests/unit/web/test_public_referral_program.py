from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.application.dto import UserReferralStatsDto
from src.core.enums import (
    ReferralAccrualStrategy,
    ReferralLevel,
    ReferralRewardStrategy,
    ReferralRewardType,
)
from src.web.endpoints.public.referral import get_referral_program

get_referral_program_impl = get_referral_program.__dishka_orig_func__  # type: ignore[attr-defined]


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        referral=SimpleNamespace(
            enable=True,
            level=ReferralLevel.SECOND,
            accrual_strategy=ReferralAccrualStrategy.ON_FIRST_PAYMENT,
            reward=SimpleNamespace(
                type=ReferralRewardType.POINTS,
                strategy=ReferralRewardStrategy.AMOUNT,
                config={ReferralLevel.FIRST: 10, ReferralLevel.SECOND: 5},
            ),
        )
    )


def _dependencies(*, web_enabled: bool = True) -> dict[str, object]:
    stats = UserReferralStatsDto(
        referrer_telegram_id=None,
        referrer_email=None,
        referrer_username=None,
        referrals_level_1=3,
        referrals_level_2=1,
        reward_points=25,
        reward_days=7,
    )
    return {
        "user": SimpleNamespace(
            id=42,
            is_email_verified=True,
            referral_code="Code / 42",
            points=90,
        ),
        "settings_dao": SimpleNamespace(get=AsyncMock(return_value=_settings())),
        "referral_dao": SimpleNamespace(
            get_referrals_count=AsyncMock(return_value=4),
            get_referrals_with_payment_count=AsyncMock(return_value=2),
            get_user_referral_stats=AsyncMock(return_value=stats),
        ),
        "config": SimpleNamespace(
            web_enabled=web_enabled,
            web_cabinet_url="https://pay.example.com/auth/telegram/webapp?old=1",
        ),
    }


@pytest.mark.asyncio
async def test_referral_program_exposes_canonical_clean_pay_url_and_issued_totals() -> None:
    response = await get_referral_program_impl(**_dependencies())  # type: ignore[arg-type]

    assert response.web_referral_url == "https://pay.example.com/invite/Code%20%2F%2042"
    assert response.points_balance == 90
    assert response.total_points_issued == 25
    assert response.total_days_issued == 7
    assert response.invited_with_payment_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("subscription", [None, SimpleNamespace(is_trial=True)])
async def test_referral_program_does_not_require_a_paid_subscription(
    subscription: object,
) -> None:
    # The public contract deliberately has no SubscriptionDao dependency: a
    # verified user must be able to share Clean Pay before buying for themself.
    dependencies = _dependencies()
    dependencies["unused_subscription"] = subscription

    response = await get_referral_program_impl(  # type: ignore[arg-type]
        **{key: value for key, value in dependencies.items() if key != "unused_subscription"}
    )

    assert response.web_referral_url.startswith("https://pay.example.com/invite/")


@pytest.mark.asyncio
async def test_referral_program_fails_closed_without_clean_pay_origin() -> None:
    dependencies = _dependencies(web_enabled=False)

    with pytest.raises(HTTPException) as exc_info:
        await get_referral_program_impl(**dependencies)  # type: ignore[arg-type]

    assert exc_info.value.status_code == 503
    assert "not configured" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_referral_program_requires_verified_email() -> None:
    dependencies = _dependencies()
    dependencies["user"].is_email_verified = False  # type: ignore[attr-defined]

    with pytest.raises(HTTPException) as exc_info:
        await get_referral_program_impl(**dependencies)  # type: ignore[arg-type]

    assert exc_info.value.status_code == 403
    assert "verified email" in str(exc_info.value.detail)
    dependencies["settings_dao"].get.assert_not_awaited()  # type: ignore[attr-defined]
