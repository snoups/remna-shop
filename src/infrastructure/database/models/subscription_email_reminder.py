from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseSql
from .timestamp import TimestampMixin


class SubscriptionEmailReminder(BaseSql, TimestampMixin):
    __tablename__ = "subscription_email_reminders"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "subscription_id",
            "expire_at_snapshot",
            "days_before",
            name="uq_subscription_email_reminder_identity",
        ),
        CheckConstraint(
            "days_before IN (1, 3, 7)",
            name="ck_subscription_email_reminder_days_before",
        ),
        CheckConstraint(
            "state IN ('PENDING', 'PROCESSING', 'RETRY_WAITING', "
            "'SENT', 'CANCELED', 'FAILED')",
            name="ck_subscription_email_reminder_state",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_subscription_email_reminder_attempt_count",
        ),
        CheckConstraint(
            "((state = 'PROCESSING' AND processing_token_hash IS NOT NULL "
            "AND processing_lease_expires_at IS NOT NULL) OR "
            "(state <> 'PROCESSING' AND processing_token_hash IS NULL "
            "AND processing_lease_expires_at IS NULL))",
            name="ck_subscription_email_reminder_processing_fence",
        ),
        Index(
            "ix_subscription_email_reminders_due",
            "state",
            "next_attempt_at",
            "due_at",
            postgresql_where=text("state IN ('PENDING', 'RETRY_WAITING', 'PROCESSING')"),
        ),
        Index(
            "ix_subscription_email_reminders_terminal_retention",
            "updated_at",
            "id",
            postgresql_where=text("state IN ('SENT', 'CANCELED', 'FAILED')"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subscription_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("subscriptions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    expire_at_snapshot: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    days_before: Mapped[int] = mapped_column(Integer, nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    state: Mapped[str] = mapped_column(String(24), default="PENDING", nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processing_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    processing_lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
