from datetime import timedelta
from enum import StrEnum
from typing import Optional

from loguru import logger
from redis.asyncio import Redis
from remnapy.models.webhook import HwidUserDeviceDto, TorrentBlockerReportDto, WebhookNodeDto

from src.application.common import BotService, EventPublisher
from src.application.common.dao import SubscriptionDao, UserDao
from src.application.common.uow import UnitOfWork
from src.application.dto import SubscriptionDto, UserDto
from src.application.events import (
    NodeConnectionLostEvent,
    NodeConnectionRestoredEvent,
    NodeTrafficReachedEvent,
    SubscriptionExpiresEvent,
    SubscriptionLimitedEvent,
    TorrentBlockedEvent,
    UserDeviceAddedEvent,
    UserDeviceDeletedEvent,
    UserFirstConnectionEvent,
    UserNotConnectedEvent,
)
from src.application.events.system import SubscriptionRevokedEvent, TorrentBlockerReportEvent
from src.application.events.user import SubscriptionExpiredAgoEvent
from src.application.use_cases.remnawave.commands.synchronization import (
    SyncRemnaUser,
    SyncRemnaUserDto,
)
from src.application.use_cases.subscription.commands.grace import (
    EnterGraceMode,
    EnterGraceModeDto,
)
from src.core.config import AppConfig
from src.core.constants import DATETIME_VIEW_FORMAT, IMPORTED_TAG, T_ME, TIME_1H
from src.core.enums import SubscriptionStatus
from src.core.types import RemnaUserDto
from src.core.utils.converters import country_code_to_flag
from src.core.utils.i18n_helpers import (
    i18n_format_bytes_to_unit,
    i18n_format_device_limit,
    i18n_format_expire_time,
    i18n_format_seconds,
)
from src.core.utils.i18n_keys import ByteUnitKey
from src.core.utils.time import datetime_now, get_traffic_reset_delta


