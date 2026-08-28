from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import UUID

from remnapy.enums import TrafficLimitStrategy

from src.core.constants import UNLIMITED_EXPIRE_YEAR
from src.core.enums import PlanType, SubscriptionStatus
from src.core.types import RemnaUserDto
from src.core.utils.converters import bytes_to_gb
from src.core.utils.time import datetime_now

from .base import BaseDto, TimestampMixin, TrackableMixin
from .plan import PlanSnapshotDto


@dataclass(frozen=True)
class SquadInfoDto:
    uuid: UUID
    name: str


@dataclass(kw_only=True)
class RemnaSubscriptionDto:
    id: int
    status: SubscriptionStatus
    expire_at: datetime
    url: str

    traffic_limit: int
    device_limit: int
    traffic_limit_strategy: TrafficLimitStrategy

    tag: Optional[str] = None
    internal_squads: list[UUID] = field(default_factory=list)
    external_squad: Optional[UUID] = None

    @classmethod
    def from_remna_user(cls, remna_user: RemnaUserDto) -> "RemnaSubscriptionDto":
        return cls(
            id=remna_user.id,
            status=SubscriptionStatus(remna_user.status),
            expire_at=remna_user.expire_at,
            url=remna_user.subscription_url,
            traffic_limit=bytes_to_gb(int(remna_user.traffic_limit_bytes)),
            device_limit=remna_user.hwid_device_limit or 0,
            traffic_limit_strategy=TrafficLimitStrategy(remna_user.traffic_limit_strategy),
            tag=remna_user.tag,
            internal_squads=[squad.uuid for squad in remna_user.active_internal_squads],
            external_squad=remna_user.external_squad_uuid,
        )


@dataclass(kw_only=True)
class SubscriptionDto(BaseDto, TrackableMixin, TimestampMixin):
    user_id: int = 0
    user_remna_id: int

    status: SubscriptionStatus = SubscriptionStatus.ACTIVE
    is_trial: bool = False
    disabled_by_channel_leave: bool = False

    traffic_limit: int
    device_limit: int
    traffic_limit_strategy: TrafficLimitStrategy

    tag: Optional[str] = None
    internal_squads: list[UUID] = field(default_factory=list)
    external_squad: Optional[UUID] = None

    expire_at: datetime
    url: str

    plan_snapshot: "PlanSnapshotDto"

    device_single_reset_at: Optional[datetime] = None
    device_all_reset_at: Optional[datetime] = None
    link_reset_at: Optional[datetime] = None

    @property
    def is_active(self) -> bool:
        return self.current_status == SubscriptionStatus.ACTIVE

    @property
    def is_expired(self) -> bool:
        return self.current_status == SubscriptionStatus.EXPIRED

    @property
    def is_unlimited(self) -> bool:
        return self.expire_at.year == UNLIMITED_EXPIRE_YEAR

    @property
    def current_status(self) -> SubscriptionStatus:
        if datetime_now() > self.expire_at:
            return SubscriptionStatus.EXPIRED
        return self.status

    @property
    def limit_type(self) -> PlanType:
        has_traffic = self.traffic_limit > 0
        has_devices = self.device_limit > 0

        if has_traffic and has_devices:
            return PlanType.BOTH
        elif has_traffic:
            return PlanType.TRAFFIC
        elif has_devices:
            return PlanType.DEVICES
        else:
            return PlanType.UNLIMITED

    @property
    def has_devices_limit(self) -> bool:
        return self.limit_type in (PlanType.DEVICES, PlanType.BOTH)

    @property
    def has_traffic_limit(self) -> bool:
        return self.limit_type in (PlanType.TRAFFIC, PlanType.BOTH)
