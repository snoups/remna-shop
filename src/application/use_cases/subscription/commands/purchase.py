from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from loguru import logger

from src.application.common import EventPublisher, Interactor, Remnawave
from src.application.common.dao import SubscriptionDao, UserDao
from src.application.common.uow import UnitOfWork
from src.application.dto import PlanSnapshotDto, SubscriptionDto, TransactionDto, UserDto
from src.application.events import TrialActivatedEvent
from src.core.enums import PurchaseType, SubscriptionStatus
from src.core.exceptions import TrialNotAvailableError
from src.core.types import RemnaUserDto
from src.core.utils.converters import days_to_datetime
from src.core.utils.i18n_helpers import (
    i18n_format_days,
    i18n_format_device_limit,
    i18n_format_traffic_limit,
)
from src.core.utils.time import datetime_now


@dataclass(frozen=True)
class ActivateTrialSubscriptionDto:
    user: UserDto
    plan: PlanSnapshotDto


class ActivateTrialSubscription(Interactor[ActivateTrialSubscriptionDto, None]):
    required_permission = None

    def __init__(
        self,
        uow: UnitOfWork,
        user_dao: UserDao,
        subscription_dao: SubscriptionDao,
        remnawave: Remnawave,
        event_publisher: EventPublisher,
    ) -> None:
        self.uow = uow
        self.user_dao = user_dao
        self.subscription_dao = subscription_dao
        self.remnawave = remnawave
        self.event_publisher = event_publisher

    async def _execute(self, actor: UserDto, data: ActivateTrialSubscriptionDto) -> None:
        user = data.user
        plan = data.plan

        if not user.is_trial_available:
            raise TrialNotAvailableError(f"Trial not available for user '{user.remna_name}'")

        logger.info(f"{actor.log} Started trial for user '{user.id}'")

        async with self.uow:
            # Atomically claim the trial: on a double-click only one execution flips the flag,
            # the loser gets claimed=False and aborts before creating a panel user or a duplicate
            # subscription. Rolls back (restoring the flag) if remnawave creation fails.
            claimed = await self.user_dao.claim_trial(user.id)
            if not claimed:
                raise TrialNotAvailableError(
                    f"Trial already activated for user '{user.remna_name}'"
                )

            created_user = await self.remnawave.create_user(user, plan=plan)

            trial_subscription = SubscriptionDto(
                user_remna_id=created_user.id,
                status=SubscriptionStatus(created_user.status),
                is_trial=True,
                traffic_limit=plan.traffic_limit,
                device_limit=plan.device_limit,
                traffic_limit_strategy=plan.traffic_limit_strategy,
                tag=plan.tag,
                internal_squads=plan.internal_squads,
                external_squad=plan.external_squad,
                expire_at=created_user.expire_at,
                url=created_user.subscription_url,
                plan_snapshot=plan,
            )

            await self.subscription_dao.create(
                subscription=trial_subscription,
                user_id=user.id,
            )
            await self.uow.commit()

        logger.debug(f"{actor.log} Created new trial subscription for user '{user.id}'")

        event = TrialActivatedEvent(
            telegram_id=user.telegram_id,
            username=user.username,
            name=user.name,
            email=user.email,
            plan_name=(plan.name, {}),
            plan_type=plan.type,
            plan_traffic_limit=i18n_format_traffic_limit(plan.traffic_limit),
            plan_device_limit=i18n_format_device_limit(plan.device_limit),
            plan_duration=i18n_format_days(plan.duration),
        )
        await self.event_publisher.publish(event)
        logger.info(
            f"{actor.log} Trial subscription completed successfully for user '{user.remna_name}'"
        )


@dataclass(frozen=True)
class PurchaseSubscriptionDto:
    user: UserDto
    transaction: TransactionDto
    subscription: Optional[SubscriptionDto]