class RemnaWebhookService:
    def __init__(
        self,
        config: AppConfig,
        uow: UnitOfWork,
        user_dao: UserDao,
        subscription_dao: SubscriptionDao,
        event_bus: EventPublisher,
        redis: Redis,
        bot_service: BotService,
        #
        sync_user: SyncRemnaUser,
        enter_grace_mode: EnterGraceMode,
    ) -> None:
        self.config = config
        self.uow = uow
        self.user_dao = user_dao
        self.subscription_dao = subscription_dao
        self.event_bus = event_bus
        self.redis = redis
        self.bot_service = bot_service
        #
        self.sync_user = sync_user
        self.enter_grace_mode = enter_grace_mode

    async def handle_user_event(
        self,
        event: str,
        remna_user: RemnaUserDto,
        expiration_hours: Optional[int] = None,
    ) -> None:
        logger.debug(f"Received user event '{event}'")

        if event == RemnaUserEvent.NOT_CONNECTED:
            await self._process_not_connected(remna_user)
            return

        if event in {RemnaUserEvent.CREATED, RemnaUserEvent.MODIFIED}:
            await self._process_sync(event, remna_user)
            return

        user = await self.user_dao.get_by_remna_id(remna_user.id)
        if not user:
            logger.warning(f"Local user not found for remna_id '{remna_user.id}'")
            return

        current_subscription = await self.subscription_dao.get_current(user.id)
        if not current_subscription:
            logger.warning(
                f"Current subscription not found for '{user.remna_name}', "
                f"status event '{event}' processing aborted"
            )
            return

        if event == RemnaUserEvent.DELETED:
            logger.debug(f"Executing deletion for RemnaUser '{remna_user.telegram_id}'")
            await self._process_delete_subscription(remna_user)

        elif event in {
            RemnaUserEvent.REVOKED,
            RemnaUserEvent.ENABLED,
            RemnaUserEvent.DISABLED,
            RemnaUserEvent.LIMITED,
            RemnaUserEvent.EXPIRED,
        }:
            await self._process_status(user, current_subscription, event, remna_user)

        elif event == RemnaUserEvent.EXPIRATION:
            await self._process_expiration(user, current_subscription, remna_user, expiration_hours)

        elif event == RemnaUserEvent.FIRST_CONNECTED:
            await self.event_bus.publish(
                UserFirstConnectionEvent(
                    user_id=user.id,
                    telegram_id=user.telegram_id,
                    username=user.username,
                    name=user.name,
                    email=user.email,
                    is_trial=current_subscription.is_trial,
                    subscription_id=remna_user.id,
                    subscription_status=SubscriptionStatus(remna_user.status),
                    traffic_used=i18n_format_bytes_to_unit(
                        remna_user.used_traffic_bytes, min_unit=ByteUnitKey.MEGABYTE
                    ),
                    traffic_limit=i18n_format_bytes_to_unit(remna_user.traffic_limit_bytes or None),
                    device_limit=i18n_format_device_limit(remna_user.hwid_device_limit),
                    expire_time=i18n_format_expire_time(remna_user.expire_at),
                )
            )
        else:
            logger.warning(f"Unhandled user event '{event}' for '{remna_user.telegram_id}'")

    async def handle_device_event(
        self, event: str, remna_user: RemnaUserDto, device: HwidUserDeviceDto
    ) -> None:
        logger.info(f"Received device event '{event}' for RemnaUser '{remna_user.id}'")

        user = await self.user_dao.get_by_remna_id(remna_user.id)
        if not user:
            logger.warning(f"Local user not found for remna_id '{remna_user.id}'")
            return

        if event == RemnaUserHwidDevicesEvent.ADDED:
            await self.event_bus.publish(
                UserDeviceAddedEvent(
                    user_id=user.id,
                    telegram_id=user.telegram_id,
                    username=user.username,
                    name=user.name,
                    email=user.email,
                    hwid=device.hwid,
                    platform=device.platform,
                    device_model=device.device_model,
                    os_version=device.os_version,
                    user_agent=device.user_agent,
                )
            )
        elif event == RemnaUserHwidDevicesEvent.DELETED:
            await self.event_bus.publish(
                UserDeviceDeletedEvent(
                    user_id=user.id,
                    telegram_id=user.telegram_id,
                    username=user.username,
                    name=user.name,
                    email=user.email,
                    hwid=device.hwid,
                    platform=device.platform,
                    device_model=device.device_model,
                    os_version=device.os_version,
                    user_agent=device.user_agent,
                )
            )

    async def handle_node_event(self, event: str, node: WebhookNodeDto) -> None:
        logger.info(f"Received node event '{event}' for node '{node.name}'")

        if event not in {
            RemnaNodeEvent.CONNECTION_LOST,
            RemnaNodeEvent.CONNECTION_RESTORED,
            RemnaNodeEvent.TRAFFIC_NOTIFY,
        }:
            logger.warning(f"Unhandled node event '{event}' for node '{node.name}'")
            return

        if event == RemnaNodeEvent.CONNECTION_LOST:
            await self.event_bus.publish(
                NodeConnectionLostEvent(
                    country=country_code_to_flag(code=node.country_code),
                    name=node.name,
                    address=node.address,
                    port=node.port,
                    traffic_used=i18n_format_bytes_to_unit(node.traffic_used_bytes),
                    traffic_limit=i18n_format_bytes_to_unit(node.traffic_limit_bytes or None),
                    last_status_message=node.last_status_message,
                    last_status_change=node.last_status_change.strftime(DATETIME_VIEW_FORMAT)
                    if node.last_status_change
                    else None,
                )
            )
        elif event == RemnaNodeEvent.CONNECTION_RESTORED:
            await self.event_bus.publish(
                NodeConnectionRestoredEvent(
                    country=country_code_to_flag(code=node.country_code),
                    name=node.name,
                    address=node.address,
                    port=node.port,
                    traffic_used=i18n_format_bytes_to_unit(node.traffic_used_bytes),
                    traffic_limit=i18n_format_bytes_to_unit(node.traffic_limit_bytes or None),
                    last_status_message=node.last_status_message,
                    last_status_change=node.last_status_change.strftime(DATETIME_VIEW_FORMAT)
                    if node.last_status_change
                    else None,
                )
            )
        elif event == RemnaNodeEvent.TRAFFIC_NOTIFY:
            await self.event_bus.publish(
                NodeTrafficReachedEvent(
                    country=country_code_to_flag(code=node.country_code),
                    name=node.name,
                    address=node.address,
                    port=node.port,
                    traffic_used=i18n_format_bytes_to_unit(node.traffic_used_bytes),
                    traffic_limit=i18n_format_bytes_to_unit(node.traffic_limit_bytes or None),
                    last_status_message=node.last_status_message,
                    last_status_change=node.last_status_change.strftime(DATETIME_VIEW_FORMAT)
                    if node.last_status_change
                    else None,
                )
            )

    async def _process_expiration(
        self,
        user: UserDto,
        current_subscription: SubscriptionDto,
        remna_user: RemnaUserDto,
        expiration_hours: Optional[int],
    ) -> None:
        if expiration_hours is None:
            logger.warning(
                f"Skipping expiration for '{remna_user.telegram_id}': missing meta.expiration"
            )
            return
        if (
            remna_user.expire_at
            and current_subscription.expire_at
            and (current_subscription.expire_at - remna_user.expire_at).total_seconds() > 3600
        ):
            logger.debug(
                f"Skipping expiration ({expiration_hours}h) for '{remna_user.telegram_id}': "
                f"subscription renewed (local={current_subscription.expire_at}, "
                f"webhook={remna_user.expire_at})"
            )
            return
        day = max(1, round(abs(expiration_hours) / 24))
        if expiration_hours < 0:
            await self.event_bus.publish(
                SubscriptionExpiresEvent(
                    day=day,
                    user=user,
                    is_trial=current_subscription.is_trial,
                )
            )
        else:
            await self.event_bus.publish(
                SubscriptionExpiredAgoEvent(
                    day=day,
                    user=user,
                    is_trial=current_subscription.is_trial,
                )
            )

    async def _process_not_connected(self, remna_user: RemnaUserDto) -> None:
        user = await self.user_dao.get_by_remna_id(remna_user.id)
        if not user:
            logger.warning(f"Local user not found for remna_id '{remna_user.id}'")
            return
        support_url = f"{T_ME}{self.config.bot.support_username.get_secret_value()}"
        await self.event_bus.publish(UserNotConnectedEvent(user=user, support_url=support_url))

    async def handle_torrent_blocker_event(self, report: TorrentBlockerReportDto) -> None:
        logger.info("Received torrent blocker webhook event")

        action_report = report.report.action_report
        xray_report = report.report.xray_report

        if not action_report.blocked:
            logger.debug("Torrent blocker report did not result in a block, skipping")
            return

        remna_user = report.user
        telegram_id = remna_user.telegram_id
        user_identifier = (
            str(telegram_id) if telegram_id else (action_report.user_id or str(remna_user.id))
        )
        node_name = report.node.name
        blocked_ip = action_report.ip
        block_duration_seconds = int(action_report.block_duration) or TIME_1H

        dedupe_key = self._build_torrent_blocker_key(
            user_identifier=user_identifier,
            node_name=node_name,
            blocked_ip=blocked_ip,
        )
        if await self.redis.exists(dedupe_key):
            logger.debug(f"Torrent blocker notification already processed for key '{dedupe_key}'")
            return

        await self.redis.set(dedupe_key, value="1", ex=block_duration_seconds)

        user = await self.user_dao.get_by_telegram_id(telegram_id) if telegram_id else None

        username = user.username if user else remna_user.username
        name = user.name if user else (username or f"ID {user_identifier}")
        block_duration = i18n_format_seconds(block_duration_seconds)
        will_unblock_at = action_report.will_unblock_at.strftime(DATETIME_VIEW_FORMAT)
        protocol = xray_report.protocol or "unknown"
        source = xray_report.source or "unknown"
        destination = xray_report.destination or "unknown"

        await self.event_bus.publish(
            TorrentBlockerReportEvent(
                user_id=user.id if user else 0,
                telegram_id=telegram_id or 0,
                username=username,
                name=name,
                node_name=node_name,
                blocked_ip=blocked_ip,
                block_duration=block_duration,
                will_unblock_at=will_unblock_at,
                protocol=protocol,
                source=source,
                destination=destination,
            )
        )

        if not user:
            logger.warning(
                f"Local user not found for torrent blocker notification '{user_identifier}'"
            )
            return

        await self.event_bus.publish(
            TorrentBlockedEvent(
                user=user,
                node_name=node_name,
                block_duration=block_duration,
                support_url=self.bot_service.get_support_url(),
            )
        )

    async def _process_sync(self, event: str, remna_user: RemnaUserDto) -> None:
        if event == RemnaUserEvent.CREATED and remna_user.tag != IMPORTED_TAG:
            logger.debug(
                f"RemnaUser '{remna_user.telegram_id}' ignored: not tagged as '{IMPORTED_TAG}'"
            )
            return

        logger.debug(f"Executing sync for user '{remna_user.telegram_id}' due to event '{event}'")
        dto = SyncRemnaUserDto(remna_user=remna_user, creating=(event == RemnaUserEvent.CREATED))
        await self.sync_user.system(dto)

    async def _process_delete_subscription(self, remna_user: RemnaUserDto) -> None:
        async with self.uow:
            subscription = await self.subscription_dao.get_by_remna_id(remna_user.id)

            if not subscription:
                logger.warning(
                    f"Subscription not found for ID '{remna_user.id}', delete aborted"
                )
                return

            user_id = subscription.user_id
            subscription.status = SubscriptionStatus.DELETED
            await self.subscription_dao.update(subscription)

            current_subscription = await self.subscription_dao.get_current(user_id)

            if current_subscription:
                if current_subscription.user_remna_id != subscription.user_remna_id:
                    logger.debug(
                        f"Subscription '{subscription.user_remna_id}' "
                        f"is not current for user_id '{user_id}', skipping unlinking"
                    )
                else:
                    logger.debug(f"Unlinked current subscription for user_id '{user_id}'")
                    await self.user_dao.clear_current_subscription(user_id)

            await self.uow.commit()
            logger.info(f"Successfully processed deletion for subscription '{remna_user.id}'")

    async def _process_status(
        self,
        user: UserDto,
        current_subscription: SubscriptionDto,
        event: str,
        remna_user: RemnaUserDto,
    ) -> None:
        await self.sync_user.system(SyncRemnaUserDto(remna_user=remna_user, creating=False))

        if event == RemnaUserEvent.LIMITED:
            await self.event_bus.publish(
                SubscriptionLimitedEvent(
                    user=user,
                    is_trial=current_subscription.is_trial,
                    traffic_strategy=current_subscription.traffic_limit_strategy,
                    reset_time=i18n_format_expire_time(
                        get_traffic_reset_delta(
                            current_subscription.traffic_limit_strategy,
                            current_subscription.created_at,
                        )
                    ),
                )
            )
        elif event == RemnaUserEvent.EXPIRED:
            if remna_user.expire_at is None:
                logger.debug(
                    f"Skipping EXPIRED for '{remna_user.telegram_id}': unlimited (no expire_at)"
                )
                return
            if remna_user.expire_at + timedelta(days=3) < datetime_now():
                logger.debug(
                    f"Skipping expiration notification for '{remna_user.telegram_id}': "
                    f"more than 3 days passed"
                )
                return
            await self.enter_grace_mode.system(
                EnterGraceModeDto(user=user, subscription=current_subscription)
            )

        if event == RemnaUserEvent.REVOKED:
            await self.event_bus.publish(
                SubscriptionRevokedEvent(
                    user_id=user.id,
                    telegram_id=user.telegram_id,
                    username=user.username,
                    name=user.name,
                    email=user.email,
                    is_trial=current_subscription.is_trial,
                    subscription_id=remna_user.id,
                    subscription_status=SubscriptionStatus(remna_user.status),
                    traffic_used=i18n_format_bytes_to_unit(
                        remna_user.used_traffic_bytes, min_unit=ByteUnitKey.MEGABYTE
                    ),
                    traffic_limit=i18n_format_bytes_to_unit(remna_user.traffic_limit_bytes or None),
                    device_limit=i18n_format_device_limit(remna_user.hwid_device_limit),
                    expire_time=i18n_format_expire_time(remna_user.expire_at),
                )
            )

    @staticmethod
    def _build_torrent_blocker_key(
        user_identifier: str,
        node_name: str,
        blocked_ip: str,
    ) -> str:
        return f"torrent_blocker_lock:{user_identifier}:{node_name}:{blocked_ip}"


