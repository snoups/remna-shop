from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseSql
from .timestamp import TimestampMixin


class PaymentOperation(BaseSql, TimestampMixin):
    __tablename__ = "payment_operations"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "operation",
            "idempotency_key",
            name="uq_payment_operations_identity",
        ),
        CheckConstraint(
            "operation IN ('PURCHASE', 'EXTEND')",
            name="ck_payment_operations_operation",
        ),
        CheckConstraint(
            "status IN ('CLAIMED', 'PROCESSING', 'SUCCEEDED', 'UNKNOWN', 'MANUAL_REQUIRED')",
            name="ck_payment_operations_status",
        ),
        CheckConstraint(
            "((status IN ('CLAIMED', 'PROCESSING') AND lease_expires_at IS NOT NULL) "
            "OR (status IN ('SUCCEEDED', 'UNKNOWN', 'MANUAL_REQUIRED') "
            "AND lease_expires_at IS NULL))",
            name="ck_payment_operations_lease",
        ),
        CheckConstraint(
            "recovery_mode IN ('MANUAL_REQUIRED', 'LOCAL', 'YOOKASSA_REPLAY')",
            name="ck_payment_operations_recovery_mode",
        ),
        CheckConstraint(
            "gateway_type IS NULL OR gateway_type IN ("
            "'TELEGRAM_STARS', 'YOOKASSA', 'YOOMONEY', 'VALUTIX', 'CRYPTOMUS', "
            "'HELEKET', 'CRYPTOPAY', 'FREEKASSA', 'MULENPAY', 'PAYMASTER', "
            "'PLATEGA', 'ROBOKASSA', 'URLPAY', 'WATA')",
            name="ck_payment_operations_gateway_type",
        ),
        CheckConstraint(
            "((reconcile_token_hash IS NULL AND reconcile_lease_expires_at IS NULL) "
            "OR (reconcile_token_hash IS NOT NULL AND reconcile_lease_expires_at IS NOT NULL))",
            name="ck_payment_operations_reconcile_lease",
        ),
        CheckConstraint(
            "reconcile_attempt_count >= 0",
            name="ck_payment_operations_reconcile_attempt_count",
        ),
        CheckConstraint(
            "status <> 'SUCCEEDED' OR (transaction_id IS NOT NULL AND response IS NOT NULL)",
            name="ck_payment_operations_succeeded_transaction",
        ),
        UniqueConstraint(
            "transaction_id",
            name="uq_payment_operations_transaction_id",
        ),
        ForeignKeyConstraint(
            ["transaction_id", "user_id"],
            ["transactions.id", "transactions.user_id"],
            name="fk_payment_operations_transaction_owner",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index("ix_payment_operations_status_updated_at", "status", "updated_at"),
        Index(
            "ix_payment_operations_reconcile_queue",
            "status",
            "reconcile_next_attempt_at",
            "reconcile_lease_expires_at",
        ),
        Index(
            "ix_payment_operations_manual_alerts",
            "status",
            "reconcile_alerted_at",
            "reconcile_alert_next_attempt_at",
            "reconcile_alert_lease_expires_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "users.id",
            name="fk_payment_operations_user_id_users",
            ondelete="RESTRICT",
        ),
        index=True,
    )
    operation: Mapped[str] = mapped_column(String(16))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    provider_key: Mapped[str] = mapped_column(String(64), unique=True)
    response: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    transaction_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    gateway_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    resolved_payment_snapshot: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
    )
    provider_request_snapshot: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
    )
    provider_owner_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    provider_result_snapshot: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
    )
    recovery_mode: Mapped[str] = mapped_column(
        String(32),
        default="MANUAL_REQUIRED",
        server_default="MANUAL_REQUIRED",
    )
    provider_replay_expires_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    reconcile_token_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    reconcile_lease_expires_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    reconcile_attempt_count: Mapped[int] = mapped_column(default=0, server_default="0")
    reconcile_next_attempt_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    reconcile_last_attempt_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    reconcile_last_error: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    reconcile_alerted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    reconcile_alert_token_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    reconcile_alert_lease_expires_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    reconcile_alert_attempt_count: Mapped[int] = mapped_column(default=0, server_default="0")
    reconcile_alert_next_attempt_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
