from dataclasses import dataclass
from typing import Optional

from loguru import logger
from remnapy import RemnawaveSDK
from remnapy.models import GetExternalSquadByUuidResponseDto
from remnapy.models.hwid import HwidDeviceDto

from src.application.common import Interactor, Remnawave
from src.application.common.dao import SettingsDao, SubscriptionDao, UserDao
from src.application.common.policy import Permission
from src.application.dto import SubscriptionDto, UserDto
from src.core.config import AppConfig
from src.core.types import RemnaUserDto


@dataclass(frozen=True)
class GetUserProfileResultDto:
    target_user: UserDto
    subscription: Optional[SubscriptionDto]
    show_points: bool
    is_not_self: bool
    can_edit: bool


class GetUserProfile(Interactor[int, GetUserProfileResultDto]):
    required_permission = Permission.USER_EDITOR

    def __init__(
        self,
        user_dao: UserDao,
        settings_dao: SettingsDao,
        subscription_dao: SubscriptionDao,
        config: AppConfig,
    ) -> None:
        self.user_dao = user_dao
        self.settings_dao = settings_dao
        self.subscription_dao = subscription_dao
        self.config = config

    async def _execute(self, actor: UserDto, user_id: int) -> GetUserProfileResultDto:
        target_user = await self.user_dao.get_by_id(user_id)

        if not target_user:
            raise ValueError(f"User '{user_id}' not found")

        settings = await self.settings_dao.get()
        subscription = await self.subscription_dao.get_current(target_user.id)

        logger.info(f"{actor.log} Viewed details for user '{user_id}'")

        return GetUserProfileResultDto(
            target_user=target_user,
            subscription=subscription,
            show_points=settings.referral.reward.is_points,
            is_not_self=target_user.id != actor.id,
            can_edit=actor.role > target_user.role,
        )


@dataclass(frozen=True)
class GetUserProfileSubscriptionResultDto:
    subscription: SubscriptionDto
    remna_user: RemnaUserDto
    last_node_name: Optional[str] = None
    external_squad: Optional[GetExternalSquadByUuidResponseDto] = None

    @property
    def can_edit(self) -> bool:
        return not self.subscription.is_expired

    @property
    def formatted_internal_squads(self) -> Optional[str]:
        if not self.remna_user.active_internal_squads:
            return None
        return ", ".join(s.name for s in self.remna_user.active_internal_squads)

    @property
    def formatted_external_squad(self) -> Optional[str]:
        if not self.external_squad:
            return None
        return self.external_squad.name


class GetUserProfileSubscription(Interactor[int, GetUserProfileSubscriptionResultDto]):
    required_permission = Permission.USER_SUBSCRIPTION_EDITOR

    def __init__(
        self,
        user_dao: UserDao,
        subscription_dao: SubscriptionDao,
        remnawave: Remnawave,
        remnawave_sdk: RemnawaveSDK,
    ) -> None:
        self.user_dao = user_dao
        self.subscription_dao = subscription_dao
        self.remnawave = remnawave
        self.remnawave_sdk = remnawave_sdk

    async def _execute(
        self,
        actor: UserDto,
        user_id: int,
    ) -> GetUserProfileSubscriptionResultDto:
        target_user = await self.user_dao.get_by_id(user_id)
        if not target_user:
            raise ValueError(f"User '{user_id}' not found")
        subscription = await self.subscription_dao.get_current(target_user.id)
        if not subscription:
            raise ValueError(f"Current subscription for user '{user_id}' not found")

        remna_user = await self.remnawave.get_user_by_id(subscription.user_remna_id)
        if not remna_user:
            raise ValueError(f"User Remnawave for '{user_id}' not found")

        last_node = None
        if remna_user.last_connected_node_uuid:
            try:
                last_node = await self.remnawave_sdk.nodes.get_one_node(
                    remna_user.last_connected_node_uuid
                )
            except Exception as e:
                logger.error(f"Failed to fetch node info: {e}")

        logger.info(f"{actor.log} Viewed subscription details for '{user_id}'")

        external_squad = None
        if remna_user.external_squad_uuid:
            external_squad = await self.remnawave_sdk.external_squads.get_external_squad_by_uuid(
                uuid=remna_user.external_squad_uuid
            )

        return GetUserProfileSubscriptionResultDto(
            subscription=subscription,
            remna_user=remna_user,
            last_node_name=last_node.name if last_node else None,
            external_squad=external_squad,
        )


@dataclass(frozen=True)
class GetUserDevicesResultDto:
    devices: list[HwidDeviceDto]
    current_count: int
    max_count: int
    subscription: SubscriptionDto


class GetUserDevices(Interactor[int, GetUserDevicesResultDto]):
    required_permission = Permission.USER_SUBSCRIPTION_EDITOR

    def __init__(
        self,
        user_dao: UserDao,
        subscription_dao: SubscriptionDao,
        remnawave: Remnawave,
    ) -> None:
        self.user_dao = user_dao
        self.subscription_dao = subscription_dao
        self.remnawave = remnawave

    async def _execute(self, actor: UserDto, user_id: int) -> GetUserDevicesResultDto:
        target_user = await self.user_dao.get_by_id(user_id)
        if not target_user:
            raise ValueError(f"User '{user_id}' not found")

        subscription = await self.subscription_dao.get_current(target_user.id)
        if not subscription:
            raise ValueError(f"Subscription for '{user_id}' not found")

        devices = await self.remnawave.get_devices(subscription.user_remna_id)

        logger.info(f"{actor.log} Retrieved '{len(devices)}' devices for user '{user_id}'")

        return GetUserDevicesResultDto(
            devices=devices,
            current_count=len(devices),
            max_count=subscription.device_limit,
            subscription=subscription,
        )