class RemnaUserEvent(StrEnum):
    CREATED = "user.created"
    MODIFIED = "user.modified"
    DELETED = "user.deleted"
    REVOKED = "user.revoked"
    DISABLED = "user.disabled"
    ENABLED = "user.enabled"
    LIMITED = "user.limited"
    EXPIRED = "user.expired"

    TRAFFIC_RESET = "user.traffic_reset"
    NOT_CONNECTED = "user.not_connected"
    FIRST_CONNECTED = "user.first_connected"
    BANDWIDTH_USAGE_THRESHOLD_REACHED = "user.bandwidth_usage_threshold_reached"

    EXPIRATION = "user.expiration"


class RemnaUserHwidDevicesEvent(StrEnum):
    ADDED = "user_hwid_devices.added"
    DELETED = "user_hwid_devices.deleted"


class RemnaNodeEvent(StrEnum):
    CREATED = "node.created"
    MODIFIED = "node.modified"
    DISABLED = "node.disabled"
    ENABLED = "node.enabled"
    DELETED = "node.deleted"
    CONNECTION_LOST = "node.connection_lost"
    CONNECTION_RESTORED = "node.connection_restored"
    TRAFFIC_NOTIFY = "node.traffic_notify"


class RemnaTorrentBlockerEvent(StrEnum):
    REPORT = "torrent_blocker.report"


