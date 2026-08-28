from datetime import timedelta
from typing import Optional, cast
from uuid import UUID

from adaptix import Retort
from adaptix.conversion import ConversionRetort
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import and_, case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.common.dao import SubscriptionDao, UserDao
from src.application.dto import PlanSubStatsDto, SubscriptionDto, SubscriptionStatsDto
from src.core.enums import SubscriptionStatus
from src.core.utils.time import datetime_now
from src.infrastructure.database.models import Subscription, User

from .base import BaseDaoImpl


class SubscriptionDaoImpl(SubscriptionDao, BaseDaoImpl):
    def __init__(
        self,
        session: AsyncSession,
        retort: Retort,
        conversion_retort: ConversionRetort,
        redis: Redis,
        user_dao: UserDao,
    ) -> None:
        self.session = session
        self.retort = retort
        self.conversion_retort = conversion_retort
        self.redis = redis
        self.user_dao = user_dao

        self._convert_to_dto = self.conversion_retort.get_converter(Subscription, SubscriptionDto)
        self._convert_to_dto_list = self.conversion_retort.get_converter(
            list[Subscription], list[SubscriptionDto]
        )

    async def create(self, subscription: SubscriptionDto, user_id: int) -> SubscriptionDto:
        subscription_data = self.retort.dump(subscription)
        subscription_data.pop("id", None)
        subscription_data.pop("user_id", None)
        db_subscription = Subscription(**subscription_data, user_id=user_id)

        self.session.add(db_subscription)
        await self.session.flush()

        await self.user_dao.set_current_subscription_by_id(user_id, db_subscription.id)

        logger.debug(
            f"Created new subscription '{db_subscription.id}' "
            f"for remna user '{subscription.user_remna_id}'"
        )
        return self._convert_to_dto(db_subscription)

    async def get_by_id(self, subscription_id: int) -> Optional[SubscriptionDto]:
        stmt = select(Subscription).where(Subscription.id == subscription_id)
        db_subscription = await self.session.scalar(stmt)

        if db_subscription:
            logger.debug(f"Subscription '{subscription_id}' found")
            return self._convert_to_dto(db_subscription)

        logger.debug(f"Subscription '{subscription_id}' not found")
        return None

    async def get_by_remna_id(self, user_remna_id: int) -> Optional[SubscriptionDto]:
        stmt = select(Subscription).where(Subscription.user_remna_id == user_remna_id)
        db_subscription = await self.session.scalar(stmt)

        if db_subscription:
            logger.debug(f"Subscription found by remna ID '{user_remna_id}'")
            return self._convert_to_dto(db_subscription)

        logger.debug(f"Subscription with remna ID '{user_remna_id}' not found")
        return None

    async def get_all_by_user(self, user_id: int) -> list[SubscriptionDto]:
        stmt = (
            select(Subscription)
            .where(Subscription.user_id == user_id)
            .order_by(Subscription.created_at.desc())
        )
        result = await self.session.scalars(stmt)
        db_subscriptions = cast(list, result.all())

        logger.debug(f"Retrieved '{len(db_subscriptions)}' subscriptions for user_id='{user_id}'")
        return self._convert_to_dto_list(db_subscriptions)

    async def get_current(self, user_id: int) -> Optional[SubscriptionDto]:
        stmt = (
            select(Subscription)
            .join(User, User.current_subscription_id == Subscription.id)
            .where(User.id == user_id)
            .limit(1)
        )
        db_subscription = await self.session.scalar(stmt)

        if db_subscription:
            logger.debug(f"Current active subscription found for user_id '{user_id}'")
            return self._convert_to_dto(db_subscription)

        logger.debug(f"Active subscription not found for user_id '{user_id}'")
        return None

    async def update(self, subscription: SubscriptionDto) -> Optional[SubscriptionDto]:
        if not subscription.id:
            logger.warning("Subscription ID is missing, skipping update")
            return None

        if not subscription.changed_data:
            logger.debug(
                f"No changes detected for subscription '{subscription.id}', skipping update"
            )
            return await self.get_by_id(subscription.id)

        values_to_update = self._serialize_for_update(subscription, SubscriptionDto, Subscription)

        stmt = (
            update(Subscription)
            .where(Subscription.id == subscription.id)
            .values(**values_to_update)
            .returning(Subscription)
        )
        db_subscription = await self.session.scalar(stmt)

        if db_subscription:
            logger.debug(
                f"Subscription '{subscription.id}' updated successfully "
                f"with data '{values_to_update}'"
            )
            return self._convert_to_dto(db_subscription)

        logger.warning(f"Failed to update subscription '{subscription.id}'")
        return None

    async def update_status(
        self,
        subscription_id: int,
        status: SubscriptionStatus,
    ) -> Optional[SubscriptionDto]:
        stmt = (
            update(Subscription)
            .where(Subscription.id == subscription_id)
            .values(status=status)
            .returning(Subscription)
        )
        db_subscription = await self.session.scalar(stmt)

        if db_subscription:
            logger.debug(f"Subscription '{subscription_id}' status updated to '{status}'")
            return self._convert_to_dto(db_subscription)

        logger.warning(f"Failed to update subscription '{subscription_id}': not found")
        return None

    async def exists(self, user_remna_id: int) -> bool:
        stmt = select(
            select(Subscription).where(Subscription.user_remna_id == user_remna_id).exists()
        )
        is_exists = await self.session.scalar(stmt) or False

        logger.debug(
            f"Subscription existence status for remna ID '{user_remna_id}' is '{is_exists}'"
        )
        return is_exists

    async def count_active_by_plan(self, plan_id: int) -> int:
        stmt = (
            select(func.count(Subscription.id))
            .join(User, User.current_subscription_id == Subscription.id)
            .where(
                Subscription.plan_snapshot["id"].as_integer() == plan_id,
                Subscription.status == SubscriptionStatus.ACTIVE,
                User.is_blocked.is_(False),
                User.is_bot_blocked.is_(False),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def get_all_active_internal_squads(self) -> list[UUID]:
        stmt = select(Subscription.plan_snapshot["internal_squads"].as_json()).where(
            Subscription.status == SubscriptionStatus.ACTIVE,
            Subscription.plan_snapshot["internal_squads"].is_not(None),
        )

        result = await self.session.execute(stmt)
        raw_squads_lists = result.scalars().all()

        unique_squads: set[UUID] = set()

        for squad_list in raw_squads_lists:
            if isinstance(squad_list, list):
                for s in squad_list:
                    try:
                        unique_squads.add(UUID(s))
                    except (ValueError, TypeError):
                        continue

        squads = list(unique_squads)

        logger.debug(
            f"Retrieved '{len(squads)}' unique internal squads from all active subscriptions"
        )
        return squads

    async def count_total_trials(self) -> int:
        stmt = select(func.count(func.distinct(Subscription.user_id))).where(
            Subscription.is_trial.is_(True),
        )
        return await self.session.scalar(stmt) or 0

    async def count_converted_from_trial(self) -> int:
        trial_users_subq = (
            select(Subscription.user_id).where(Subscription.is_trial.is_(True)).scalar_subquery()
        )

        stmt = select(func.count(func.distinct(Subscription.user_id))).where(
            Subscription.user_id.in_(trial_users_subq),
            Subscription.is_trial.is_(False),
            Subscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.EXPIRED]),
        )
        return await self.session.scalar(stmt) or 0

    async def get_stats(self) -> SubscriptionStatsDto:
        now = datetime_now()
        week_later = now + timedelta(days=7)

        is_active = Subscription.status == SubscriptionStatus.ACTIVE
        is_disabled = Subscription.status == SubscriptionStatus.DISABLED
        is_limited = Subscription.status == SubscriptionStatus.LIMITED
        is_expired = Subscription.status == SubscriptionStatus.EXPIRED

        is_expiring = and_(
            is_active,
            Subscription.expire_at >= now,
            Subscription.expire_at <= week_later,
        )

        is_unlimited = and_(
            Subscription.traffic_limit == 0,
            Subscription.device_limit == 0,
        )

        stmt = (
            select(
                func.count().label("total"),
                func.sum(case((is_active, 1), else_=0)).label("total_active"),
                func.sum(case((is_disabled, 1), else_=0)).label("total_disabled"),
                func.sum(case((is_limited, 1), else_=0)).label("total_limited"),
                func.sum(case((is_expired, 1), else_=0)).label("total_expired"),
                func.sum(
                    case((and_(is_active, Subscription.is_trial.is_(True)), 1), else_=0)
                ).label("active_trial"),
                func.sum(case((is_expiring, 1), else_=0)).label("expiring_soon"),
                func.sum(case((and_(is_active, is_unlimited), 1), else_=0)).label(
                    "total_unlimited"
                ),
                func.sum(
                    case((and_(is_active, Subscription.traffic_limit != 0), 1), else_=0)
                ).label("total_traffic"),
                func.sum(case((and_(is_active, Subscription.device_limit != 0), 1), else_=0)).label(
                    "total_devices"
                ),
            )
            .join(User, User.current_subscription_id == Subscription.id)
            .where(Subscription.status != SubscriptionStatus.DELETED)
        )

        row = (await self.session.execute(stmt)).mappings().one()
        logger.debug("Subscription stats fetched")

        return SubscriptionStatsDto(
            total=int(row["total"] or 0),
            total_active=int(row["total_active"] or 0),
            total_expired=int(row["total_expired"] or 0),
            total_disabled=int(row["total_disabled"] or 0),
            active_trial=int(row["active_trial"] or 0),
            expiring_soon=int(row["expiring_soon"] or 0),
            total_unlimited=int(row["total_unlimited"] or 0),
            total_limited=int(row["total_limited"] or 0),
            total_traffic=int(row["total_traffic"] or 0),
            total_devices=int(row["total_devices"] or 0),
        )

    async def get_plan_sub_stats(self) -> list[PlanSubStatsDto]:
        now = datetime_now()
        week_later = now + timedelta(days=7)

        plan_id_expr = Subscription.plan_snapshot["id"].as_integer()
        plan_name_expr = Subscription.plan_snapshot["name"].as_string()
        duration_expr = Subscription.plan_snapshot["duration"].as_integer()

        is_active = Subscription.status == SubscriptionStatus.ACTIVE
        is_disabled = Subscription.status == SubscriptionStatus.DISABLED
        is_limited = Subscription.status == SubscriptionStatus.LIMITED
        is_expired = Subscription.status == SubscriptionStatus.EXPIRED

        is_expiring = and_(
            is_active,
            Subscription.expire_at >= now,
            Subscription.expire_at <= week_later,
        )

        is_unlimited = and_(
            Subscription.traffic_limit == 0,
            Subscription.device_limit == 0,
        )

        counts_stmt = (
            select(
                plan_id_expr.label("plan_id"),
                plan_name_expr.label("plan_name"),
                func.count().label("total"),
                func.sum(case((is_active, 1), else_=0)).label("total_active"),
                func.sum(case((is_disabled, 1), else_=0)).label("total_disabled"),
                func.sum(case((is_limited, 1), else_=0)).label("total_limited"),
                func.sum(case((is_expired, 1), else_=0)).label("total_expired"),
                func.sum(case((is_expiring, 1), else_=0)).label("expiring_soon"),
                func.sum(case((and_(is_active, is_unlimited), 1), else_=0)).label(
                    "total_unlimited"
                ),
                func.sum(
                    case((and_(is_active, Subscription.traffic_limit != 0), 1), else_=0)
                ).label("total_traffic"),
                func.sum(case((and_(is_active, Subscription.device_limit != 0), 1), else_=0)).label(
                    "total_devices"
                ),
            )
            .join(User, User.current_subscription_id == Subscription.id)
            .where(
                plan_id_expr.isnot(None),
                Subscription.status != SubscriptionStatus.DELETED,
            )
            .group_by(plan_id_expr, plan_name_expr)
        )

        duration_subq = (
            select(
                plan_id_expr.label("plan_id"),
                duration_expr.label("duration"),
                func.row_number()
                .over(
                    partition_by=plan_id_expr,
                    order_by=func.count().desc(),
                )
                .label("rn"),
            )
            .join(User, User.current_subscription_id == Subscription.id)
            .where(
                plan_id_expr.isnot(None),
                Subscription.status != SubscriptionStatus.DELETED,
            )
            .group_by(plan_id_expr, duration_expr)
            .subquery()
        )
        popular_duration_stmt = select(
            duration_subq.c.plan_id,
            duration_subq.c.duration,
        ).where(duration_subq.c.rn == 1)

        counts_rows = await self.session.execute(counts_stmt)
        duration_rows = await self.session.execute(popular_duration_stmt)

        popular_duration_map: dict[int, int] = {
            row.plan_id: (row.duration or 0) for row in duration_rows.mappings()
        }

        logger.debug("Plan subscription stats fetched")
        return [
            PlanSubStatsDto(
                plan_id=row["plan_id"],
                plan_name=row["plan_name"] or "",
                total=int(row["total"] or 0),
                total_active=int(row["total_active"] or 0),
                total_disabled=int(row["total_disabled"] or 0),
                total_limited=int(row["total_limited"] or 0),
                total_expired=int(row["total_expired"] or 0),
                expiring_soon=int(row["expiring_soon"] or 0),
                total_unlimited=int(row["total_unlimited"] or 0),
                total_traffic=int(row["total_traffic"] or 0),
                total_devices=int(row["total_devices"] or 0),
                popular_duration=popular_duration_map.get(row["plan_id"], 0),
            )
            for row in counts_rows.mappings()
        ]
