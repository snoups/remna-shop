from dataclasses import dataclass
from datetime import timedelta

from loguru import logger

from src.application.common import EventPublisher, Interactor
from src.application.common.dao import SettingsDao, SubscriptionDao, UserDao
from src.application.common.policy import Permission, PermissionPolicy
from src.application.common.remnawave import Remnawave
from src.application.common.uow import UnitOfWork
from src.application.dto import UserDto
from src.application.events import UserAllDevicesDeletedEvent
from src.core.exceptions import CooldownError, PermissionDeniedError
from src.core.utils.time import datetime_now


@dataclass(frozen=True)
class DeleteUserDeviceDto:
    user_id: int
    hwid: str


class DeleteUserDevice(Interactor[DeleteUserDeviceDto, bool]):
    required_permission = Permission.PUBLIC

    def __init__(
        self,
        subscription_dao: SubscriptionDao,
        remnawave: Remnawave,
        settings_dao: SettingsDao,
        uow: UnitOfWork,
    ) -> None:
        self.subscription_dao = subscription_dao
        self.remnawave = remnawave
        self.settings_dao = settings_dao
        self.uow = uow

    async def _execute(self, actor: UserDto, data: DeleteUserDeviceDto) -> bool:
        is_self = data.user_id == actor.id
        if not is_self and not PermissionPolicy.has_permission(actor, Permission.USER_EDITOR):
            logger.warning(
                f"{actor.log} denied deleting device of foreign user '{data.user_id}' "
                f"without USER_EDITOR"
            )
            raise PermissionDeniedError()

        settings = await self.settings_dao.get()
        extra = settings.extra.device_single_reset

        if not extra.enabled:
            raise ValueError("Single device reset is disabled")

        current_subscription = await self.subscription_dao.get_current(data.user_id)
        if not current_subscription:
            raise ValueError(f"Subscription for user_id '{data.user_id}' not found")

        if extra.cooldown_hours > 0 and current_subscription.device_single_reset_at:
            available_at = current_subscription.device_single_reset_at + timedelta(
                hours=extra.cooldown_hours
            )
            if datetime_now() < available_at:
                raise CooldownError(available_at)

        async with self.uow:
            remaining_devices = await self.remnawave.delete_device(
                current_subscription.user_remna_id,
                data.hwid,
            )
            await self.remnawave.drop_connections(current_subscription.user_remna_id)
            current_subscription.device_single_reset_at = datetime_now()
            await self.subscription_dao.update(current_subscription)
            await self.uow.commit()

        logger.info(f"{actor.log} Deleted device '{data.hwid}' for user_id '{data.user_id}'")
        return bool(remaining_devices)


class DeleteUserAllDevices(Interactor[None, None]):
    required_permission = Permission.PUBLIC

    def __init__(
        self,
        subscription_dao: SubscriptionDao,
        remnawave: Remnawave,
        settings_dao: SettingsDao,
        uow: UnitOfWork,
        event_publisher: EventPublisher,
    ) -> None:
        self.subscription_dao = subscription_dao
        self.remnawave = remnawave
        self.settings_dao = settings_dao
        self.uow = uow
        self.event_publisher = event_publisher

    async def _execute(self, actor: UserDto, data: None) -> None:
        settings = await self.settings_dao.get()
        extra = settings.extra.device_all_reset

        if not extra.enabled:
            raise ValueError("All devices reset is disabled")

        current_subscription = await self.subscription_dao.get_current(actor.id)
        if not current_subscription:
            raise ValueError(
                f"User '{actor.remna_name}' has no active subscription or device limit unlimited"
            )

        if extra.cooldown_hours > 0 and current_subscription.device_all_reset_at:
            available_at = current_subscription.device_all_reset_at + timedelta(
                hours=extra.cooldown_hours
            )
            if datetime_now() < available_at:
                raise CooldownError(available_at)

        devices = await self.remnawave.get_devices(current_subscription.user_remna_id)
        device_count = len(devices)

        async with self.uow:
            await self.remnawave.delete_all_devices(current_subscription.user_remna_id)
            await self.remnawave.drop_connections(current_subscription.user_remna_id)
            current_subscription.device_all_reset_at = datetime_now()
            await self.subscription_dao.update(current_subscription)
            await self.uow.commit()

        logger.info(f"{actor.log} Deleted all devices and dropped connections")

        if device_count:
            await self.event_publisher.publish(
                UserAllDevicesDeletedEvent(
                    user_id=actor.id,
                    telegram_id=actor.telegram_id,
                    username=actor.username,
                    name=actor.name,
                    email=actor.email,
                    device_count=device_count,
                )
            )