class RemnaServiceEvent(StrEnum):
    PANEL_STARTED = "service.panel_started"
    LOGIN_ATTEMPT_FAILED = "service.login_attempt_failed"
    LOGIN_ATTEMPT_SUCCESS = "service.login_attempt_success"


class RemnaCrmEvent(StrEnum):
    INFRA_BILLING_NODE_PAYMENT_IN_7_DAYS = "crm.infra_billing_node_payment_in_7_days"
    INFRA_BILLING_NODE_PAYMENT_IN_48HRS = "crm.infra_billing_node_payment_in_48hrs"
    INFRA_BILLING_NODE_PAYMENT_IN_24HRS = "crm.infra_billing_node_payment_in_24hrs"
    INFRA_BILLING_NODE_PAYMENT_DUE_TODAY = "crm.infra_billing_node_payment_due_today"
    INFRA_BILLING_NODE_PAYMENT_OVERDUE_24HRS = "crm.infra_billing_node_payment_overdue_24hrs"
    INFRA_BILLING_NODE_PAYMENT_OVERDUE_48HRS = "crm.infra_billing_node_payment_overdue_48hrs"
    INFRA_BILLING_NODE_PAYMENT_OVERDUE_7_DAYS = "crm.infra_billing_node_payment_overdue_7_days"
