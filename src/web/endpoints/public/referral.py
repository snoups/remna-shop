from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, HTTPException, status

from src.application.common.dao import ReferralDao, SettingsDao
from src.core.config import AppConfig
from src.core.utils.referral_urls import build_web_referral_url
from src.web.schemas import ReferralProgramResponse, ReferralRewardLevelResponse

from ._common import CurrentUser

router = APIRouter(prefix="/referral", tags=["Public - Referral"])


@router.get("/program", response_model=ReferralProgramResponse)
@inject
async def get_referral_program(
    user: CurrentUser,
    settings_dao: FromDishka[SettingsDao],
    referral_dao: FromDishka[ReferralDao],
    config: FromDishka[AppConfig],
) -> ReferralProgramResponse:
    if not user.is_email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Referral program is available only for users with verified email",
        )

    settings = await settings_dao.get()

    if not settings.referral.enable:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Referral program is disabled",
        )

    web_referral_url = build_web_referral_url(
        config.web_cabinet_url if config.web_enabled else "",
        user.referral_code,
    )
    if not web_referral_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Web cabinet referral URL is not configured",
        )

    invited_count = await referral_dao.get_referrals_count(user.id)
    invited_with_payment_count = await referral_dao.get_referrals_with_payment_count(user.id)
    referral_stats = await referral_dao.get_user_referral_stats(user.id)

    reward_levels = [
        ReferralRewardLevelResponse(level=level.value, value=value)
        for level, value in sorted(
            settings.referral.reward.config.items(),
            key=lambda item: item[0].value,
        )
        if level.value <= settings.referral.level.value
    ]

    return ReferralProgramResponse(
        enabled=settings.referral.enable,
        referral_code=user.referral_code,
        web_referral_url=web_referral_url,
        invited_count=invited_count,
        invited_with_payment_count=invited_with_payment_count,
        points_balance=user.points,
        total_points_issued=referral_stats.reward_points,
        total_days_issued=referral_stats.reward_days,
        reward_type=settings.referral.reward.type.value,
        reward_strategy=settings.referral.reward.strategy.value,
        accrual_strategy=settings.referral.accrual_strategy.value,
        max_level=settings.referral.level.value,
        reward_levels=reward_levels,
    )
