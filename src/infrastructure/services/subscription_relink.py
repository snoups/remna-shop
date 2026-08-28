from typing import Optional

from loguru import logger
from remnapy.models import UserResponseDto

from src.application.common import Remnawave
from src.application.common.dao import SubscriptionDao, UserDao
from src.application.common.uow import UnitOfWork
from src.application.dto import SubscriptionDto
from src.core.constants import REMNASHOP_PREFIX
from src.core.enums import SubscriptionStatus


class SubscriptionRelinker:
    """Re-link legacy subscriptions to Remnawave 3.2.x numeric user IDs.

    Older remnashop versions stored the panel 2.x user UUID in
    ``subscriptions.user_remna_id``. The panel 3.2.x API only exposes numeric
    user IDs, so migration 0047 stores the REMNA_ID_UNLINKED sentinel (-1)
    for such rows. On startup we resolve them by the deterministic username
    (``rs_<telegram_id>``) - falling back to a telegram_id lookup - and store
    the numeric ID. Subscriptions whose panel user no longer exists are marked
    EXPIRED, since there is nothing left to manage.
    """

    def __init__(
        self,
        uow: UnitOfWork,
        subscription_dao: SubscriptionDao,
        user_dao: UserDao,
        remnawave: Remnawave,
    ) -> None:
        self.uow = uow
        self.subscription_dao = subscription_dao
        self.user_dao = user_dao
        self.remnawave = remnawave

    async def relink(self) -> None:
        async with self.uow:
            unlinked = await self.subscription_dao.get_all_unlinked()
            if not unlinked:
                return

            logger.warning(
                f"Found '{len(unlinked)}' subscription(s) without a linked panel user, "
                "re-linking them by username"
            )
            for subscription in unlinked:
                await self._relink_one(subscription)
            await self.uow.commit()

    async def _relink_one(self, subscription: SubscriptionDto) -> None:
        user = await self.user_dao.get_by_id(subscription.user_id)
        if user is None or user.telegram_id is None:
            logger.warning(
                f"Subscription '{subscription.id}' belongs to a missing bot user "
                f"'{subscription.user_id}', skipping re-link"
            )
            return

        username = f"{REMNASHOP_PREFIX}{user.telegram_id}"
        try:
            remna_user: Optional[UserResponseDto] = await self.remnawave.get_user_by_username(
                username
            )
            if remna_user is None:
                candidates = await self.remnawave.get_users_by_telegram_id(user.telegram_id)
                if len(candidates) == 1:
                    remna_user = candidates[0]
        except Exception:
            logger.exception(
                f"Failed to look up panel user '{username}' for subscription "
                f"'{subscription.id}', will retry on next startup"
            )
            return

        if remna_user is not None:
            subscription.user_remna_id = remna_user.id
            await self.subscription_dao.update(subscription)
            logger.info(
                f"Re-linked subscription '{subscription.id}' of user "
                f"'{user.telegram_id}' to panel user '{remna_user.id}'"
            )
            return

        subscription.status = SubscriptionStatus.EXPIRED
        await self.subscription_dao.update(subscription)
        logger.warning(
            f"Panel user '{username}' not found in Remnawave; subscription "
            f"'{subscription.id}' of user '{user.telegram_id}' marked EXPIRED"
        )
