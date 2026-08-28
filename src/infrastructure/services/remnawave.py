import asyncio
from dataclasses import fields, is_dataclass
from datetime import datetime, timedelta
from typing import Optional, Union
from uuid import UUID

from loguru import logger
from packaging.version import Version
from remnapy import RemnawaveSDK
from remnapy.enums import TrafficLimitStrategy
from remnapy.exceptions import AuthenticationError, ConflictError, NotFoundError
from remnapy.models import (
    CreateUserRequestDto,
    DeleteUserAllHwidDeviceRequestDto,
    DeleteUserHwidDeviceRequestDto,
    DropByUserIds,
    DropConnectionsRequestDto,
    GetMetadataResponseDto,
    TargetAllNodes,
    UpdateUserRequestDto,
    UserResponseDto,
)
from remnapy.models.hwid import HwidDeviceDto

from src.application.common import Remnawave
from src.application.common.remnawave import T
from src.application.dto import (
    PlanSnapshotDto,
    RemnaSubscriptionDto,
    SquadInfoDto,
    SubscriptionDto,
    UserDto,
)
from src.core.constants import REMNAWAVE_MIN_VERSION
from src.core.enums import SubscriptionStatus
from src.core.utils.converters import days_to_datetime, gb_to_bytes
from src.core.utils.time import datetime_now


