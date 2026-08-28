from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from aiogram.utils.formatting import Text

from src.__version__ import __version__
from src.application.dto import BuildInfoDto, MediaDescriptorDto, MessagePayloadDto
from src.core.constants import REMNAWAVE_MAX_VERSION, REPOSITORY
from src.core.enums import (
    AccessMode,
    MediaType,
    PaymentGatewayType,
    PlanType,
    PurchaseType,
    SubscriptionStatus,
    SystemNotificationType,
)
from src.core.types import NotificationType

from .base import BaseEvent, SystemEvent


@dataclass(frozen=True, kw_only=True)
class RemnashopWelcomeEvent(BaseEvent):
    notification_type: NotificationType = field(
        default=SystemNotificationType.SYSTEM,
        init=False,
    )

    version: str = __version__
    repository: str = REPOSITORY

    @property
    def event_key(self) -> str:
        return "event-remnashop-welcome"

    def as_payload(self) -> "MessagePayloadDto":
        return MessagePayloadDto(
            i18n_key=self.event_key,
            i18n_kwargs={**asdict(self)},
            disable_default_markup=False,
            delete_after=None,
        )


@dataclass(frozen=True, kw_only=True)
class ErrorEvent(BaseEvent, BuildInfoDto):
    notification_type: NotificationType = field(
        default=SystemNotificationType.SYSTEM,
        init=False,
    )

    telegram_id: Optional[int] = field(default=None)
    username: Optional[str] = field(default=None)
    name: Optional[str] = field(default=None)

    exception: BaseException

    def as_payload(
        self,
        media: MediaDescriptorDto,
        error_type: str,
        error_message: Text,
    ) -> "MessagePayloadDto":
        data = self.__dict__.copy()
        data.pop("exception", None)

        return MessagePayloadDto(
            i18n_key=self.event_key,
            i18n_kwargs={
                **data,
                "error": f"{error_type}: {error_message.as_html()}",
            },
            media=media,
            media_type=MediaType.DOCUMENT,
            disable_default_markup=False,
            delete_after=None,
        )

    @property
    def event_key(self) -> str:
        return "event-error.general"


@dataclass(frozen=True, kw_only=True)
class RemnawaveErrorEvent(ErrorEvent):
    notification_type: NotificationType = field(
        default=SystemNotificationType.SYSTEM,
        init=False,
    )

    @property
    def event_key(self) -> str:
        return "event-error.remnawave"


@dataclass(frozen=True, kw_only=True)
class RemnawaveVersionWarningEvent(SystemEvent, BuildInfoDto):
    notification_type: NotificationType = field(
        default=SystemNotificationType.SYSTEM,
        init=False,
    )

    panel_version: str
    max_version: str = str(REMNAWAVE_MAX_VERSION)

    @property
    def event_key(self) -> str:
        return "event-error.remnawave-version"

    def as_payload(self) -> "MessagePayloadDto":
        return MessagePayloadDto(
            i18n_key=self.event_key,
            i18n_kwargs={**asdict(self)},
            disable_default_markup=False,
            delete_after=None,
        )


@dataclass(frozen=True, kw_only=True)
class BotInlineModeDisabledEvent(SystemEvent):
    notification_type: NotificationType = field(
        default=SystemNotificationType.SYSTEM,
        init=False,
    )

    @property
    def event_key(self) -> str:
        return "event-bot.inline-mode-disabled"

    def as_payload(self) -> "MessagePayloadDto":
        return MessagePayloadDto(
            i18n_key=self.event_key,
            disable_default_markup=False,
            delete_after=None,
        )


@dataclass(frozen=True, kw_only=True)
class WebhookErrorEvent(SystemEvent):
    notification_type: NotificationType = field(
        default=SystemNotificationType.SYSTEM,
        init=False,
    )

    error_message: Optional[str] = None

    @property
    def event_key(self) -> str:
        return "event-error.webhook"

    def as_payload(self) -> "MessagePayloadDto":
        return MessagePayloadDto(
            i18n_key=self.event_key,
            i18n_kwargs={"error": self.error_message or "—"},
            disable_default_markup=False,
            delete_after=None,
        )


@dataclass(frozen=True, kw_only=True)
class ChannelCheckErrorEvent(SystemEvent):
    notification_type: NotificationType = field(
        default=SystemNotificationType.SYSTEM,
        init=False,
    )

    telegram_id: int
    username: Optional[str]
    name: str
    reason: str

    @property
    def event_key(self) -> str:
        return "event-error.channel-check"


@dataclass(frozen=True, kw_only=True)
class NotificationErrorEvent(SystemEvent):
    notification_type: NotificationType = field(
        default=SystemNotificationType.SYSTEM,
        init=False,
    )

    chat_id: Optional[int]
    thread_id: Optional[int]
    reason: str

    @property
    def event_key(self) -> str:
        return "event-error.notification"


@dataclass(frozen=True, kw_only=True)
class BotLifecycleEvent(SystemEvent, BuildInfoDto):
    notification_type: NotificationType = field(
        default=SystemNotificationType.BOT_LIFECYCLE,
        init=False,
    )


