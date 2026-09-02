from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional, Self
from uuid import UUID

from src.core.enums import (
    Currency,
    PaymentGatewayType,
    PurchaseType,
    TransactionFulfillmentStatus,
    TransactionStatus,
)

from .base import BaseDto, TimestampMixin, TrackableMixin
from .plan import PlanSnapshotDto


@dataclass(kw_only=True)
class PriceDetailsDto(TrackableMixin):
    original_amount: Decimal
    discount_percent: int
    final_amount: Decimal

    @property
    def is_free(self) -> bool:
        return self.final_amount == 0

    @classmethod
    def test(cls) -> Self:
        return cls(
            original_amount=Decimal(2),
            discount_percent=0,
            final_amount=Decimal(2),
        )


@dataclass(kw_only=True)
class TransactionDto(BaseDto, TrackableMixin, TimestampMixin):
    payment_id: UUID
    user_id: int

    status: TransactionStatus
    cancellation_reason: Optional[str] = None
    is_test: bool = False

    purchase_type: PurchaseType
    gateway_type: PaymentGatewayType
    gateway_display_name: Optional[str] = None
    payment_method: Optional[str] = None

    pricing: "PriceDetailsDto"
    currency: Currency
    plan_snapshot: "PlanSnapshotDto"
    fulfillment_status: TransactionFulfillmentStatus = TransactionFulfillmentStatus.NOT_STARTED
    fulfillment_token_hash: Optional[str] = None
    fulfillment_started_at: Optional[datetime] = None
    fulfillment_lease_expires_at: Optional[datetime] = None
    fulfillment_completed_at: Optional[datetime] = None
    fulfillment_last_error: Optional[str] = None
    fulfillment_alerted_at: Optional[datetime] = None
    fulfillment_alert_token_hash: Optional[str] = None
    fulfillment_alert_lease_expires_at: Optional[datetime] = None
    fulfillment_alert_attempt_count: int = 0
    fulfillment_alert_next_attempt_at: Optional[datetime] = None

    @property
    def is_completed(self) -> bool:
        return self.status == TransactionStatus.COMPLETED

    @property
    def is_terminal(self) -> bool:
        return self.status in (TransactionStatus.COMPLETED, TransactionStatus.CANCELED)


@dataclass(frozen=True)
class PaymentWebhookEventDto:
    id: int
    payment_id: UUID
    gateway_type: PaymentGatewayType
    status: TransactionStatus
    selected_payment_method: Optional[str]
    processing_token_hash: Optional[str]
    processing_lease_expires_at: Optional[datetime]
    processing_attempt_count: int
    processing_next_attempt_at: Optional[datetime]
    processing_last_error: Optional[str]
    manual_required_at: Optional[datetime]
    alerted_at: Optional[datetime]
    created_at: datetime