class RemnawaveImpl(Remnawave):
    def __init__(self, sdk: RemnawaveSDK) -> None:
        self.sdk = sdk

    async def try_connection(self) -> Version:
        for attempt in range(1, 4):
            try:
                metadata = await self.sdk.system.get_metadata()
                break
            except AuthenticationError as e:
                logger.error(f"Authentication failed when connecting to Remnawave panel: '{e}'")
                raise
            except Exception as e:
                if attempt < 3:
                    logger.warning(
                        f"Failed to connect to Remnawave panel (attempt {attempt}/3): '{e}', "
                        f"retrying in 5s..."
                    )
                    await asyncio.sleep(5)
                else:
                    logger.error(f"Failed to connect to Remnawave panel after 3 attempts: '{e}'")
                    raise

        if not isinstance(metadata, GetMetadataResponseDto):
            logger.error(f"Invalid response from Remnawave panel: '{metadata}'")
            raise ValueError(f"Invalid response from Remnawave panel: {metadata}")

        panel_version = Version(metadata.version)
        if panel_version < REMNAWAVE_MIN_VERSION:
            logger.error(
                f"Remnawave panel version '{panel_version}' is not compatible. "
                f"Minimum required version: '{REMNAWAVE_MIN_VERSION}'"
            )
            raise ValueError(
                f"Remnawave panel version '{panel_version}' is not compatible. "
                f"Minimum required version: '{REMNAWAVE_MIN_VERSION}'"
            )

        logger.info(f"Successfully connected to Remnawave panel (version: {panel_version})")
        return panel_version

    async def create_user(
        self,
        user: UserDto,
        plan: Optional[PlanSnapshotDto] = None,
        subscription: Optional[SubscriptionDto] = None,
    ) -> UserResponseDto:
        request_dto = self._build_create_request(user, plan, subscription)

        try:
            created_user = await self.sdk.users.create_user(request_dto)
            logger.info(
                f"RemnaUser '{created_user.username}' created successfully. "
                f"ID: '{created_user.id}', telegram_id: '{created_user.telegram_id}'"
            )
            return created_user
        except ConflictError:
            logger.warning(
                f"RemnaUser '{request_dto.username}' already exists in panel, "
                f"fetching the existing user"
            )
            existing_user = await self.sdk.users.get_user_by_username(request_dto.username)
            logger.info(
                f"Fetched existing RemnaUser '{existing_user.username}' "
                f"with ID '{existing_user.id}' from panel"
            )
            return existing_user

    async def update_user(
        self,
        user: UserDto,
        user_id: int,
        plan: Optional[PlanSnapshotDto] = None,
        subscription: Optional[SubscriptionDto] = None,
        reset_traffic: bool = False,
    ) -> UserResponseDto:
        request_dto = self._build_update_request(user, user_id, plan, subscription)

        try:
            remna_user = await self.sdk.users.update_user(request_dto)
            logger.info(
                f"RemnaUser '{remna_user.username}' updated successfully. "
                f"ID: '{remna_user.id}', telegram_id: '{remna_user.telegram_id}'"
            )
        except NotFoundError:
            logger.warning(f"RemnaUser '{request_dto.username}' with ID '{user_id}' not found")
            raise

        if reset_traffic:
            await self.reset_traffic(user_id)

        return remna_user

    async def apply_grace(
        self,
        user_id: int,
        expire_at: datetime,
        internal_squads: list[UUID],
        external_squad: Optional[UUID],
        traffic_bytes: int,
        traffic_strategy: TrafficLimitStrategy,
        tag: Optional[str],
        device_limit: int,
    ) -> UserResponseDto:
        request_dto = UpdateUserRequestDto(
            id=user_id,
            expire_at=expire_at,
            status=SubscriptionStatus.ACTIVE,
            traffic_limit_strategy=traffic_strategy,
            traffic_limit_bytes=traffic_bytes,
            hwid_device_limit=device_limit,
            tag=tag,
            active_internal_squads=internal_squads,
            external_squad_uuid=external_squad,
        )
        remna_user = await self.sdk.users.update_user(request_dto)
        await self.reset_traffic(user_id)
        logger.info(f"Applied grace to RemnaUser '{user_id}'")
        return remna_user

    async def enable_user(self, user_id: int) -> None:
        try:
            await self.sdk.users.enable_user(user_id)
            logger.info(f"RemnaUser '{user_id}' enabled successfully")
        except NotFoundError:
            logger.debug(f"RemnaUser '{user_id}' not found in panel")
            raise

    async def disable_user(self, user_id: int) -> None:
        try:
            await self.sdk.users.disable_user(user_id)
            logger.info(f"RemnaUser '{user_id}' disabled successfully")
        except NotFoundError:
            logger.debug(f"RemnaUser '{user_id}' not found in panel")
            raise

    async def delete_user(self, user_id: int) -> bool:
        try:
            await self.sdk.users.delete_user(user_id)
            logger.info(f"RemnaUser '{user_id}' deleted successfully")
            return True
        except NotFoundError:
            logger.debug(f"RemnaUser '{user_id}' not found in panel")
            return False

    async def get_user_by_id(self, user_id: int) -> Optional[UserResponseDto]:
        try:
            remna_user = await self.sdk.users.get_user_by_id(user_id)
            logger.info(f"Fetched RemnaUser '{user_id}' from panel")
            return remna_user
        except NotFoundError:
            logger.debug(f"RemnaUser '{user_id}' not found in panel")
            return None

    async def get_user_by_username(self, username: str) -> Optional[UserResponseDto]:
        try:
            remna_user = await self.sdk.users.get_user_by_username(username)
            logger.debug(f"Fetched RemnaUser '{username}' with ID '{remna_user.id}' from panel")
            return remna_user
        except NotFoundError:
            logger.debug(f"RemnaUser '{username}' not found in panel")
            return None

    async def get_users_by_telegram_id(self, telegram_id: int) -> list[UserResponseDto]:
        response = await self.sdk.users.get_users_stream(telegram_id=str(telegram_id))
        logger.debug(f"Fetched {len(response.users)} RemnaUsers for telegram_id '{telegram_id}'")
        return response.users

    async def get_all_users(self, limit: int, offset: int) -> list[UserResponseDto]:
        response = await self.sdk.users.get_all_users(start=offset, size=limit)
        logger.debug(f"Fetched {len(response.users)} RemnaUsers (limit={limit}, offset={offset})")
        return response.users

    async def get_user_by_email(self, email: str) -> list[UserResponseDto]:
        response = await self.sdk.users.get_users_stream(email=email)
        logger.debug(f"Fetched {len(response.users)} RemnaUsers for email '{email}'")
        return response.users

    async def get_devices(self, user_id: int) -> list[HwidDeviceDto]:
        response = await self.sdk.hwid.get_hwid_user(user_id)
        logger.debug(f"Fetched {response.total} devices for RemnaUser '{user_id}'")
        return response.devices if response.total else []

    async def delete_device(self, user_id: int, hwid_uuid: str) -> Optional[int]:
        try:
            response = await self.sdk.hwid.delete_hwid_to_user(
                DeleteUserHwidDeviceRequestDto(user_id=user_id, hwid=hwid_uuid)
            )
            logger.info(
                f"Deleted HWID device '{hwid_uuid}' for RemnaUser '{user_id}'. "
                f"Total devices now: {response.total}"
            )
        except NotFoundError:
            logger.debug(f"RemnaUser '{user_id}' not found in panel")
            return None

        return int(response.total)

    async def delete_all_devices(self, user_id: int) -> None:
        try:
            result = await self.sdk.hwid.delete_all_hwid_user(
                DeleteUserAllHwidDeviceRequestDto(user_id=user_id)
            )
        except NotFoundError:
            logger.debug(f"RemnaUser '{user_id}' not found in panel")
            return
        logger.info(f"Deleted all HWID devices ({result.total}) for RemnaUser '{user_id}'")

    async def drop_connections(self, user_id: int) -> None:
        try:
            await self.sdk.connections.drop_connections(
                body=DropConnectionsRequestDto(
                    drop_by=DropByUserIds(user_ids=[user_id]),
                    target_nodes=TargetAllNodes(),
                )
            )
            logger.info(f"Dropped connections for RemnaUser '{user_id}'")
        except Exception as e:
            logger.warning(f"Failed to drop connections for RemnaUser '{user_id}': {e}")

    async def reset_traffic(self, user_id: int) -> Optional[UserResponseDto]:
        try:
            remna_user = await self.sdk.users.reset_user_traffic(user_id)
            logger.info(f"Traffic for RemnaUser '{remna_user.id}' reset successfully")
            return remna_user
        except NotFoundError:
            logger.debug(f"RemnaUser '{user_id}' not found in panel")
            return None

    async def revoke_subscription(self, user_id: int) -> None:
        try:
            await self.sdk.users.revoke_user_subscription(user_id)
            logger.info(f"Subscription for RemnaUser '{user_id}' revoked successfully")
        except NotFoundError:
            logger.debug(f"RemnaUser '{user_id}' not found in panel")

    async def get_squads_available(self) -> bool:
        result = await self.sdk.internal_squads.get_internal_squads()
        return bool(result.internal_squads)

    async def get_internal_squads(self) -> list[SquadInfoDto]:
        result = await self.sdk.internal_squads.get_internal_squads()
        return [SquadInfoDto(uuid=s.uuid, name=s.name) for s in result.internal_squads]

    async def get_external_squads(self) -> list[SquadInfoDto]:
        result = await self.sdk.external_squads.get_external_squads()
        return [SquadInfoDto(uuid=s.uuid, name=s.name) for s in result.external_squads]

    def apply_sync(self, target: T, source: Union[SubscriptionDto, RemnaSubscriptionDto]) -> T:
        if not is_dataclass(target) or not is_dataclass(source):
            raise TypeError("Both target and source must be dataclasses")

        target_fields = {f.name for f in fields(target)}
        source_fields = {f.name for f in fields(source)}

        field_map = {"user_remna_id": "id"}

        for target_field, source_field in field_map.items():
            if target_field in target_fields and source_field in source_fields:
                old_value = getattr(target, target_field)
                new_value = getattr(source, source_field)

                if old_value != new_value:
                    logger.debug(
                        f"Field '{target_field}' changed from '{old_value}' to '{new_value}'"
                    )
                    setattr(target, target_field, new_value)

        common_fields = target_fields & source_fields

        for field_name in common_fields:
            old_value = getattr(target, field_name)
            new_value = getattr(source, field_name)

            if old_value != new_value:
                logger.debug(f"Field '{field_name}' changed from '{old_value}' to '{new_value}'")
                setattr(target, field_name, new_value)

        return target

    def _build_create_request(
        self,
        user: UserDto,
        plan: Optional[PlanSnapshotDto],
        subscription: Optional[SubscriptionDto],
    ) -> CreateUserRequestDto:
        if subscription:
            return CreateUserRequestDto(
                username=user.remna_name,
                telegram_id=user.telegram_id,
                expire_at=subscription.expire_at,
                traffic_limit_strategy=subscription.traffic_limit_strategy,
                traffic_limit_bytes=gb_to_bytes(subscription.traffic_limit),
                hwid_device_limit=subscription.device_limit,
                description=user.remna_description,
                email=user.email,
                tag=subscription.tag,
                active_internal_squads=subscription.internal_squads,
                external_squad_uuid=subscription.external_squad,
            )

        if plan:
            return CreateUserRequestDto(
                username=user.remna_name,
                telegram_id=user.telegram_id,
                expire_at=days_to_datetime(plan.duration),
                traffic_limit_strategy=plan.traffic_limit_strategy,
                traffic_limit_bytes=gb_to_bytes(plan.traffic_limit),
                hwid_device_limit=plan.device_limit,
                description=user.remna_description,
                email=user.email,
                tag=plan.tag,
                active_internal_squads=plan.internal_squads,
                external_squad_uuid=plan.external_squad,
            )

        return CreateUserRequestDto(
            username=user.remna_name,
            telegram_id=user.telegram_id,
            expire_at=datetime_now() + timedelta(days=3650),
            description=user.remna_description,
            email=user.email,
        )

    def _build_update_request(
        self,
        user: UserDto,
        user_id: int,
        plan: Optional[PlanSnapshotDto],
        subscription: Optional[SubscriptionDto],
    ) -> UpdateUserRequestDto:
        if subscription:
            return UpdateUserRequestDto(
                id=user_id,
                telegram_id=user.telegram_id,
                expire_at=subscription.expire_at,
                status=(
                    SubscriptionStatus.DISABLED
                    if subscription.status == SubscriptionStatus.DISABLED
                    else SubscriptionStatus.ACTIVE
                ),
                traffic_limit_strategy=subscription.traffic_limit_strategy,
                traffic_limit_bytes=gb_to_bytes(subscription.traffic_limit),
                hwid_device_limit=subscription.device_limit,
                description=user.remna_description,
                email=user.email,
                tag=subscription.tag,
                active_internal_squads=subscription.internal_squads,
                external_squad_uuid=subscription.external_squad,
            )

        if plan:
            return UpdateUserRequestDto(
                id=user_id,
                telegram_id=user.telegram_id,
                expire_at=days_to_datetime(plan.duration),
                status=SubscriptionStatus.ACTIVE,
                traffic_limit_strategy=plan.traffic_limit_strategy,
                traffic_limit_bytes=gb_to_bytes(plan.traffic_limit),
                hwid_device_limit=plan.device_limit,
                description=user.remna_description,
                email=user.email,
                tag=plan.tag,
                active_internal_squads=plan.internal_squads,
                external_squad_uuid=plan.external_squad,
            )

        raise ValueError("Either 'plan' or 'subscription' must be provided")