@dataclass(frozen=True, kw_only=True)
class BotStartupEvent(BotLifecycleEvent):
    access_mode: AccessMode
    payments_allowed: bool
    registration_allowed: bool

    @property
    def event_key(self) -> str:
        return "event-bot.startup"


@dataclass(frozen=True, kw_only=True)
class BotShutdownEvent(BotLifecycleEvent):
    uptime: Any

    @property
    def event_key(self) -> str:
        return "event-bot.shutdown"


@dataclass(frozen=True, kw_only=True)
class BotUpdateEvent(SystemEvent):
    notification_type: NotificationType = field(
        default=SystemNotificationType.BOT_UPDATE,
        init=False,
    )

    local_version: str
    remote_version: str

    def as_payload(self) -> "MessagePayloadDto":
        return MessagePayloadDto(
            i18n_key=self.event_key,
            i18n_kwargs={**asdict(self)},
            disable_default_markup=False,
            delete_after=None,
        )

    @property
    def event_key(self) -> str:
        return "event-bot.update"


@dataclass(frozen=True, kw_only=True)
class UserEvent(SystemEvent):
    user_id: int = field(default=0)
    telegram_id: Optional[int] = field(default=None)
    username: Optional[str] = field(default=None)
    email: Optional[str] = field(default=None)
    name: str


@dataclass(frozen=True, kw_only=True)
class UserRegisteredEvent(UserEvent):
    notification_type: NotificationType = field(
        default=SystemNotificationType.USER_REGISTERED,
        init=False,
    )

    referrer_user_id: Optional[int] = field(default=None)
    referrer_telegram_id: Optional[int] = field(default=None)
    referrer_email: Optional[str] = field(default=None)
    referrer_username: Optional[str] = field(default=None)
    referrer_name: Optional[str] = field(default=None)

    ad_link_id: Optional[int] = field(default=None)
    ad_link_name: Optional[str] = field(default=None)
    ad_link_code: Optional[str] = field(default=None)

    def as_payload(self) -> "MessagePayloadDto":
        return MessagePayloadDto(
            i18n_key=self.event_key,
            i18n_kwargs={**asdict(self)},
            disable_default_markup=False,
            delete_after=None,
        )

    @property
    def event_key(self) -> str:
        return "event-user.registered"


@dataclass(frozen=True, kw_only=True)
class BlacklistRegistrationAttemptEvent(UserEvent):
    notification_type: NotificationType = field(
        default=SystemNotificationType.BLACKLIST_ATTEMPT,
        init=False,
    )

    def as_payload(self) -> "MessagePayloadDto":
        return MessagePayloadDto(
            i18n_key=self.event_key,
            i18n_kwargs={**asdict(self)},
            disable_default_markup=False,
            delete_after=None,
        )

    @property
    def event_key(self) -> str:
        return "event-blacklist.registration-attempt"


@dataclass(frozen=True, kw_only=True)
class UserFirstConnectionEvent(UserEvent):
    notification_type: NotificationType = field(
        default=SystemNotificationType.USER_FIRST_CONNECTION,
        init=False,
    )

    is_trial: bool
    subscription_id: int
    subscription_status: SubscriptionStatus
    traffic_used: Any
    traffic_limit: Any
    device_limit: Any
    expire_time: Any

    @property
    def event_key(self) -> str:
        return "event-user.first-connected"

    def as_payload(self) -> "MessagePayloadDto":
        return MessagePayloadDto(
            i18n_key=self.event_key,
            i18n_kwargs={**asdict(self)},
            disable_default_markup=False,
            delete_after=None,
        )


@dataclass(frozen=True, kw_only=True)
class UserDevicesUpdatedEvent(UserEvent):
    notification_type: NotificationType = field(
        default=SystemNotificationType.USER_DEVICES_UPDATED,
        init=False,
    )

    hwid: str
    platform: Optional[str]
    device_model: Optional[str]
    os_version: Optional[str]
    user_agent: Optional[str]

    def as_payload(self) -> "MessagePayloadDto":
        return MessagePayloadDto(
            i18n_key=self.event_key,
            i18n_kwargs={**asdict(self)},
            disable_default_markup=False,
            delete_after=None,
        )


@dataclass(frozen=True, kw_only=True)
class UserDeviceAddedEvent(UserDevicesUpdatedEvent):
    @property
    def event_key(self) -> str:
        return "event-user.device-added"


@dataclass(frozen=True, kw_only=True)
class UserDeviceDeletedEvent(UserDevicesUpdatedEvent):
    @property
    def event_key(self) -> str:
        return "event-user.device-deleted"


@dataclass(frozen=True, kw_only=True)
class NodeEvent(SystemEvent):
    country: str
    name: str

    address: str
    port: Optional[int]

    traffic_used: Any
    traffic_limit: Any
    last_status_message: Optional[str]
    last_status_change: Optional[str]


