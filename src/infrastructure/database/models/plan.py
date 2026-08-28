from decimal import Decimal
from typing import Optional
from uuid import UUID

from remnapy.enums.users import TrafficLimitStrategy
from sqlalchemy import ARRAY, BigInteger, ForeignKey, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.enums import Currency, PlanAvailability, PlanType

from .base import BaseSql
from .timestamp import TimestampMixin


class Plan(BaseSql, TimestampMixin):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(primary_key=True)

    public_code: Mapped[str] = mapped_column(unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(unique=True, index=True)
    description: Mapped[Optional[str]]
    tag: Mapped[Optional[str]]

    type: Mapped[PlanType]
    availability: Mapped[PlanAvailability]
    traffic_limit_strategy: Mapped[TrafficLimitStrategy]

    traffic_limit: Mapped[int]
    device_limit: Mapped[int]

    allowed_telegram_ids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), server_default="{}")
    allowed_emails: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    internal_squads: Mapped[list[UUID]]
    external_squad: Mapped[Optional[UUID]]

    order_index: Mapped[int] = mapped_column(index=True)
    is_active: Mapped[bool]
    is_trial: Mapped[bool]

    durations: Mapped[list["PlanDuration"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="PlanDuration.order_index, PlanDuration.id",
    )


class PlanDuration(BaseSql):
    __tablename__ = "plan_durations"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"), index=True)

    days: Mapped[int]
    order_index: Mapped[int] = mapped_column(index=True)

    prices: Mapped[list["PlanPrice"]] = relationship(
        back_populates="plan_duration",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    plan: Mapped["Plan"] = relationship(back_populates="durations")


class PlanPrice(BaseSql):
    __tablename__ = "plan_prices"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_duration_id: Mapped[int] = mapped_column(
        ForeignKey("plan_durations.id", ondelete="CASCADE"),
        index=True,
    )

    currency: Mapped[Currency]
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    plan_duration: Mapped["PlanDuration"] = relationship(back_populates="prices")
