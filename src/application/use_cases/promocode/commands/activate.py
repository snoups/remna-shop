from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from adaptix import Retort
from loguru import logger

from src.application.common import EventPublisher, Interactor
from src.application.common.dao import PromocodeDao, SubscriptionDao, UserDao
from src.application.common.policy import Permission
from src.application.common.remnawave import Remnawave
from src.application.common.uow import UnitOfWork
from src.application.dto import PlanSnapshotDto, PromocodeDto, SubscriptionDto, UserDto
from src.application.dto.promocode import PromocodeActivationDto
from src.application.events.system import PromocodeActivatedEvent
from src.application.use_cases.promocode.queries.validate import (
    ValidatePromocode,
    ValidatePromocodeDto,
)
from src.core.enums import PromocodeRewardType, SubscriptionStatus
from src.core.utils.converters import days_to_datetime
from src.core.utils.time import datetime_now


@dataclass(frozen=True)
class ActivatePromocodeDto:
    code: str
    user: UserDto


@dataclass(frozen=True)
class _PendingReward:
    subscription_update: Optional[SubscriptionDto] = None
    subscription_create: Optional[SubscriptionDto] = None
    user_update: Optional[UserDto] = None


class ActivatePromocode(Interactor[ActivatePromocodeDto, PromocodeDto]):
    required_permission = Permission.PUBLIC

    def __init__(
        self,
        uow: UnitOfWork,
        promocode_dao: PromocodeDao,
        user_dao: UserDao,
        subscription_dao: SubscriptionDao,
        remnawave: Remnawave,
        validate_promocode: ValidatePromocode,
        event_publisher: EventPublisher,
        retort: Retort,
    ) -> None:
        self.uow = uow
        self.promocode_dao = promocode_dao
        self.user_dao = user_dao
        self.subscription_dao = subscription_dao
        self.remnawave = remnawave
        self.validate_promocode = validate_promocode
        self.event_publisher = event_publisher
        self.retort = retort

    async def _execute(self, actor: UserDto, data: ActivatePromocodeDto) -> PromocodeDto:
        user = data.user

        promo = await self.validate_promocode(
            actor, ValidatePromocodeDto(code=data.code, user=user)
        )

        subscription = await self.subscription_dao.get_current(user.id)

        # Remnawave calls happen OUTSIDE the transaction: if any raises, the
        # exception propagates and nothing is persisted (promocode not consumed).
        pending = await self._apply_reward_remote(actor, user, promo, subscription)

        async with self.uow:
            assert promo.id is not None
            activation = PromocodeActivationDto(
                promocode_id=promo.id,
                user_id=user.id,
                activated_at=datetime_now(),
            )
            await self.promocode_dao.create_activation(
                activation,
                max_activations=promo.max_activations,
                is_reusable=promo.is_reusable,
            )

            await self._persist_reward(user, pending)
            await self.uow.commit()

        logger.info(f"{actor.log} Activated promocode '{promo.code}'")

        event = PromocodeActivatedEvent(
            user_id=user.id,
            telegram_id=user.telegram_id,
            username=user.username,
            name=user.name,
            promocode_code=promo.code,
            reward_type=promo.reward_type.value,
            reward=promo.reward,
            plan_name=(str(promo.plan_snapshot.get("name")), {})
            if promo.plan_snapshot and promo.plan_snapshot.get("name")
            else "",
        )
        await self.event_publisher.publish(event)

        return promo

    async def _apply_reward_remote(
        self,
        actor: UserDto,
        user: UserDto,
        promo: PromocodeDto,
        subscription: Optional[SubscriptionDto],
    ) -> _PendingReward:
        match promo.reward_type:
            case PromocodeRewardType.DURATION:
                return await self._apply_duration(actor, user, promo, subscription)
            case PromocodeRewardType.TRAFFIC:
                return await self._apply_traffic(actor, user, promo, subscription)
            case PromocodeRewardType.DEVICES:
                return await self._apply_devices(actor, user, promo, subscription)
            case PromocodeRewardType.SUBSCRIPTION:
                return await self._apply_subscription(actor, user, promo, subscription)
            case PromocodeRewardType.PERSONAL_DISCOUNT:
                return self._apply_personal_discount(actor, user, promo)
            case PromocodeRewardType.PURCHASE_DISCOUNT:
                return self._apply_purchase_discount(actor, user, promo)

    async def _persist_reward(self, user: UserDto, pending: _PendingReward) -> None:
        if pending.subscription_update is not None:
            await self.subscription_dao.update(pending.subscription_update)
        if pending.subscription_create is not None:
            try:
                await self.subscription_dao.create(
                    subscription=pending.subscription_create, user_id=user.id
                )
            except Exception:
                # Remote user was already created in the remote phase; a failure
                # here leaves a remote orphan (inherent dual-write without 2PC).
                logger.error(
                    f"Failed to persist new subscription after Remnawave create_user "
                    f"(remote uuid={pending.subscription_create.user_remna_id}); "
                    f"possible remote orphan"
                )
                raise
        if pending.user_update is not None:
            await self.user_dao.update(pending.user_update)

    async def _apply_duration(
        self,
        actor: UserDto,
        user: UserDto,
        promo: PromocodeDto,
        subscription: Optional[SubscriptionDto],
    ) -> _PendingReward:
        if not subscription or promo.reward is None:
            return _PendingReward()
        if promo.reward == 0:
            # 0 days means a permanent (unlimited) subscription.
            subscription.expire_at = days_to_datetime(0)
            log_detail = "unlimited"
        else:
            subscription.expire_at = subscription.expire_at + timedelta(days=promo.reward)
            log_detail = f"+{promo.reward} days"
        await self.remnawave.update_user(
            user=user,
            user_id=subscription.user_remna_id,
            subscription=subscription,
        )
        logger.info(f"{actor.log} DURATION reward: {log_detail} applied")
        return _PendingReward(subscription_update=subscription)

    async def _apply_traffic(
        self,
        actor: UserDto,
        user: UserDto,
        promo: PromocodeDto,
        subscription: Optional[SubscriptionDto],
    ) -> _PendingReward:
        if not subscription or promo.reward is None:
            return _PendingReward()
        if promo.reward == 0:
            # 0 GB means an unlimited traffic limit.
            subscription.traffic_limit = 0
            log_detail = "unlimited"
        else:
            subscription.traffic_limit = subscription.traffic_limit + promo.reward
            log_detail = f"+{promo.reward} GB"
        await self.remnawave.update_user(
            user=user,
            user_id=subscription.user_remna_id,
            subscription=subscription,
        )
        logger.info(f"{actor.log} TRAFFIC reward: {log_detail} applied")
        return _PendingReward(subscription_update=subscription)

    async def _apply_devices(
        self,
        actor: UserDto,
        user: UserDto,
        promo: PromocodeDto,
        subscription: Optional[SubscriptionDto],
    ) -> _PendingReward:
        if not subscription or promo.reward is None:
            return _PendingReward()
        if promo.reward == 0:
            # 0 devices means an unlimited device limit.
            subscription.device_limit = 0
            log_detail = "unlimited"
        else:
            subscription.device_limit = subscription.device_limit + promo.reward
            log_detail = f"+{promo.reward} devices"
        await self.remnawave.update_user(
            user=user,
            user_id=subscription.user_remna_id,
            subscription=subscription,
        )
        logger.info(f"{actor.log} DEVICES reward: {log_detail} applied")
        return _PendingReward(subscription_update=subscription)

    async def _apply_subscription(
        self,
        actor: UserDto,
        user: UserDto,
        promo: PromocodeDto,
        subscription: Optional[SubscriptionDto],
    ) -> _PendingReward:
        if not promo.plan_snapshot:
            return _PendingReward()
        plan = self.retort.load(promo.plan_snapshot, PlanSnapshotDto)
        if subscription:
            updated = await self.remnawave.update_user(
                user=user,
                user_id=subscription.user_remna_id,
                plan=plan,
                reset_traffic=True,
            )
            # Keep the local subscription in sync with the new plan pushed to the
            # panel; otherwise the DB keeps stale limits/expiry and later updates
            # would overwrite the panel with outdated values.
            subscription.status = SubscriptionStatus(updated.status)
            subscription.traffic_limit = plan.traffic_limit
            subscription.device_limit = plan.device_limit
            subscription.traffic_limit_strategy = plan.traffic_limit_strategy
            subscription.tag = plan.tag
            subscription.internal_squads = plan.internal_squads
            subscription.external_squad = plan.external_squad
            subscription.expire_at = updated.expire_at
            subscription.url = updated.subscription_url
            subscription.plan_snapshot = plan
            logger.info(f"{actor.log} SUBSCRIPTION reward applied")
            return _PendingReward(subscription_update=subscription)
        created = await self.remnawave.create_user(user=user, plan=plan)
        new_sub = SubscriptionDto(
            user_remna_id=created.id,
            status=SubscriptionStatus(created.status),
            traffic_limit=plan.traffic_limit,
            device_limit=plan.device_limit,
            traffic_limit_strategy=plan.traffic_limit_strategy,
            tag=plan.tag,
            internal_squads=plan.internal_squads,
            external_squad=plan.external_squad,
            expire_at=created.expire_at,
            url=created.subscription_url,
            plan_snapshot=plan,
        )
        logger.info(f"{actor.log} SUBSCRIPTION reward applied")
        return _PendingReward(subscription_create=new_sub)

    def _apply_personal_discount(
        self,
        actor: UserDto,
        user: UserDto,
        promo: PromocodeDto,
    ) -> _PendingReward:
        if not promo.reward:
            return _PendingReward()
        user.personal_discount = promo.reward
        logger.info(f"{actor.log} PERSONAL_DISCOUNT reward: {promo.reward}% applied")
        return _PendingReward(user_update=user)

    def _apply_purchase_discount(
        self,
        actor: UserDto,
        user: UserDto,
        promo: PromocodeDto,
    ) -> _PendingReward:
        if not promo.reward:
            return _PendingReward()
        user.purchase_discount = promo.reward
        logger.info(f"{actor.log} PURCHASE_DISCOUNT reward: {promo.reward}% applied")
        return _PendingReward(user_update=user)