@dataclass(frozen=True, kw_only=True)
class NodeTrafficReachedEvent(NodeEvent):
    notification_type: NotificationType = field(
        default=SystemNotificationType.NODE_TRAFFIC_REACHED,
        init=False,
    )

    @property
    def event_key(self) -> str:
        return "event-node.traffic-reached"


@dataclass(frozen=True, kw_only=True)
class TorrentBlockerReportEvent(UserEvent):
    notification_type: NotificationType = field(
        default=SystemNotificationType.TORRENT_BLOCKER,
        init=False,
    )

    node_name: str
    blocked_ip: str
    block_duration: Any
    will_unblock_at: str
    protocol: str
    source: str
    destination: str

    @property
    def event_key(self) -> str:
        return "event-torrent-blocker.report"


@dataclass(frozen=True, kw_only=True)
class NodeStatusChangedEvent(NodeEvent):
    notification_type: NotificationType = field(
        default=SystemNotificationType.NODE_STATUS_CHANGED,
        init=False,
    )


@dataclass(frozen=True, kw_only=True)
class NodeConnectionLostEvent(NodeStatusChangedEvent):
    @property
    def event_key(self) -> str:
        return "event-node.connection-lost"


@dataclass(frozen=True, kw_only=True)
class NodeConnectionRestoredEvent(NodeStatusChangedEvent):
    @property
    def event_key(self) -> str:
        return "event-node.connection-restored"


@dataclass(frozen=True, kw_only=True)
class UserPurchaseEvent(UserEvent):
    notification_type: NotificationType = field(
        default=SystemNotificationType.SUBSCRIPTION,
        init=False,
    )

    purchase_type: PurchaseType
    is_trial_plan: bool

    payment_id: UUID
    gateway_type: PaymentGatewayType
    final_amount: Decimal
    discount_percent: int
    original_amount: Decimal
    currency: str

    plan_name: Any
    plan_type: PlanType
    plan_traffic_limit: Any
    plan_device_limit: Any
    plan_duration: Any

    previous_plan_name: Any = None
    previous_plan_type: Any = None
    previous_plan_traffic_limit: Any = None
    previous_plan_device_limit: Any = None
    previous_plan_duration: Any = None

    def as_payload(self) -> "MessagePayloadDto":
        return MessagePayloadDto(
            i18n_key=self.event_key,
            i18n_kwargs={**asdict(self)},
            disable_default_markup=False,
            delete_after=None,
        )

    @property
    def event_key(self) -> str:
        match self.purchase_type:
            case PurchaseType.NEW:
                return "event-subscription.new"
            case PurchaseType.RENEW:
                return "event-subscription.renew"
            case PurchaseType.CHANGE:
                return "event-subscription.change"


@dataclass(frozen=True, kw_only=True)
class TrialActivatedEvent(UserEvent):
    notification_type: NotificationType = field(
        default=SystemNotificationType.TRIAL_ACTIVATED,
        init=False,
    )

    is_trial_plan: bool = True
    plan_name: Any
    plan_type: PlanType
    plan_traffic_limit: Any
    plan_device_limit: Any
    plan_duration: Any

    def as_payload(self) -> "MessagePayloadDto":
        return MessagePayloadDto(
            i18n_key=self.event_key,
            i18n_kwargs={**asdict(self)},
            disable_default_markup=False,
            delete_after=None,
        )

    @property
    def event_key(self) -> str:
        return "event-subscription.trial"


@dataclass(frozen=True, kw_only=True)
class SubscriptionRevokedEvent(UserEvent):
    notification_type: NotificationType = field(
        default=SystemNotificationType.USER_REVOKED_SUBSCRIPTION,
        init=False,
    )

    is_trial: bool
    subscription_id: int
    subscription_status: SubscriptionStatus
    traffic_used: Any
    traffic_limit: Any
    device_limit: Any
    expire_time: Any

    def as_payload(self) -> "MessagePayloadDto":
        return MessagePayloadDto(
            i18n_key=self.event_key,
            i18n_kwargs={**asdict(self)},
            disable_default_markup=False,
            delete_after=None,
        )

    @property
    def event_key(self) -> str:
        return "event-subscription.revoked"


@dataclass(frozen=True, kw_only=True)
class PromocodeActivatedEvent(SystemEvent):
    notification_type: NotificationType = field(
        default=SystemNotificationType.PROMOCODE_ACTIVATED,
        init=False,
    )

    user_id: int
    telegram_id: Optional[int]
    username: Optional[str]
    name: str
    promocode_code: str
    reward_type: str
    reward: Optional[int]
    plan_name: Any

    @property
    def event_key(self) -> str:
        return "event-promocode.activated"

    def as_payload(self) -> "MessagePayloadDto":
        return MessagePayloadDto(
            i18n_key=self.event_key,
            i18n_kwargs={
                "telegram_id": self.telegram_id or 0,
                "username": self.username or 0,
                "name": self.name,
                "promocode_code": self.promocode_code,
                "promocode_type": self.reward_type,  # used by promocode-type term + reward branch
                "reward": self.reward if self.reward is not None else 0,
                "plan_name": self.plan_name or "—",
            },
            disable_default_markup=False,
            delete_after=None,
        )
