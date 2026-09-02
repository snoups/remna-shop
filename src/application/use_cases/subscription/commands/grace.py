from dataclasses import dataclass
from datetime import datetime, timedelta

from loguru import logger

from src.application.common import (
    EventPublisher,
    Interactor,
    Remnawave,
    SubscriptionMutationLock,
)
from src.application.common.dao import SettingsDao, SubscriptionDao
from src.application.common.uow import UnitOfWork
from src.application.dto import GraceSettingsDto, SubscriptionDto, UserDto
from src.application.events import GraceActivatedEvent, SubscriptionExpiredEvent
from src.core.utils.converters import days_to_datetime
from src.core.utils.i18n_helpers import i18n_format_expire_time
from src.core.utils.time import datetime_now

_MB = 1024**2


@dataclass(frozen=True)
class EnterGraceModeDto:
    user: UserDto
    subscription: SubscriptionDto


class EnterGraceMode(Interactor[EnterGraceModeDto, None]):
    required_permission = None

    def __init__(
        self,
        uow: UnitOfWork,
        settings_dao: SettingsDao,
        subscription_dao: SubscriptionDao,
        remnawave: Remnawave,
        event_publisher: EventPublisher,
        subscription_mutation_lock: SubscriptionMutationLock,
    ) -> None:
        self.uow = uow
        self.settings_dao = settings_dao
        self.subscription_dao = subscription_dao
        self.remnawave = remnawave
        self.event_publisher = event_publisher
        self.subscription_mutation_lock = subscription_mutation_lock

    async def _execute(self, actor: UserDto, data: EnterGraceModeDto) -> None:
        async with self.subscription_mutation_lock.hold(data.user.id):
            await self._execute_locked(actor, data)

    async def _execute_locked(self, actor: UserDto, data: EnterGraceModeDto) -> None:
        user = data.user
        sub = await self.subscription_dao.get_current(user.id)
        if sub is None:
            logger.info(f"{actor.log} Subscription disappeared before grace mutation")
            return
        grace = (await self.settings_dao.get()).grace

        if sub.grace_until is not None:
            # The grace period itself ran out. Always end it — even if grace was switched
            # off meanwhile, otherwise grace_until would stay set on the subscription forever.
            await self._end_grace(actor, sub)

        elif grace.enabled and not sub.is_trial:
            grace_until = await self._start_grace(actor, sub, grace)
            await self.event_publisher.publish(
                GraceActivatedEvent(
                    user=user,
                    is_trial=sub.is_trial,
                    traffic_mb=grace.traffic_mb,
                    is_indefinite=grace.is_indefinite,
                    grace_until=i18n_format_expire_time(grace_until),
                )
            )
            return

        await self.event_publisher.publish(
            SubscriptionExpiredEvent(user=user, is_trial=sub.is_trial)
        )

    async def _start_grace(
        self, actor: UserDto, sub: SubscriptionDto, grace: GraceSettingsDto
    ) -> datetime:
        grace_until = (
            days_to_datetime(0)
            if grace.is_indefinite
            else datetime_now() + timedelta(days=grace.duration_days)
        )
        # Squads default to the expired subscription's own; grace settings
        # act as an optional override (non-empty list / explicit UUID wins).
        internal_squads = grace.internal_squads or sub.internal_squads
        external_squad = (
            grace.external_squad if grace.external_squad is not None else sub.external_squad
        )

        async with self.uow:
            await self.remnawave.apply_grace(
                uuid=sub.user_remna_id,
                expire_at=grace_until,
                internal_squads=internal_squads,
                external_squad=external_squad,
                traffic_bytes=grace.traffic_mb * _MB,
                traffic_strategy=grace.traffic_strategy,
                tag=grace.tag,
                device_limit=sub.device_limit,
            )
            sub.grace_until = grace_until
            await self.subscription_dao.update(sub)
            await self.uow.commit()

        logger.info(f"{actor.log} Activated grace for '{sub.user_remna_id}' until '{grace_until}'")
        return grace_until

    async def _end_grace(self, actor: UserDto, sub: SubscriptionDto) -> None:
        async with self.uow:
            await self.remnawave.disable_user(sub.user_remna_id)
            sub.grace_until = None
            await self.subscription_dao.update(sub)
            await self.uow.commit()

        logger.info(f"{actor.log} Ended grace for '{sub.user_remna_id}'")