class PurchaseSubscription(Interactor[PurchaseSubscriptionDto, None]):
    required_permission = None

    def __init__(
        self,
        uow: UnitOfWork,
        user_dao: UserDao,
        subscription_dao: SubscriptionDao,
        remnawave: Remnawave,
    ) -> None:
        self.uow = uow
        self.user_dao = user_dao
        self.subscription_dao = subscription_dao
        self.remnawave = remnawave

    async def _execute(self, actor: UserDto, data: PurchaseSubscriptionDto) -> None:  # noqa: C901
        user = data.user
        transaction = data.transaction
        subscription = data.subscription
        plan = transaction.plan_snapshot
        purchase_type = transaction.purchase_type
        has_trial = subscription.is_trial if subscription else False

        if not user or not plan:
            raise ValueError(f"User or plan not found for transaction '{transaction.id}'")

        logger.info(
            f"{actor.log} Purchase subscription started: '{purchase_type}' "
            f"for user '{user.remna_name}'"
        )

        async with self.uow:
            # 1. NEW PURCHASE (NOT TRIAL)
            if purchase_type == PurchaseType.NEW and not has_trial:
                created_user = await self.remnawave.create_user(user, plan=plan)
                new_sub = self._build_subscription_dto(created_user, plan)

                await self.subscription_dao.create(
                    subscription=new_sub,
                    user_id=user.id,
                )
                await self.user_dao.set_trial_available(user.id, False)
                if user.purchase_discount:
                    user.purchase_discount = 0
                    await self.user_dao.update(user)
                await self.uow.commit()

                logger.debug(f"{actor.log} Created new subscription for user '{user.id}'")

            # 2. RENEW (NOT TRIAL)
            elif purchase_type == PurchaseType.RENEW and not has_trial:
                if not subscription:
                    raise ValueError(
                        f"No subscription found for renewal for user '{user.remna_name}'"
                    )

                duration = transaction.plan_snapshot.duration

                if duration == 0:
                    new_expire = days_to_datetime(duration)  # unlimited
                else:
                    base_date = (
                        datetime_now()
                        if subscription.grace_until is not None
                        else max(subscription.expire_at, datetime_now())
                    )
                    new_expire = base_date + timedelta(days=duration)

                subscription.expire_at = new_expire
                subscription.device_limit = plan.device_limit
                subscription.traffic_limit = plan.traffic_limit
                subscription.traffic_limit_strategy = plan.traffic_limit_strategy
                subscription.tag = plan.tag
                subscription.internal_squads = plan.internal_squads
                subscription.external_squad = plan.external_squad
                subscription.grace_until = None
                # A paid renewal always restores access. Ending a grace period disables the
                # panel user, and that DISABLED status is synced back onto the subscription —
                # without this, _build_update_request would keep sending DISABLED and the
                # customer would pay for nothing.
                subscription.status = SubscriptionStatus.ACTIVE

                await self.remnawave.update_user(
                    user=user,
                    user_id=subscription.user_remna_id,
                    subscription=subscription,
                    reset_traffic=True,
                )

                subscription.plan_snapshot = plan
                await self.subscription_dao.update(subscription)
                if user.purchase_discount:
                    user.purchase_discount = 0
                    await self.user_dao.update(user)
                await self.uow.commit()
                logger.debug(f"{actor.log} Renewed subscription for user '{user.id}'")

            # 3. CHANGE OR CONVERT FROM TRIAL
            elif purchase_type == PurchaseType.CHANGE or has_trial:
                if not subscription:
                    raise ValueError(
                        f"No subscription found for change for user '{user.remna_name}'"
                    )

                await self.subscription_dao.update_status(
                    subscription_id=subscription.id,
                    status=SubscriptionStatus.DELETED,
                )

                updated_user = await self.remnawave.update_user(
                    user=user,
                    user_id=subscription.user_remna_id,
                    plan=plan,
                    reset_traffic=True,
                )

                new_sub = self._build_subscription_dto(updated_user, plan)
                await self.subscription_dao.create(
                    subscription=new_sub,
                    user_id=user.id,
                )

                if user.purchase_discount:
                    user.purchase_discount = 0
                    await self.user_dao.update(user)
                await self.uow.commit()
                logger.debug(f"{actor.log} Changed subscription for user '{user.id}'")

            else:
                raise ValueError(
                    f"Unknown purchase type '{purchase_type}' for user '{user.remna_name}'"
                )

        logger.info(f"{actor.log} Purchase subscription completed for user '{user.id}'")

    def _build_subscription_dto(
        self,
        remna_user: RemnaUserDto,
        plan: PlanSnapshotDto,
    ) -> SubscriptionDto:
        return SubscriptionDto(
            user_remna_id=remna_user.id,
            status=SubscriptionStatus(remna_user.status),
            is_trial=plan.is_trial,
            traffic_limit=plan.traffic_limit,
            device_limit=plan.device_limit,
            traffic_limit_strategy=plan.traffic_limit_strategy,
            tag=plan.tag,
            internal_squads=plan.internal_squads,
            external_squad=plan.external_squad,
            expire_at=remna_user.expire_at,
            url=remna_user.subscription_url,
            plan_snapshot=plan,
        )
