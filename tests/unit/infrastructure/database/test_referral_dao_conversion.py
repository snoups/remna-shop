from typing import cast

from adaptix import Retort
from adaptix.conversion import ConversionRetort
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.enums import ReferralRewardState, ReferralRewardType
from src.infrastructure.database.dao.referral import ReferralDaoImpl
from src.infrastructure.database.models import ReferralReward


def test_referral_dao_resolves_reward_relationship_types_at_runtime() -> None:
    dao = ReferralDaoImpl(
        session=cast(AsyncSession, object()),
        retort=Retort(),
        conversion_retort=ConversionRetort(),
        redis=cast(Redis, object()),
    )

    assert callable(dao._convert_to_reward_dto)
    assert callable(dao._convert_to_reward_list)

    reward = dao._convert_to_reward_dto(
        ReferralReward(
            id=8,
            referral_id=101,
            user_id=2,
            type=ReferralRewardType.POINTS,
            amount=10,
            is_issued=False,
            state=ReferralRewardState.MANUAL_REQUIRED,
        )
    )

    assert reward.referral_id == 101
