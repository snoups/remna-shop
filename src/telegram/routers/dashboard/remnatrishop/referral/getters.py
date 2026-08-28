from typing import Any

from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.application.common import TranslatorRunner
from src.application.common.dao import SettingsDao
from src.core.enums import (
    ReferralAccrualStrategy,
    ReferralLevel,
    ReferralRewardStrategy,
    ReferralRewardType,
)


@inject
async def referral_getter(
    dialog_manager: DialogManager,
    settings_dao: FromDishka[SettingsDao],
    **kwargs: Any,
) -> dict[str, Any]:
    settings = await settings_dao.get()

    return {
        "is_enable": settings.referral.enable,
        "referral_level": settings.referral.level,
        "reward_type": settings.referral.reward.type,
        "accrual_strategy_type": settings.referral.accrual_strategy,
        "reward_strategy_type": settings.referral.reward.strategy,
    }


async def level_getter(dialog_manager: DialogManager, **kwargs: Any) -> dict[str, Any]:
    return {"levels": list(ReferralLevel)}


async def reward_type_getter(dialog_manager: DialogManager, **kwargs: Any) -> dict[str, Any]:
    return {"rewards": list(ReferralRewardType)}


async def accrual_strategy_getter(dialog_manager: DialogManager, **kwargs: Any) -> dict[str, Any]:
    return {"strategys": list(ReferralAccrualStrategy)}


async def reward_strategy_getter(dialog_manager: DialogManager, **kwargs: Any) -> dict[str, Any]:
    return {"strategys": list(ReferralRewardStrategy)}


@inject
async def reward_getter(
    dialog_manager: DialogManager,
    i18n: FromDishka[TranslatorRunner],
    settings_dao: FromDishka[SettingsDao],
    **kwargs: Any,
) -> dict[str, Any]:
    settings = await settings_dao.get()
    reward_config = settings.referral.reward.config

    levels_strings = []
    max_level = settings.referral.level
    for level, value in reward_config.items():
        if level <= max_level:
            levels_strings.append(
                i18n.get(
                    "msg-referral-reward-level",
                    level=level,
                    value=value,
                    reward_type=settings.referral.reward.type,
                    reward_strategy_type=settings.referral.reward.strategy,
                )
            )

    reward_string = "\n".join(levels_strings)

    return {
        "reward": reward_string,
        "reward_type": settings.referral.reward.type,
        "reward_strategy_type": settings.referral.reward.strategy,
    }
