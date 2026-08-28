from dataclasses import dataclass

from loguru import logger

from src.application.common import Interactor
from src.application.common.dao import PromocodeDao, SubscriptionDao, UserDao
from src.application.common.policy import Permission
from src.application.dto import PromocodeDto, SubscriptionDto, UserDto
from src.core.constants import UNLIMITED_EXPIRE_YEAR
from src.core.enums import PromocodeAvailability, PromocodeRewardType
from src.core.exceptions import (
    PromocodeAlreadyActivatedError,
    PromocodeExpiredError,
    PromocodeNotAvailableError,
    PromocodeNotFoundError,
)
from src.core.utils.time import datetime_now

SUBSCRIPTION_REQUIRED_REWARDS = frozenset(
    {
        PromocodeRewardType.DURATION,
        PromocodeRewardType.TRAFFIC,
        PromocodeRewardType.DEVICES,
    }
)


@dataclass(frozen=True)
class ValidatePromocodeDto:
    code: str
    user: UserDto


class ValidatePromocode(Interactor[ValidatePromocodeDto, PromocodeDto]):
    required_permission = Permission.PUBLIC

    def __init__(
        self,
        promocode_dao: PromocodeDao,
        user_dao: UserDao,
        subscription_dao: SubscriptionDao,
    ) -> None:
        self.promocode_dao = promocode_dao
        self.user_dao = user_dao
        self.subscription_dao = subscription_dao

    async def _execute(self, actor: UserDto, data: ValidatePromocodeDto) -> PromocodeDto:
        user = data.user
        code = data.code.strip().upper()

        promo = await self.promocode_dao.get_by_code(code)

        if not promo or not promo.is_active:
            logger.info(f"{actor.log} Promocode '{code}' not found or inactive")
            raise PromocodeNotFoundError(f"Promocode '{code}' not found")

        assert promo.id is not None

        if promo.expires_at is not None and datetime_now() > promo.expires_at:
            logger.info(f"{actor.log} Promocode '{code}' expired")
            raise PromocodeExpiredError("Promocode has expired")

        if promo.max_activations is not None:
            count = await self.promocode_dao.get_activations_count(promo.id)
            if count >= promo.max_activations:
                logger.info(f"{actor.log} Promocode '{code}' max activations reached")
                raise PromocodeNotAvailableError("Promocode activation limit reached")

        if not promo.is_reusable:
            existing = await self.promocode_dao.get_activation_by_user(promo.id, user.id)
            if existing:
                logger.info(f"{actor.log} Promocode '{code}' already activated by user")
                raise PromocodeAlreadyActivatedError("Promocode already activated")

        if promo.reward_type in SUBSCRIPTION_REQUIRED_REWARDS:
            await self._check_subscription_requirements(actor, user, promo)

        await self._check_availability(actor, user, promo)

        logger.info(f"{actor.log} Promocode '{code}' is valid for user")
        return promo

    async def _check_subscription_requirements(
        self, actor: UserDto, user: UserDto, promo: PromocodeDto
    ) -> None:
        current = await self.subscription_dao.get_current(user.id)
        if current is None or not current.is_active:
            # An expired/disabled subscription has expire_at in the past; extending it
            # would push a past date to the panel, which rejects it. Require an active sub.
            logger.info(f"{actor.log} Promocode '{promo.code}' requires an active subscription")
            raise PromocodeNotAvailableError("Active subscription required for this promocode")
        if promo.reward_type == PromocodeRewardType.DURATION and current.is_trial:
            # A DURATION promo would extend the free trial's expiry, effectively
            # prolonging the trial. Block it — trials are not eligible.
            logger.info(f"{actor.log} Promocode '{promo.code}' cannot extend a trial subscription")
            raise PromocodeNotAvailableError("Duration promocode not allowed on trial")
        if self._is_resource_unlimited(promo.reward_type, current):
            logger.info(f"{actor.log} Promocode '{promo.code}' resource already unlimited")
            raise PromocodeNotAvailableError("Resource is already unlimited")

    @staticmethod
    def _is_resource_unlimited(
        reward_type: PromocodeRewardType, subscription: SubscriptionDto
    ) -> bool:
        match reward_type:
            case PromocodeRewardType.DURATION:
                return subscription.expire_at.year == UNLIMITED_EXPIRE_YEAR
            case PromocodeRewardType.TRAFFIC:
                return subscription.traffic_limit == 0
            case PromocodeRewardType.DEVICES:
                return subscription.device_limit == 0
            case _:
                return False

    async def _check_availability(self, actor: UserDto, user: UserDto, promo: PromocodeDto) -> None:
        match promo.availability:
            case PromocodeAvailability.ALL:
                return

            case PromocodeAvailability.NEW:
                has_sub = await self.user_dao.has_any_subscription(user.id, include_trial=False)
                if has_sub:
                    raise PromocodeNotAvailableError("Promocode is for new users only")

            case PromocodeAvailability.EXISTING:
                has_sub = await self.user_dao.has_any_subscription(user.id, include_trial=False)
                if not has_sub:
                    raise PromocodeNotAvailableError("Promocode is for existing users only")

            case PromocodeAvailability.INVITED:
                is_invited = await self.user_dao.is_invited_user(user.id)
                if not is_invited:
                    raise PromocodeNotAvailableError("Promocode is for invited users only")
