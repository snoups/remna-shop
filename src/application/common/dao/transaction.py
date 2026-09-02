from datetime import datetime, timedelta
from typing import Iterable, Optional, Protocol, runtime_checkable
from uuid import UUID

from src.application.dto import (
    GatewayStatsDto,
    PaymentWebhookEventDto,
    PlanIncomeDto,
    TransactionDto,
    UserPaymentStatsDto,
)
from src.core.enums import PaymentGatewayType, TransactionStatus


class TransactionOwnerUnavailableError(Exception): ...


@runtime_checkable
class TransactionDao(Protocol):
    async def create(self, transaction: TransactionDto) -> TransactionDto: ...

    async def update(self, transaction: TransactionDto) -> Optional[TransactionDto]: ...

    async def get_by_payment_id(self, payment_id: UUID) -> Optional[TransactionDto]: ...

    async def get_by_payment_id_for_user(
        self,
        user_id: int,
        payment_id: UUID,
    ) -> Optional[TransactionDto]: ...

    async def get_by_internal_id_for_user(
        self,
        user_id: int,
        transaction_id: int,
    ) -> Optional[TransactionDto]: ...

    async def list_historical_referral_reward_sources(
        self,
        *,
        limit: int,
        offset: int,
    ) -> list[TransactionDto]: ...

    async def get_historical_referral_reward_sources(
        self,
        transaction_ids: list[int],
        *,
        for_update: bool = False,
    ) -> list[TransactionDto]: ...

    async def get_first_successful_paid_transaction_id(self, user_id: int) -> Optional[int]: ...

    async def get_by_user(self, user_id: int) -> list[TransactionDto]: ...

    async def get_page_by_user(
        self,
        user_id: int,
        *,
        limit: int,
        before_created_at: Optional[datetime] = None,
        before_id: Optional[int] = None,
    ) -> list[TransactionDto]: ...

    async def get_all(self, limit: int = 100, offset: int = 0) -> list[TransactionDto]: ...

    async def get_by_status(self, status: TransactionStatus) -> list[TransactionDto]: ...

    async def update_status(
        self,
        payment_id: UUID,
        status: TransactionStatus,
    ) -> Optional[TransactionDto]: ...

    async def transition_status(
        self,
        payment_id: UUID,
        new_status: TransactionStatus,
        allowed_current: Iterable[TransactionStatus],
    ) -> Optional[TransactionDto]: ...

    async def set_payment_method_if_absent_or_equal(
        self,
        payment_id: UUID,
        *,
        payment_method: str,
    ) -> bool: ...

    async def cancel_by_provider(self, payment_id: UUID) -> Optional[TransactionDto]: ...

    async def transition_refunded(self, payment_id: UUID) -> Optional[TransactionDto]: ...

    async def mark_refund_manual_required(self, payment_id: UUID) -> bool: ...

    async def claim_fulfillment(
        self,
        payment_id: UUID,
        *,
        token_hash: str,
        lease_for: timedelta,
    ) -> Optional[TransactionDto]: ...

    async def complete_fulfillment(self, payment_id: UUID, *, token_hash: str) -> bool: ...

    async def mark_fulfillment_manual_required(
        self,
        payment_id: UUID,
        *,
        token_hash: str,
        error_code: str,
    ) -> bool: ...

    async def expire_fulfillment(self, payment_id: UUID) -> bool: ...

    async def expire_fulfillments(self, *, limit: int) -> int: ...

    async def claim_manual_fulfillment_alerts(
        self,
        *,
        token_hash: str,
        lease_for: timedelta,
        limit: int,
    ) -> list[TransactionDto]: ...

    async def mark_fulfillment_alerted(
        self,
        payment_id: UUID,
        *,
        token_hash: Optional[str] = None,
    ) -> bool: ...

    async def release_fulfillment_alert(
        self,
        payment_id: UUID,
        *,
        token_hash: str,
        retry_after: timedelta,
    ) -> bool: ...

    async def store_webhook_event(
        self,
        *,
        payment_id: UUID,
        gateway_type: PaymentGatewayType,
        status: TransactionStatus,
        selected_payment_method: Optional[str] = None,
        error_code: Optional[str] = None,
    ) -> None: ...

    async def claim_webhook_event_by_identity(
        self,
        *,
        payment_id: UUID,
        gateway_type: PaymentGatewayType,
        status: TransactionStatus,
        token_hash: str,
        lease_for: timedelta,
    ) -> Optional[PaymentWebhookEventDto]: ...

    async def claim_replayable_webhook_events(
        self,
        *,
        token_hash: str,
        lease_for: timedelta,
        limit: int,
    ) -> list[PaymentWebhookEventDto]: ...

    async def delete_webhook_event(self, event_id: int, *, token_hash: str) -> bool: ...

    async def release_webhook_event(
        self,
        event_id: int,
        *,
        token_hash: str,
        retry_after: timedelta,
        error_code: str,
        manual_required: bool,
    ) -> bool: ...

    async def claim_manual_webhook_alerts(
        self,
        *,
        token_hash: str,
        lease_for: timedelta,
        limit: int,
    ) -> list[PaymentWebhookEventDto]: ...

    async def mark_webhook_alerted(self, event_id: int, *, token_hash: str) -> bool: ...

    async def delete_webhook_event_by_identity(
        self,
        *,
        payment_id: UUID,
        gateway_type: PaymentGatewayType,
        status: TransactionStatus,
    ) -> bool: ...

    async def mark_expired_orphaned_webhook_events(
        self,
        *,
        retention: timedelta,
        limit: int,
    ) -> int: ...

    async def exists(self, payment_id: UUID) -> bool: ...

    async def has_paid_purchase_excluding_stars(self, user_id: int) -> bool: ...

    async def cancel_old(self, minutes: int = 30) -> int: ...

    async def count(self) -> int: ...

    async def count_paying_users(self) -> int: ...

    async def count_total(self) -> int: ...

    async def count_completed(self) -> int: ...

    async def count_free(self) -> int: ...

    async def get_gateway_stats(self) -> list[GatewayStatsDto]: ...

    async def get_plan_income(self) -> list[PlanIncomeDto]: ...

    async def get_recent_pending(
        self,
        user_id: int,
        plan_id: int,
        duration_days: int,
        gateway_type: PaymentGatewayType,
    ) -> Optional[TransactionDto]: ...

    async def get_user_payment_stats(
        self,
        user_id: int,
    ) -> tuple[Optional[datetime], list[UserPaymentStatsDto]]: ...