class ResetUserTraffic(Interactor[int, None]):
    required_permission = Permission.USER_EDITOR

    def __init__(
        self,
        user_dao: UserDao,
        subscription_dao: SubscriptionDao,
        remnawave: Remnawave,
    ) -> None:
        self.user_dao = user_dao
        self.subscription_dao = subscription_dao
        self.remnawave = remnawave

    async def _execute(self, actor: UserDto, user_id: int) -> None:
        target_user = await self.user_dao.get_by_id(user_id)
        if not target_user:
            raise ValueError(f"User '{user_id}' not found")

        subscription = await self.subscription_dao.get_current(target_user.id)
        if not subscription:
            raise ValueError(f"Subscription for user '{target_user.remna_name}' not found")

        try:
            await self.remnawave.reset_traffic(subscription.user_remna_id)
        except Exception as e:
            logger.error(
                f"Failed to reset traffic in Remnawave for user '{target_user.remna_name}': {e}"
            )
            raise

        logger.info(f"{actor.log} Reset traffic for user '{target_user.id}'")


class ReissueSubscription(Interactor[None, None]):
    required_permission = Permission.PUBLIC

    def __init__(
        self,
        subscription_dao: SubscriptionDao,
        remnawave: Remnawave,
        settings_dao: SettingsDao,
        uow: UnitOfWork,
    ) -> None:
        self.subscription_dao = subscription_dao
        self.remnawave = remnawave
        self.settings_dao = settings_dao
        self.uow = uow

    async def _execute(self, actor: UserDto, data: None) -> None:
        settings = await self.settings_dao.get()
        extra = settings.extra.link_reset

        if not extra.enabled:
            raise ValueError("Subscription link reset is disabled")

        current_subscription = await self.subscription_dao.get_current(actor.id)
        if not current_subscription:
            raise ValueError(f"No active subscription for user '{actor.remna_name}'")

        if extra.cooldown_hours > 0 and current_subscription.link_reset_at:
            available_at = current_subscription.link_reset_at + timedelta(
                hours=extra.cooldown_hours
            )
            if datetime_now() < available_at:
                raise CooldownError(available_at)

        async with self.uow:
            await self.remnawave.revoke_subscription(current_subscription.user_remna_id)
            current_subscription.link_reset_at = datetime_now()
            await self.subscription_dao.update(current_subscription)
            await self.uow.commit()

        logger.info(f"{actor.log} Reissued subscription")


class ReissueUserSubscription(Interactor[int, None]):
    required_permission = Permission.USER_EDITOR

    def __init__(
        self, user_dao: UserDao, subscription_dao: SubscriptionDao, remnawave: Remnawave
    ) -> None:
        self.user_dao = user_dao
        self.subscription_dao = subscription_dao
        self.remnawave = remnawave

    async def _execute(self, actor: UserDto, user_id: int) -> None:
        target_user = await self.user_dao.get_by_id(user_id)
        if not target_user:
            raise ValueError(f"User '{user_id}' not found")

        current_subscription = await self.subscription_dao.get_current(target_user.id)

        if not current_subscription:
            raise ValueError(f"No active subscription for user '{target_user.remna_name}'")

        await self.remnawave.revoke_subscription(current_subscription.user_remna_id)

        logger.info(f"{actor.log} Reissued subscription for user '{target_user.id}'")
