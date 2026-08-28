from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID

from aiogram.enums import ButtonStyle
from pydantic import SecretStr
from remnapy.enums import TrafficLimitStrategy

from src.core.constants import REPOSITORY, T_ME
from src.core.enums import (
    AccessMode,
    ButtonType,
    Currency,
    MediaType,
    ReferralAccrualStrategy,
    ReferralLevel,
    ReferralRewardStrategy,
    ReferralRewardType,
    Role,
    SystemNotificationType,
    UserNotificationType,
)
from src.core.types import NotificationType

from .base import BaseDto, TimestampMixin, TrackableMixin


def get_default_notifications() -> dict[str, bool]:
    system_keys = {ntf.value: True for ntf in SystemNotificationType}
    user_keys = {ntf.value: True for ntf in UserNotificationType}
    return {**system_keys, **user_keys}


def get_default_notifications_routes() -> dict[str, "SystemNotificationRouteDto"]:
    return {ntf.value: SystemNotificationRouteDto() for ntf in SystemNotificationType}


@dataclass(kw_only=True)
class AccessSettingsDto(TrackableMixin):
    mode: AccessMode = AccessMode.PUBLIC
    registration_allowed: bool = True
    payments_allowed: bool = True

    def can_register(self) -> bool:
        if self.mode == AccessMode.RESTRICTED:
            return False
        return self.registration_allowed


@dataclass(kw_only=True)
class RequirementSettingsDto(TrackableMixin):
    rules_required: bool = False
    channel_required: bool = False

    rules_link: SecretStr = SecretStr("https://telegram.org/tos/")
    channel_id: Optional[int] = None
    channel_link: SecretStr = SecretStr("@remna_shop")

    @property
    def rules_url(self) -> str:
        return self.rules_link.get_secret_value()

    @property
    def channel_has_username(self) -> bool:
        return self.channel_link.get_secret_value().startswith("@")

    @property
    def channel_url(self) -> str:
        url = self.channel_link.get_secret_value()
        if self.channel_has_username:
            return f"{T_ME}{url[1:]}"
        return url


@dataclass(kw_only=True)
class SystemNotificationRouteDto:
    chat_id: Optional[int] = None
    thread_id: Optional[int] = None

    @property
    def effective_thread_id(self) -> Optional[int]:
        return None if self.thread_id == 1 else self.thread_id

    @property
    def is_configured(self) -> bool:
        return self.chat_id is not None


@dataclass(kw_only=True)
class NotificationsSettingsDto(TrackableMixin):
    settings: dict[str, bool] = field(default_factory=get_default_notifications)
    routes: dict[str, SystemNotificationRouteDto] = field(
        default_factory=get_default_notifications_routes
    )
    default_route: SystemNotificationRouteDto = field(default_factory=SystemNotificationRouteDto)

    def is_enabled(self, ntf_type: NotificationType) -> bool:
        return self.settings.get(ntf_type, True)

    def toggle(self, ntf_type: NotificationType) -> None:
        new_settings = self.settings.copy()
        new_settings[ntf_type] = not self.is_enabled(ntf_type)
        self.settings = new_settings

    def get_route(self, ntf_type: NotificationType) -> Optional[SystemNotificationRouteDto]:
        return self.routes.get(str(ntf_type))

    def resolve_route(self, ntf_type: NotificationType) -> Optional[SystemNotificationRouteDto]:
        route = self.routes.get(str(ntf_type))
        if route and route.is_configured:
            return route
        if self.default_route.is_configured:
            return self.default_route
        return None

    def set_default_route(self, chat_id: Optional[int], thread_id: Optional[int]) -> None:
        self.default_route = SystemNotificationRouteDto(chat_id=chat_id, thread_id=thread_id)

    def set_route(
        self,
        ntf_type: NotificationType,
        chat_id: Optional[int],
        thread_id: Optional[int],
    ) -> None:
        new_routes = self.routes.copy()
        new_routes[str(ntf_type)] = SystemNotificationRouteDto(chat_id=chat_id, thread_id=thread_id)
        self.routes = new_routes

    def clear_route(self, ntf_type: NotificationType) -> None:
        new_routes = self.routes.copy()
        new_routes.pop(str(ntf_type), None)
        self.routes = new_routes

    @property
    def system(self) -> list[tuple[NotificationType, bool]]:
        return [
            (ntf, self.is_enabled(SystemNotificationType(ntf.value)))
            for ntf in SystemNotificationType
        ]

    @property
    def user(self) -> list[tuple[NotificationType, bool]]:
        return [
            (ntf, self.is_enabled(UserNotificationType(ntf.value))) for ntf in UserNotificationType
        ]


