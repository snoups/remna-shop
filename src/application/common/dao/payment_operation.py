from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Optional, Protocol


class PaymentOperationStatus(StrEnum):
    CLAIMED = "CLAIMED"
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    UNKNOWN = "UNKNOWN"
    MANUAL_REQUIRED = "MANUAL_REQUIRED"


class PaymentOperationRecoveryMode(StrEnum):
    MANUAL_REQUIRED = "MANUAL_REQUIRED"
    LOCAL = "LOCAL"
    YOOKASSA_REPLAY = "YOOKASSA_REPLAY"


class PaymentOperationOwnerMergedError(Exception): ...


@dataclass(frozen=True)
class PaymentOperationRecord:
    id: int
    user_id: int
    operation: str
    idempotency_key: str
    request_hash: str
    status: PaymentOperationStatus
    provider_key: str
    response: Optional[dict[str, Any]]
    lease_expires_at: Optional[datetime]
    transaction_id: Optional[int]
    gateway_type: Optional[str]
    resolved_payment_snapshot: Optional[dict[str, Any]]
    provider_request_snapshot: Optional[dict[str, Any]]
    provider_owner_hash: Optional[str]
    provider_result_snapshot: Optional[dict[str, Any]]
    recovery_mode: PaymentOperationRecoveryMode
    provider_replay_expires_at: Optional[datetime]
    reconcile_token_hash: Optional[str]
    reconcile_lease_expires_at: Optional[datetime]
    reconcile_attempt_count: int
    reconcile_next_attempt_at: Optional[datetime]
    reconcile_last_attempt_at: Optional[datetime]
    reconcile_last_error: Optional[str]
    reconcile_alerted_at: Optional[datetime]
    reconcile_alert_token_hash: Optional[str]
    reconcile_alert_lease_expires_at: Optional[datetime]
    reconcile_alert_attempt_count: int
    reconcile_alert_next_attempt_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class PaymentOperationDao(Protocol):
    async def claim(
        self,
        *,
        user_id: int,
        operation: str,
        idempotency_key: str,
        request_hash: str,
        provider_key: str,
        lease_for: timedelta,
    ) -> tuple[PaymentOperationRecord, bool]: ...

    async def get_by_id(self, operation_id: int) -> Optional[PaymentOperationRecord]: ...

    async def get_by_identity(
        self,
        *,
        user_id: int,
        operation: str,
        idempotency_key: str,
    ) -> Optional[PaymentOperationRecord]: ...

    async def reclaim_claimed(
        self,
        operation_id: int,
        *,
        lease_for: timedelta,
    ) -> bool: ...

    async def mark_processing(
        self,
        operation_id: int,
        *,
        lease_for: timedelta,
        gateway_type: str,
        resolved_payment_snapshot: dict[str, Any],
        provider_request_snapshot: dict[str, Any],
        provider_owner_hash: Optional[str],
        recovery_mode: PaymentOperationRecoveryMode,
        provider_replay_for: Optional[timedelta],
    ) -> bool: ...

    async def checkpoint_provider_result(
        self,
        operation_id: int,
        result: dict[str, Any],
    ) -> bool: ...

    async def link_transaction(
        self,
        operation_id: int,
        transaction_id: int,
    ) -> bool: ...

    async def complete(self, operation_id: int, response: dict[str, Any]) -> bool: ...

    async def mark_unknown(self, operation_id: int) -> bool: ...

    async def expire_processing(self, operation_id: int) -> bool: ...

    async def delete_expired_claimed(self, operation_id: int) -> bool: ...

    async def delete_claimed(self, operation_id: int) -> bool: ...

    async def claim_reconciliation(
        self,
        operation_id: int,
        *,
        token_hash: str,
        lease_for: timedelta,
    ) -> bool: ...

    async def mark_expired_provider_replay_manual(
        self,
        operation_id: int,
    ) -> bool: ...

    async def mark_exhausted_reconciliation_manual(
        self,
        operation_id: int,
        *,
        max_attempts: int,
    ) -> bool: ...

    async def expire_reconciliations(self, *, limit: int) -> int: ...

    async def release_reconciliation(
        self,
        operation_id: int,
        *,
        token_hash: str,
        retry_after: timedelta,
        error_code: str,
    ) -> bool: ...

    async def checkpoint_reconciliation_result(
        self,
        operation_id: int,
        *,
        token_hash: str,
        result: dict[str, Any],
    ) -> bool: ...

    async def mark_manual_required(
        self,
        operation_id: int,
        *,
        token_hash: str,
        error_code: str,
    ) -> bool: ...

    async def link_manual_reconciliation(
        self,
        operation_id: int,
        *,
        token_hash: str,
        transaction_id: int,
        error_code: str,
    ) -> bool: ...

    async def link_pending_fulfillment_reconciliation(
        self,
        operation_id: int,
        *,
        token_hash: str,
        transaction_id: int,
        provider_result: dict[str, Any],
        retry_after: timedelta,
    ) -> bool: ...

    async def complete_reconciliation(
        self,
        operation_id: int,
        *,
        token_hash: str,
        transaction_id: int,
        response: dict[str, Any],
        provider_result: Optional[dict[str, Any]] = None,
    ) -> bool: ...

    async def claim_manual_reconciliation_alerts(
        self,
        *,
        token_hash: str,
        lease_for: timedelta,
        limit: int,
    ) -> list[PaymentOperationRecord]: ...

    async def mark_reconciliation_alerted(
        self,
        operation_id: int,
        *,
        token_hash: str,
    ) -> bool: ...

    async def release_reconciliation_alert(
        self,
        operation_id: int,
        *,
        token_hash: str,
        retry_after: timedelta,
    ) -> bool: ...
