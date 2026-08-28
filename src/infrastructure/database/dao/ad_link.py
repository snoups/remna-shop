from typing import Optional

from adaptix import Retort
from adaptix.conversion import ConversionRetort
from loguru import logger
from sqlalchemy import delete, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.common.dao import AdLinkDao
from src.application.dto import AdLinkDto, AdLinkStatsDto
from src.core.enums import TransactionStatus
from src.infrastructure.database.models import AdLink
from src.infrastructure.database.models.transaction import Transaction
from src.infrastructure.database.models.user import User


class AdLinkDaoImpl(AdLinkDao):
    def __init__(
        self,
        session: AsyncSession,
        retort: Retort,
        conversion_retort: ConversionRetort,
    ) -> None:
        self.session = session
        self.retort = retort
        self.conversion_retort = conversion_retort

        self._to_dto = self.conversion_retort.get_converter(AdLink, AdLinkDto)
        self._to_dto_list = self.conversion_retort.get_converter(list[AdLink], list[AdLinkDto])

    async def create(self, link: AdLinkDto) -> AdLinkDto:
        data = self.retort.dump(link)
        data.pop("id", None)
        db_link = AdLink(**data)
        self.session.add(db_link)
        await self.session.flush()
        logger.debug(f"AdLink '{link.name}' created with code '{link.code}'")
        return self._to_dto(db_link)

    async def get_by_id(self, link_id: int) -> Optional[AdLinkDto]:
        db_link = await self.session.get(AdLink, link_id)
        return self._to_dto(db_link) if db_link else None

    async def get_by_code(self, code: str) -> Optional[AdLinkDto]:
        stmt = select(AdLink).where(AdLink.code == code)
        db_link = await self.session.scalar(stmt)
        if db_link:
            logger.debug(f"AdLink with code '{code}' found")
        return self._to_dto(db_link) if db_link else None

    async def get_all(self) -> list[AdLinkDto]:
        stmt = select(AdLink).order_by(AdLink.created_at.desc())
        result = await self.session.scalars(stmt)
        db_links = list(result.all())
        logger.debug(f"Retrieved {len(db_links)} ad links")
        return self._to_dto_list(db_links)

    async def update(self, link: AdLinkDto) -> Optional[AdLinkDto]:
        db_link = await self.session.get(AdLink, link.id)
        if not db_link:
            logger.warning(f"AdLink id={link.id} not found for update")
            return None
        for key, value in link.changed_data.items():
            if hasattr(db_link, key):
                setattr(db_link, key, value)
        await self.session.flush()
        logger.debug(f"AdLink id={link.id} updated")
        return self._to_dto(db_link)

    async def delete(self, link_id: int) -> bool:
        stmt = delete(AdLink).where(AdLink.id == link_id).returning(AdLink.id)
        result = await self.session.execute(stmt)
        deleted = result.scalar_one_or_none()
        if deleted:
            logger.debug(f"AdLink id={link_id} deleted")
            return True
        logger.debug(f"AdLink id={link_id} not found for deletion")
        return False

    async def get_stats(self, link_id: int) -> AdLinkStatsDto:
        registrations = (
            await self.session.scalar(select(func.count(User.id)).where(User.ad_link_id == link_id))
            or 0
        )

        trials = (
            await self.session.scalar(
                select(func.count(User.id)).where(
                    User.ad_link_id == link_id,
                    User.is_trial_available.is_(False),
                )
            )
            or 0
        )

        # Users with at least one paid purchase (final_amount > 0).
        paid_buyers_filter = (
            User.ad_link_id == link_id,
            Transaction.status == TransactionStatus.COMPLETED,
            Transaction.pricing["final_amount"].as_float() > 0,
        )

        buyers = (
            await self.session.scalar(
                select(func.count(distinct(User.id)))
                .join(Transaction, Transaction.user_id == User.id)
                .where(*paid_buyers_filter)
            )
            or 0
        )

        # Buyers who also activated their trial.
        trial_buyers = (
            await self.session.scalar(
                select(func.count(distinct(User.id)))
                .join(Transaction, Transaction.user_id == User.id)
                .where(*paid_buyers_filter, User.is_trial_available.is_(False))
            )
            or 0
        )

        amounts_stmt = (
            select(
                Transaction.currency.label("currency"),
                func.sum(Transaction.pricing["final_amount"].as_float()).label("total"),
            )
            .join(User, User.id == Transaction.user_id)
            .where(
                User.ad_link_id == link_id,
                Transaction.status == TransactionStatus.COMPLETED,
                Transaction.pricing["final_amount"].as_float() > 0,
            )
            .group_by(Transaction.currency)
        )
        amounts_rows = (await self.session.execute(amounts_stmt)).mappings().all()

        revenue: dict[str, float] = {
            row["currency"].symbol: float(row["total"] or 0) for row in amounts_rows
        }

        # Each user's earliest paid transaction, summed by currency.
        first_purchases = (
            select(
                Transaction.currency.label("currency"),
                Transaction.pricing["final_amount"].as_float().label("amount"),
            )
            .distinct(Transaction.user_id)
            .join(User, User.id == Transaction.user_id)
            .where(
                User.ad_link_id == link_id,
                Transaction.status == TransactionStatus.COMPLETED,
                Transaction.pricing["final_amount"].as_float() > 0,
            )
            .order_by(Transaction.user_id, Transaction.created_at)
            .subquery()
        )
        first_amounts_stmt = select(
            first_purchases.c.currency,
            func.sum(first_purchases.c.amount).label("total"),
        ).group_by(first_purchases.c.currency)
        first_amounts_rows = (await self.session.execute(first_amounts_stmt)).mappings().all()

        first_purchase_revenue: dict[str, float] = {
            row["currency"].symbol: float(row["total"] or 0) for row in first_amounts_rows
        }

        return AdLinkStatsDto(
            registrations=registrations,
            trials=trials,
            buyers=buyers,
            trial_buyers=trial_buyers,
            revenue=revenue,
            first_purchase_revenue=first_purchase_revenue,
        )
