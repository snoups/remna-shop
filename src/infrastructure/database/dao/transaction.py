from datetime import datetime, timedelta
from decimal import Decimal
from typing import Iterable, Optional, cast
from uuid import UUID

from adaptix import Retort
from adaptix.conversion import ConversionRetort
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import and_, case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.common.dao import TransactionDao
from src.application.dto import GatewayStatsDto, PlanIncomeDto, TransactionDto, UserPaymentStatsDto
from src.core.enums import PaymentGatewayType, TransactionStatus
from src.core.utils.time import datetime_now
from src.infrastructure.database.models import Transaction


class TransactionDaoImpl(TransactionDao):
    def __init__(
        self,
        session: AsyncSession,
        retort: Retort,
        conversion_retort: ConversionRetort,
        redis: Redis,
    ) -> None:
        self.session = session
        self.retort = retort
        self.conversion_retort = conversion_retort
        self.redis = redis

        self._convert_to_dto = self.conversion_retort.get_converter(Transaction, TransactionDto)
        self._convert_to_dto_list = self.conversion_retort.get_converter(
            list[Transaction],
            list[TransactionDto],
        )

    async def create(self, transaction: TransactionDto) -> TransactionDto:
        transaction_data = self.retort.dump(transaction)
        transaction_data.pop("id", None)
        db_transaction = Transaction(**transaction_data)

        self.session.add(db_transaction)
        await self.session.flush()

        logger.debug(f"Created new transaction '{transaction.payment_id}'")
        return self._convert_to_dto(db_transaction)

    async def update(self, transaction: TransactionDto) -> Optional[TransactionDto]:
        if not transaction.changed_data:
            logger.warning("No changes detected in transaction, skipping update")
            return None

        stmt = (
            update(Transaction)
            .where(Transaction.payment_id == transaction.payment_id)
            .values(**transaction.changed_data)
            .returning(Transaction)
        )
        db_transaction = await self.session.scalar(stmt)

        if db_transaction:
            logger.debug(
                f"Transaction '{transaction.payment_id}' updated with '{transaction.changed_data}'"
            )
            return self._convert_to_dto(db_transaction)

        logger.warning(f"Failed to update transaction '{transaction.payment_id}': not found")
        return None

    async def get_by_payment_id(self, payment_id: UUID) -> Optional[TransactionDto]:
        stmt = select(Transaction).where(Transaction.payment_id == payment_id)
        db_transaction = await self.session.scalar(stmt)

        if db_transaction:
            logger.debug(f"Transaction '{payment_id}' found")
            return self._convert_to_dto(db_transaction)

        logger.debug(f"Transaction '{payment_id}' not found")
        return None

    async def get_by_user(self, user_id: int) -> list[TransactionDto]:
        stmt = (
            select(Transaction)
            .where(Transaction.user_id == user_id)
            .order_by(Transaction.created_at.desc())
        )
        result = await self.session.scalars(stmt)
        db_transactions = cast(list, result.all())

        logger.debug(f"Retrieved '{len(db_transactions)}' transactions for user_id '{user_id}'")
        return self._convert_to_dto_list(db_transactions)

    async def get_all(self, limit: int = 100, offset: int = 0) -> list[TransactionDto]:
        stmt = (
            select(Transaction).limit(limit).offset(offset).order_by(Transaction.created_at.desc())
        )
        result = await self.session.scalars(stmt)
        db_transactions = cast(list, result.all())

        logger.debug(
            f"Retrieved '{len(db_transactions)}' transactions "
            f"with limit '{limit}' and offset '{offset}'"
        )
        return self._convert_to_dto_list(db_transactions)

    async def get_by_status(self, status: TransactionStatus) -> list[TransactionDto]:
        stmt = select(Transaction).where(Transaction.status == status)
        result = await self.session.scalars(stmt)
        db_transactions = cast(list, result.all())

        logger.debug(f"Found '{len(db_transactions)}' transactions with status '{status}'")
        return self._convert_to_dto_list(db_transactions)

    async def update_status(
        self,
        payment_id: UUID,
        status: TransactionStatus,
    ) -> Optional[TransactionDto]:
        stmt = (
            update(Transaction)
            .where(Transaction.payment_id == payment_id)
            .values(status=status)
            .returning(Transaction)
        )
        db_transaction = await self.session.scalar(stmt)

        if db_transaction:
            logger.debug(f"Transaction '{payment_id}' status updated to '{status}'")
            return self._convert_to_dto(db_transaction)

        logger.warning(f"Failed to update transaction '{payment_id}': not found")
        return None

    async def transition_status(
        self,
        payment_id: UUID,
        new_status: TransactionStatus,
        allowed_current: Iterable[TransactionStatus],
    ) -> Optional[TransactionDto]:
        stmt = (
            update(Transaction)
            .where(
                Transaction.payment_id == payment_id,
                Transaction.status.in_(tuple(allowed_current)),
            )
            .values(status=new_status)
            .returning(Transaction)
        )
        db_transaction = await self.session.scalar(stmt)
        if db_transaction:
            logger.debug(f"Transaction '{payment_id}' transitioned to '{new_status}'")
            return self._convert_to_dto(db_transaction)
        logger.info(f"Transaction '{payment_id}' transition to '{new_status}' did not match")
        return None

    async def exists(self, payment_id: UUID) -> bool:
        stmt = select(select(Transaction).where(Transaction.payment_id == payment_id).exists())
        is_exists = await self.session.scalar(stmt) or False

        logger.debug(f"Transaction '{payment_id}' existence status is '{is_exists}'")
        return is_exists

    async def has_paid_purchase_excluding_stars(self, user_id: int) -> bool:
        stmt = select(
            select(Transaction)
            .where(
                Transaction.user_id == user_id,
                Transaction.status == TransactionStatus.COMPLETED,
                Transaction.is_test.is_(False),
                Transaction.gateway_type != PaymentGatewayType.TELEGRAM_STARS,
            )
            .exists()
        )
        result = await self.session.scalar(stmt) or False

        logger.debug(f"User '{user_id}' has non-stars paid purchase: '{result}'")
        return result

    async def cancel_old(self, minutes: int = 30) -> int:
        threshold = datetime_now() - timedelta(minutes=minutes)

        stmt = (
            update(Transaction)
            .where(Transaction.status == TransactionStatus.PENDING)
            .where(Transaction.created_at < threshold)
            .values(status=TransactionStatus.CANCELED)
        )
        result = await self.session.execute(stmt)
        count = result.rowcount  # type: ignore[attr-defined]

        if count > 0:
            logger.debug(f"Cancelled '{count}' pending transactions older than '{minutes}' minutes")
        else:
            logger.debug(f"No pending transactions older than '{minutes}' minutes found to cancel")

        return cast(int, count)

    async def count(self) -> int:
        stmt = select(func.count()).select_from(Transaction)
        total = await self.session.scalar(stmt) or 0

        logger.debug(f"Total transactions count is '{total}'")
        return total

    async def count_paying_users(self) -> int:
        stmt = select(func.count(func.distinct(Transaction.user_id))).where(
            Transaction.status == TransactionStatus.COMPLETED
        )

        return await self.session.scalar(stmt) or 0

    async def count_total(self) -> int:
        stmt = select(func.count()).select_from(Transaction)
        return await self.session.scalar(stmt) or 0

    async def count_completed(self) -> int:
        stmt = (
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.status == TransactionStatus.COMPLETED)
        )
        return await self.session.scalar(stmt) or 0

    async def count_free(self) -> int:
        stmt = (
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.pricing["final_amount"].as_float() == 0)
        )
        return await self.session.scalar(stmt) or 0

    async def get_gateway_stats(self) -> list[GatewayStatsDto]:
        now = datetime_now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_ago = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        month_ago = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_month_end = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_month_start = (last_month_end - timedelta(days=1)).replace(day=1)

        final_amount = Transaction.pricing["final_amount"].as_float()
        original_amount = Transaction.pricing["original_amount"].as_float()
        is_free = final_amount == 0
        is_completed = Transaction.status == TransactionStatus.COMPLETED

        stmt = select(
            Transaction.gateway_type,
            func.count().label("total_transactions"),
            func.sum(case((is_completed, 1), else_=0)).label("completed_transactions"),
            func.sum(case((is_free, 1), else_=0)).label("free_transactions"),
            func.sum(case((is_completed, final_amount), else_=0.0)).label("total_income"),
            func.sum(
                case(
                    (
                        and_(is_completed, Transaction.created_at >= today_start),
                        final_amount,
                    ),
                    else_=0.0,
                )
            ).label("daily_income"),
            func.sum(
                case(
                    (
                        and_(is_completed, Transaction.created_at >= week_ago),
                        final_amount,
                    ),
                    else_=0.0,
                )
            ).label("weekly_income"),
            func.sum(
                case(
                    (
                        and_(is_completed, Transaction.created_at >= month_ago),
                        final_amount,
                    ),
                    else_=0.0,
                )
            ).label("monthly_income"),
            func.sum(
                case(
                    (
                        and_(
                            is_completed,
                            Transaction.created_at >= last_month_start,
                            Transaction.created_at < last_month_end,
                        ),
                        final_amount,
                    ),
                    else_=0.0,
                )
            ).label("last_month_income"),
            func.sum(case((and_(is_completed, ~is_free), 1), else_=0)).label("paid_count"),
            func.sum(case((and_(is_completed, ~is_free), 1), else_=0)).label("paid_count"),
            func.sum(case((is_completed, original_amount - final_amount), else_=0.0)).label(
                "total_discounts"
            ),
        ).group_by(Transaction.gateway_type)

        result = await self.session.execute(stmt)
        rows = result.mappings().all()

        logger.debug(f"Gateway stats fetched for {len(rows)} gateways")
        return [
            GatewayStatsDto(
                gateway_type=row["gateway_type"],
                total_income=Decimal(row["total_income"] or 0),
                daily_income=Decimal(row["daily_income"] or 0),
                weekly_income=Decimal(row["weekly_income"] or 0),
                monthly_income=Decimal(row["monthly_income"] or 0),
                last_month_income=Decimal(row["last_month_income"] or 0),
                paid_count=int(row["paid_count"] or 0),
                total_discounts=Decimal(row["total_discounts"] or 0),
                total_transactions=int(row["total_transactions"] or 0),
                completed_transactions=int(row["completed_transactions"] or 0),
                free_transactions=int(row["free_transactions"] or 0),
            )
            for row in rows
        ]

    async def get_plan_income(self) -> list[PlanIncomeDto]:
        plan_id_expr = Transaction.plan_snapshot["id"].as_integer()
        final_amount_expr = Transaction.pricing["final_amount"].as_float()

        stmt = (
            select(
                plan_id_expr.label("plan_id"),
                Transaction.currency.label("currency"),
                func.sum(final_amount_expr).label("total_income"),
            )
            .where(
                Transaction.status == TransactionStatus.COMPLETED,
                plan_id_expr.isnot(None),
            )
            .group_by(plan_id_expr, Transaction.currency)
        )

        result = await self.session.execute(stmt)
        logger.debug("Plan income stats fetched")
        return [
            PlanIncomeDto(
                plan_id=row["plan_id"],
                currency=row["currency"].symbol,
                total_income=float(row["total_income"] or 0),
            )
            for row in result.mappings()
        ]

    async def get_recent_pending(
        self,
        user_id: int,
        plan_id: int,
        duration_days: int,
        gateway_type: PaymentGatewayType,
    ) -> Optional[TransactionDto]:
        threshold = datetime_now() - timedelta(minutes=15)
        stmt = (
            select(Transaction)
            .where(
                Transaction.user_id == user_id,
                Transaction.gateway_type == gateway_type,
                Transaction.status == TransactionStatus.PENDING,
                Transaction.plan_snapshot["id"].as_integer() == plan_id,
                Transaction.plan_snapshot["duration"].as_integer() == duration_days,
                Transaction.created_at >= threshold,
            )
            .order_by(Transaction.created_at.desc())
            .limit(1)
        )
        db_transaction = await self.session.scalar(stmt)

        if db_transaction:
            logger.debug(
                f"Found recent pending transaction for user_id '{user_id}', "
                f"plan_id '{plan_id}', duration '{duration_days}'"
            )
            return self._convert_to_dto(db_transaction)

        logger.debug(
            f"No recent pending transaction for user_id '{user_id}', "
            f"plan_id '{plan_id}', duration '{duration_days}'"
        )
        return None

    async def get_user_payment_stats(
        self,
        user_id: int,
    ) -> tuple[Optional[datetime], list[UserPaymentStatsDto]]:
        last_payment_stmt = (
            select(Transaction.created_at)
            .where(
                Transaction.user_id == user_id,
                Transaction.status == TransactionStatus.COMPLETED,
            )
            .order_by(Transaction.created_at.desc())
            .limit(1)
        )

        amounts_stmt = (
            select(
                Transaction.currency.label("currency"),
                func.sum(Transaction.pricing["final_amount"].as_float()).label("total_amount"),
            )
            .where(
                Transaction.user_id == user_id,
                Transaction.status == TransactionStatus.COMPLETED,
                Transaction.pricing["final_amount"].as_float() > 0,
            )
            .group_by(Transaction.currency)
        )

        last_payment_at = await self.session.scalar(last_payment_stmt)
        amounts_rows = (await self.session.execute(amounts_stmt)).mappings().all()

        return last_payment_at, [
            UserPaymentStatsDto(
                currency=row["currency"].symbol,
                total_amount=float(row["total_amount"] or 0),
            )
            for row in amounts_rows
        ]
