from datetime import datetime
from typing import List, Optional, Protocol, TypeVar, Union
from uuid import UUID

from packaging.version import Version
from remnapy.enums import TrafficLimitStrategy
from remnapy.models import UserResponseDto
from remnapy.models.hwid import HwidDeviceDto

from src.application.dto import (
    PlanSnapshotDto,
    RemnaSubscriptionDto,
    SquadInfoDto,
    SubscriptionDto,
    UserDto,
)

T = TypeVar("T", SubscriptionDto, RemnaSubscriptionDto)


class Remnawave(Protocol):
    async def try_connection(self) -> Version: ...

    async def create_user(
        self,
        user: UserDto,
        plan: Optional[PlanSnapshotDto] = None,
        subscription: Optional[SubscriptionDto] = None,
    ) -> UserResponseDto: ...

    async def update_user(
        self,
        user: UserDto,
        user_id: int,
        plan: Optional[PlanSnapshotDto] = None,
        subscription: Optional[SubscriptionDto] = None,
        reset_traffic: bool = False,
    ) -> UserResponseDto: ...

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
    ) -> UserResponseDto: ...

    async def enable_user(self, user_id: int) -> None: ...

    async def disable_user(self, user_id: int) -> None: ...

    async def delete_user(self, user_id: int) -> bool: ...

    async def get_user_by_id(self, user_id: int) -> Optional[UserResponseDto]: ...

    async def get_user_by_username(self, username: str) -> Optional[UserResponseDto]: ...

    async def get_users_by_telegram_id(self, telegram_id: int) -> List[UserResponseDto]: ...

    async def get_users_by_email(self, email: str) -> List[UserResponseDto]: ...

    async def get_all_users(self, limit: int, offset: int) -> List[UserResponseDto]: ...

    async def get_devices(self, user_id: int) -> List[HwidDeviceDto]: ...

    async def delete_device(self, user_id: int, hwid: str) -> Optional[int]: ...

    async def delete_all_devices(self, user_id: int) -> None: ...

    async def drop_connections(self, user_id: int) -> None: ...

    async def reset_traffic(self, user_id: int) -> Optional[UserResponseDto]: ...

    async def revoke_subscription(self, user_id: int) -> None: ...

    async def get_squads_available(self) -> bool: ...

    async def get_internal_squads(self) -> List[SquadInfoDto]: ...

    async def get_external_squads(self) -> List[SquadInfoDto]: ...

    def apply_sync(
        self,
        target: T,
        source: Union[SubscriptionDto, RemnaSubscriptionDto],
    ) -> T: ...
