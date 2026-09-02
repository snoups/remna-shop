from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.core.enums import PaymentGatewayType, TransactionStatus

from .base import BaseSql
from .timestamp import TimestampMixin


class PaymentWebhookEvent(BaseSql, TimestampMixin):
    __tablename__ = "payment_webhook_events"
    __table_args__ = (
        UniqueConstraint(
            "payment_id",
            "gateway_type",
            "status",
            name="uq_payment_webhook_events_identity",
        ),
        CheckConstraint(
            "status IN ('COMPLETED', 'CANCELED', 'REFUNDED')",
            name="ck_payment_webhook_events_status",
        ),
        CheckConstraint(
            "selected_payment_method IS NULL OR gateway_type = 'PLATEGA'",
            name="ck_payment_webhook_events_selected_method",
        ),
        Index(
            "ix_payment_webhook_events_pending",
            "manual_required_at",
            "processing_next_attempt_at",
            "processing_lease_expires_at",
            "created_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[UUID]
    gateway_type: Mapped[PaymentGatewayType]
    status: Mapped[TransactionStatus]
    selected_payment_method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    processing_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    processing_lease_expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    processing_attempt_count: Mapped[int] = mapped_column(default=0, server_default="0")
    processing_next_attempt_at: Mapped[datetime | None] = mapped_column(nullable=True)
    processing_last_error: Mapped[str | None] = mapped_column(String(64), nullable=True)
    manual_required_at: Mapped[datetime | None] = mapped_column(nullable=True)
    alerted_at: Mapped[datetime | None] = mapped_column(nullable=True)
