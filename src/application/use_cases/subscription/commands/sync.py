from loguru import logger

from src.application.common import Interactor, Remnawave
from src.application.common.dao import SubscriptionDao, UserDao
from src.application.common.policy import Permission
from src.application.common.uow import UnitOfWork
from src.application.dto import RemnaSubscriptionDto, UserDto
from src.application.use_cases.remnawave.commands.synchronization import (
    SyncRemnaUser,
    SyncRemnaUserDto,
)
from src.application.use_cases.subscription.queries.match import (
    MatchSubscription,
    MatchSubscriptionDto,
)
from src.core.enums import SubscriptionStatus


class CheckSubscriptionSyncState(Interactor[int, bool]):
    required_permission = Permission.USER_SYNC

    def __init__(
        self,
        user_dao: UserDao,
        subscription_dao: SubscriptionDao,
        remnawave: Remnawave,
        match_subscription: MatchSubscription,
    ) -> None:
        self.user_dao = user_dao
        self.subscription_dao = subscription_dao
        self.remnawave = remnawave
        self.match_subscription = match_subscription

    async def _execute(self, actor: UserDto, user_id: int) -> bool:
        target_user = await self.user_dao.get_by_id(user_id)
        if not target_user:
            raise ValueError(f"User '{user_id}' not found")

        bot_sub = await self.subscription_dao.get_current(target_user.id)

        remna_user = None
        if bot_sub:
            remna_user = await self.remnawave.get_user_by_id(bot_sub.user_remna_id)
        elif target_user.telegram_id:
            remna_users = await self.remnawave.get_users_by_telegram_id(target_user.telegram_id)
            remna_user = remna_users[0] if remna_users else None

        remna_sub = RemnaSubscriptionDto.from_remna_user(remna_user) if remna_user else None

        if not remna_sub and not bot_sub:
            raise ValueError(f"{actor.log} No subscription data found to check for '{user_id}'")

        if await self.match_subscription.system(MatchSubscriptionDto(bot_sub, remna_sub)):
            logger.info(f"{actor.log} Subscription data for user '{user_id}' is consistent")
            return False

        logger.info(f"{actor.log} Inconsistency detected for user '{user_id}'")
        return True


class SyncSubscriptionFromRemnawave(Interactor[int, None]):
    required_permission = Permission.USER_SYNC

    def __init__(
        self,
        uow: UnitOfWork,
        user_dao: UserDao,
        subscription_dao: SubscriptionDao,
        remnawave: Remnawave,
        sync_remna_user: SyncRemnaUser,
    ) -> None:
        self.uow = uow
        self.user_dao = user_dao
        self.subscription_dao = subscription_dao
        self.remnawave = remnawave
        self.sync_remna_user = sync_remna_user

    async def _execute(self, actor: UserDto, user_id: int) -> None:
        async with self.uow:
            target_user = await self.user_dao.get_by_id(user_id)
            if not target_user:
                raise ValueError(f"User '{user_id}' not found")

            subscription = await self.subscription_dao.get_current(target_user.id)
            if not subscription:
                remna_users = (
                    await self.remnawave.get_users_by_telegram_id(target_user.telegram_id)
                    if target_user.telegram_id
                    else []
                )
                if not remna_users:
                    logger.info(f"{actor.log} No subscription to sync for user '{user_id}'")
                    return

                await self.sync_remna_user.system(SyncRemnaUserDto(remna_users[0], creating=False))
                logger.info(f"{actor.log} Imported subscription from panel for user '{user_id}'")
                return

            remna_user = await self.remnawave.get_user_by_id(subscription.user_remna_id)

            if not remna_user:
                await self.subscription_dao.update_status(
                    subscription.id,
                    SubscriptionStatus.DELETED,
                )
                await self.user_dao.clear_current_subscription(target_user.id)
                logger.info(
                    f"{actor.log} Deleted subscription for user '{user_id}' "
                    f"because it missing in Remnawave"
                )
            else:
                await self.sync_remna_user.system(SyncRemnaUserDto(remna_user, creating=False))
                logger.info(
                    f"{actor.log} Synchronized subscription from remnapy for user '{user_id}'"
                )

            await self.uow.commit()


class SyncSubscriptionFromRemnashop(Interactor[int, None]):
    required_permission = Permission.USER_SYNC

    def __init__(
        self,
        uow: UnitOfWork,
        user_dao: UserDao,
        subscription_dao: SubscriptionDao,
        remnawave: Remnawave,
        sync_remna_user: SyncRemnaUser,
    ) -> None:
        self.uow = uow
        self.user_dao = user_dao
        self.subscription_dao = subscription_dao
        self.remnawave = remnawave
        self.sync_remna_user = sync_remna_user

    async def _execute(self, actor: UserDto, user_id: int) -> None:
        async with self.uow:
            target_user = await self.user_dao.get_by_id(user_id)
            if not target_user:
                raise ValueError(f"User '{user_id}' not found")

            subscription = await self.subscription_dao.get_current(target_user.id)

            if not subscription:
                if target_user.telegram_id:
                    remna_users = await self.remnawave.get_users_by_telegram_id(
                        target_user.telegram_id
                    )
                    if remna_users:
                        await self.remnawave.delete_user(remna_users[0].id)
                        logger.info(
                            f"{actor.log} Deleted user '{remna_users[0].id}' from remnapy "
                            f"due to missing local subscription"
                        )
            else:
                remna_user = await self.remnawave.get_user_by_id(subscription.user_remna_id)

                if remna_user:
                    await self.remnawave.update_user(
                        user=target_user,
                        user_id=subscription.user_remna_id,
                        subscription=subscription,
                    )
                    logger.info(
                        f"{actor.log} Updated user '{user_id}' in Remnawave with local data"
                    )
                else:
                    created_user = await self.remnawave.create_user(
                        user=target_user,
                        subscription=subscription,
                    )
                    await self.sync_remna_user.system(
                        SyncRemnaUserDto(created_user, creating=False)
                    )
                    logger.info(
                        f"{actor.log} Recreated user '{user_id}' in Remnawave with local data"
                    )

            await self.uow.commit()
