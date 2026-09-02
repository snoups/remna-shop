from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.enums import (
    Currency,
    PaymentGatewayType,
    PurchaseType,
    TransactionFulfillmentStatus,
    TransactionStatus,
)

from .base import BaseSql
from .timestamp import TimestampMixin
from .user import User


class Transaction(BaseSql, TimestampMixin):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_transactions_id_user_id"),
        Index("ix_transactions_user_created_id", "user_id", "created_at", "id"),
        CheckConstraint(
            "(fulfillment_status = 'NOT_STARTED' "
            "AND fulfillment_token_hash IS NULL "
            "AND fulfillment_lease_expires_at IS NULL "
            "AND fulfillment_started_at IS NULL "
            "AND fulfillment_completed_at IS NULL "
            "AND status IN ('PENDING', 'CANCELED', 'REFUNDED')) OR "
            "(fulfillment_status = 'PROCESSING' "
            "AND fulfillment_token_hash IS NOT NULL "
            "AND fulfillment_lease_expires_at IS NOT NULL "
            "AND fulfillment_started_at IS NOT NULL "
            "AND fulfillment_completed_at IS NULL "
            "AND status IN ('COMPLETED', 'REFUNDED')) OR "
            "(fulfillment_status = 'SUCCEEDED' "
            "AND fulfillment_token_hash IS NULL "
            "AND fulfillment_lease_expires_at IS NULL "
            "AND fulfillment_started_at IS NOT NULL "
            "AND fulfillment_completed_at IS NOT NULL "
            "AND status IN ('COMPLETED', 'REFUNDED')) OR "
            "(fulfillment_status = 'MANUAL_REQUIRED' "
            "AND fulfillment_lease_expires_at IS NULL "
            "AND fulfillment_started_at IS NOT NULL "
            "AND fulfillment_completed_at IS NULL "
            "AND status IN ('COMPLETED', 'FAILED', 'REFUNDED'))",
            name="ck_transactions_fulfillment_state",
        ),
        CheckConstraint(
            "(status = 'CANCELED' AND cancellation_reason IN "
            "('PROVIDER', 'LOCAL_TIMEOUT', 'LEGACY_UNKNOWN')) OR "
            "(status <> 'CANCELED' AND cancellation_reason IS NULL)",
            name="ck_transactions_cancellation_reason",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[UUID] = mapped_column(index=True, unique=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )

    status: Mapped[TransactionStatus] = mapped_column(index=True)
    cancellation_reason: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    is_test: Mapped[bool]

    purchase_type: Mapped[PurchaseType]
    gateway_type: Mapped[PaymentGatewayType]
    gateway_display_name: Mapped[Optional[str]]
    payment_method: Mapped[Optional[str]]

    pricing: Mapped[dict[str, Any]]
    currency: Mapped[Currency]
    plan_snapshot: Mapped[dict[str, Any]]
    fulfillment_status: Mapped[TransactionFulfillmentStatus] = mapped_column(
        default=TransactionFulfillmentStatus.NOT_STARTED,
        server_default=TransactionFulfillmentStatus.NOT_STARTED.value,
    )
    fulfillment_token_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    fulfillment_started_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    fulfillment_lease_expires_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    fulfillment_completed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    fulfillment_last_error: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    fulfillment_alerted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    fulfillment_alert_token_hash: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    fulfillment_alert_lease_expires_at: Mapped[Optional[datetime]] = mapped_column(
        nullable=True
    )
    fulfillment_alert_attempt_count: Mapped[int] = mapped_column(
        default=0,
        server_default="0",
    )
    fulfillment_alert_next_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        nullable=True
    )

    user: Mapped["User"] = relationship(foreign_keys=[user_id])