@dataclass(kw_only=True)
class ReferralRewardSettingsDto(TrackableMixin):
    type: ReferralRewardType = ReferralRewardType.EXTRA_DAYS
    strategy: ReferralRewardStrategy = ReferralRewardStrategy.AMOUNT
    config: dict[ReferralLevel, int] = field(default_factory=lambda: {ReferralLevel.FIRST: 5})

    @property
    def is_identical(self) -> bool:
        values = list(self.config.values())
        return len(values) <= 1 or all(v == values[0] for v in values)

    @property
    def is_points(self) -> bool:
        return self.type == ReferralRewardType.POINTS

    @property
    def is_extra_days(self) -> bool:
        return self.type == ReferralRewardType.EXTRA_DAYS


@dataclass(kw_only=True)
class ReferralSettingsDto(TrackableMixin):
    enable: bool = True
    level: ReferralLevel = ReferralLevel.FIRST
    accrual_strategy: ReferralAccrualStrategy = ReferralAccrualStrategy.ON_FIRST_PAYMENT
    reward: ReferralRewardSettingsDto = field(default_factory=ReferralRewardSettingsDto)


@dataclass(kw_only=True)
class MenuButtonDto(TrackableMixin):
    index: int
    text: str = "btn-test"
    type: ButtonType = ButtonType.URL
    payload: str = REPOSITORY
    color: Optional[ButtonStyle] = None
    media_file_id: Optional[str] = None
    media_type: Optional[MediaType] = None
    is_active: bool = False
    required_role: Role = Role.USER
    subscribers_only: bool = False


@dataclass(kw_only=True)
class MenuSettingsDto(TrackableMixin):
    buttons: list[MenuButtonDto] = field(
        default_factory=lambda: [MenuButtonDto(index=i) for i in range(1, 7)]
    )


@dataclass(kw_only=True)
class BackupSettingsDto(TrackableMixin):
    enabled: bool = False
    interval_hours: int = 24
    max_files: int = 7
    send_to_chat: bool = True


@dataclass(kw_only=True)
class BlacklistSourceDto:
    id: int
    url: str
    name: Optional[str] = None


@dataclass(kw_only=True)
class BlacklistSettingsDto(TrackableMixin):
    blocked_ids: list[int] = field(default_factory=list)
    sources: list[BlacklistSourceDto] = field(default_factory=list)


@dataclass(kw_only=True)
class ResetFeatureSettingsDto(TrackableMixin):
    enabled: bool = True
    cooldown_hours: int = 0


@dataclass(kw_only=True)
class ExtraSettingsDto(TrackableMixin):
    device_single_reset: ResetFeatureSettingsDto = field(default_factory=ResetFeatureSettingsDto)
    device_all_reset: ResetFeatureSettingsDto = field(default_factory=ResetFeatureSettingsDto)
    link_reset: ResetFeatureSettingsDto = field(default_factory=ResetFeatureSettingsDto)
    referral_reset: ResetFeatureSettingsDto = field(default_factory=ResetFeatureSettingsDto)
    trial_channel_guard: bool = False
    mini_app_reserve: bool = False
    stars_require_paid_purchase: bool = False


@dataclass(kw_only=True)
class GraceSettingsDto(TrackableMixin):
    enabled: bool = False
    internal_squads: list[UUID] = field(default_factory=list)
    external_squad: Optional[UUID] = None
    traffic_mb: int = 0
    traffic_strategy: TrafficLimitStrategy = TrafficLimitStrategy.NO_RESET
    tag: Optional[str] = None
    duration_days: int = 0

    @property
    def is_indefinite(self) -> bool:
        return self.duration_days == 0


@dataclass(kw_only=True)
class SettingsDto(BaseDto, TrackableMixin, TimestampMixin):
    default_currency: Currency = Currency.XTR
    access: AccessSettingsDto = field(default_factory=AccessSettingsDto)
    requirements: RequirementSettingsDto = field(default_factory=RequirementSettingsDto)
    notifications: NotificationsSettingsDto = field(default_factory=NotificationsSettingsDto)
    referral: ReferralSettingsDto = field(default_factory=ReferralSettingsDto)
    menu: MenuSettingsDto = field(default_factory=MenuSettingsDto)
    backup: BackupSettingsDto = field(default_factory=BackupSettingsDto)
    blacklist: BlacklistSettingsDto = field(default_factory=BlacklistSettingsDto)
    extra: ExtraSettingsDto = field(default_factory=ExtraSettingsDto)
    grace: GraceSettingsDto = field(default_factory=GraceSettingsDto)
