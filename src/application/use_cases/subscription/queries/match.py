from dataclasses import dataclass
from typing import Optional

from loguru import logger

from src.application.common import Interactor
from src.application.dto import RemnaSubscriptionDto, SubscriptionDto, UserDto


@dataclass(frozen=True)
class MatchSubscriptionDto:
    bot_subscription: Optional[SubscriptionDto]
    remna_subscription: Optional[RemnaSubscriptionDto]


class MatchSubscription(Interactor[MatchSubscriptionDto, bool]):
    required_permission = None

    async def _execute(self, actor: UserDto, data: MatchSubscriptionDto) -> bool:
        bot_sub = data.bot_subscription
        remna_sub = data.remna_subscription

        if not bot_sub or not remna_sub:
            return False

        is_match = (
            bot_sub.user_remna_id == remna_sub.id
            and bot_sub.status == remna_sub.status
            and bot_sub.url == remna_sub.url
            and bot_sub.traffic_limit == remna_sub.traffic_limit
            and bot_sub.device_limit == remna_sub.device_limit
            and bot_sub.expire_at == remna_sub.expire_at
            and bot_sub.external_squad == remna_sub.external_squad
            and bot_sub.traffic_limit_strategy == remna_sub.traffic_limit_strategy
            and bot_sub.tag == remna_sub.tag
            and sorted(bot_sub.internal_squads) == sorted(remna_sub.internal_squads)
        )

        if not is_match:
            logger.info(f"{actor.log} Subscription data mismatch for user")

        return is_match
