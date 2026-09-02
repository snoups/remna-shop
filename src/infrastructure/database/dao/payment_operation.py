from datetime import timedelta
from typing import Any, Optional, cast

from sqlalchemy import Numeric, and_, delete, exists, func, or_, select, update
from sqlalchemy import cast as sa_cast
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from src.application.common.dao.payment_operation import (
    PaymentOperationDao,
    PaymentOperationOwnerMergedError,
    PaymentOperationRecord,
    PaymentOperationRecoveryMode,
    PaymentOperationStatus,
)
from src.core.enums import TransactionFulfillmentStatus
from src.infrastructure.database.models import PaymentOperation, Transaction, User


class PaymentOperationDaoImpl(PaymentOperationDao):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _to_record(operation: PaymentOperation) -> PaymentOperationRecord:
        return PaymentOperationRecord(
            id=operation.id,
            user_id=operation.user_id,
            operation=operation.operation,
            idempotency_key=operation.idempotency_key,
            request_hash=operation.request_hash,
            status=PaymentOperationStatus(operation.status),
            provider_key=operation.provider_key,
            response=operation.response,
            lease_expires_at=operation.lease_expires_at,
            transaction_id=operation.transaction_id,
            gateway_type=operation.gateway_type,
            resolved_payment_snapshot=operation.resolved_payment_snapshot,
            provider_request_snapshot=operation.provider_request_snapshot,
            provider_owner_hash=operation.provider_owner_hash,
            provider_result_snapshot=operation.provider_result_snapshot,
            recovery_mode=PaymentOperationRecoveryMode(operation.recovery_mode),
            provider_replay_expires_at=operation.provider_replay_expires_at,
            reconcile_token_hash=operation.reconcile_token_hash,
            reconcile_lease_expires_at=operation.reconcile_lease_expires_at,
            reconcile_attempt_count=operation.reconcile_attempt_count,
            reconcile_next_attempt_at=operation.reconcile_next_attempt_at,
            reconcile_last_attempt_at=operation.reconcile_last_attempt_at,
            reconcile_last_error=operation.reconcile_last_error,
            reconcile_alerted_at=operation.reconcile_alerted_at,
            reconcile_alert_token_hash=operation.reconcile_alert_token_hash,
            reconcile_alert_lease_expires_at=(
                operation.reconcile_alert_lease_expires_at
            ),
            reconcile_alert_attempt_count=operation.reconcile_alert_attempt_count,
            reconcile_alert_next_attempt_at=operation.reconcile_alert_next_attempt_at,
            created_at=operation.created_at,
            updated_at=operation.updated_at,
        )

    @staticmethod
    def _owner_lock_stmt(user_id: int) -> Select[tuple[int, Optional[int]]]:
        return (
            select(User.id, User.merged_into_user_id)
            .where(User.id == user_id)
            .with_for_update(read=True, key_share=True)
        )

    async def _lock_active_owner(self, user_id: int) -> None:
        owner = (await self.session.execute(self._owner_lock_stmt(user_id))).one_or_none()
        if owner is None or owner.merged_into_user_id is not None:
            raise PaymentOperationOwnerMergedError

    async def _lock_operation_owner(self, operation_id: int) -> bool:
        owner_id = await self.session.scalar(
            select(PaymentOperation.user_id).where(PaymentOperation.id == operation_id)
        )
        if owner_id is None:
            return False
        await self._lock_active_owner(owner_id)
        return True

    async def claim(
        self,
        *,
        user_id: int,
        operation: str,
        idempotency_key: str,
        request_hash: str,
        provider_key: str,
        lease_for: timedelta,
    ) -> tuple[PaymentOperationRecord, bool]:
        # FOR KEY SHARE serializes operation creation with user merge's FOR
        # UPDATE locks. A claim either commits before the merge and is moved, or
        # resumes afterwards and observes the merged tombstone.
        await self._lock_active_owner(user_id)
        stmt = (
            insert(PaymentOperation)
            .values(
                user_id=user_id,
                operation=operation,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                status=PaymentOperationStatus.CLAIMED.value,
                provider_key=provider_key,
                lease_expires_at=func.clock_timestamp() + lease_for,
            )
            .on_conflict_do_nothing(constraint="uq_payment_operations_identity")
            .returning(PaymentOperation)
        )
        inserted = await self.session.scalar(stmt)
        if inserted is not None:
            return self._to_record(inserted), True

        existing = await self.session.scalar(
            select(PaymentOperation).where(
                PaymentOperation.user_id == user_id,
                PaymentOperation.operation == operation,
                PaymentOperation.idempotency_key == idempotency_key,
            )
        )
        if existing is None:
            raise RuntimeError("Payment operation conflict was not readable")
        return self._to_record(existing), False

    async def get_by_id(self, operation_id: int) -> Optional[PaymentOperationRecord]:
        operation = await self.session.scalar(
            select(PaymentOperation).where(PaymentOperation.id == operation_id)
        )
        return self._to_record(operation) if operation is not None else None

    async def get_by_identity(
        self,
        *,
        user_id: int,
        operation: str,
        idempotency_key: str,
    ) -> Optional[PaymentOperationRecord]:
        payment_operation = await self.session.scalar(
            select(PaymentOperation).where(
                PaymentOperation.user_id == user_id,
                PaymentOperation.operation == operation,
                PaymentOperation.idempotency_key == idempotency_key,
            )
        )
        return self._to_record(payment_operation) if payment_operation is not None else None

    async def reclaim_claimed(
        self,
        operation_id: int,
        *,
        lease_for: timedelta,
    ) -> bool:
        result = await self.session.execute(
            update(PaymentOperation)
            .where(
                PaymentOperation.id == operation_id,
                PaymentOperation.status == PaymentOperationStatus.CLAIMED.value,
                PaymentOperation.lease_expires_at <= func.clock_timestamp(),
            )
            .values(lease_expires_at=func.clock_timestamp() + lease_for)
        )
        return cast(int, result.rowcount) == 1  # type: ignore[attr-defined]

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
    ) -> bool:
        result = await self.session.execute(
            update(PaymentOperation)
            .where(
                PaymentOperation.id == operation_id,
                PaymentOperation.status == PaymentOperationStatus.CLAIMED.value,
            )
            .values(
                status=PaymentOperationStatus.PROCESSING.value,
                lease_expires_at=func.clock_timestamp() + lease_for,
                gateway_type=gateway_type,
                resolved_payment_snapshot=resolved_payment_snapshot,
                provider_request_snapshot=provider_request_snapshot,
                provider_owner_hash=provider_owner_hash,
                recovery_mode=recovery_mode.value,
                provider_replay_expires_at=(
                    func.clock_timestamp() + provider_replay_for
                    if provider_replay_for is not None
                    else None
                ),
            )
        )
        return cast(int, result.rowcount) == 1  # type: ignore[attr-defined]

    async def checkpoint_provider_result(
        self,
        operation_id: int,
        result_snapshot: dict[str, Any],
    ) -> bool:
        result = await self.session.execute(
            update(PaymentOperation)
            .where(
                PaymentOperation.id == operation_id,
                PaymentOperation.status == PaymentOperationStatus.PROCESSING.value,
                or_(
                    PaymentOperation.provider_result_snapshot.is_(None),
                    PaymentOperation.provider_result_snapshot == result_snapshot,
                ),
            )
            .values(provider_result_snapshot=result_snapshot)
        )
        return cast(int, result.rowcount) == 1  # type: ignore[attr-defined]

    async def link_transaction(self, operation_id: int, transaction_id: int) -> bool:
        result = await self.session.execute(
            update(PaymentOperation)
            .where(
                PaymentOperation.id == operation_id,
                PaymentOperation.status == PaymentOperationStatus.PROCESSING.value,
                or_(
                    PaymentOperation.transaction_id.is_(None),
                    PaymentOperation.transaction_id == transaction_id,
                ),
            )
            .values(transaction_id=transaction_id)
        )
        return cast(int, result.rowcount) == 1  # type: ignore[attr-defined]

    async def complete(self, operation_id: int, response: dict[str, Any]) -> bool:
        linked_free = exists(
            select(Transaction.id).where(
                Transaction.id == PaymentOperation.transaction_id,
                sa_cast(Transaction.pricing["final_amount"].astext, Numeric) == 0,
            )
        )
        linked_fulfilled = exists(
            select(Transaction.id).where(
                Transaction.id == PaymentOperation.transaction_id,
                Transaction.fulfillment_status
                == TransactionFulfillmentStatus.SUCCEEDED,
                Transaction.fulfillment_completed_at.is_not(None),
            )
        )
        result = await self.session.execute(
            update(PaymentOperation)
            .where(
                PaymentOperation.id == operation_id,
                or_(
                    and_(
                        PaymentOperation.status == PaymentOperationStatus.PROCESSING.value,
                        PaymentOperation.transaction_id.is_not(None),
                        or_(
                            and_(
                                PaymentOperation.recovery_mode
                                != PaymentOperationRecoveryMode.LOCAL.value,
                                ~linked_free,
                            ),
                            linked_fulfilled,
                        ),
                    ),
                    and_(
                        PaymentOperation.status == PaymentOperationStatus.SUCCEEDED.value,
                        PaymentOperation.response == response,
                    ),
                ),
            )
            .values(
                status=PaymentOperationStatus.SUCCEEDED.value,
                response=response,
                lease_expires_at=None,
            )
        )
        return cast(int, result.rowcount) == 1  # type: ignore[attr-defined]

    async def mark_unknown(self, operation_id: int) -> bool:
        result = await self.session.execute(
            update(PaymentOperation)
            .where(
                PaymentOperation.id == operation_id,
                PaymentOperation.status == PaymentOperationStatus.PROCESSING.value,
            )
            .values(status=PaymentOperationStatus.UNKNOWN.value, lease_expires_at=None)
        )
        return cast(int, result.rowcount) == 1  # type: ignore[attr-defined]

    async def expire_processing(self, operation_id: int) -> bool:
        result = await self.session.execute(
            update(PaymentOperation)
            .where(
                PaymentOperation.id == operation_id,
                PaymentOperation.status == PaymentOperationStatus.PROCESSING.value,
                PaymentOperation.lease_expires_at <= func.clock_timestamp(),
            )
            .values(status=PaymentOperationStatus.UNKNOWN.value, lease_expires_at=None)
        )
        return cast(int, result.rowcount) == 1  # type: ignore[attr-defined]

    async def delete_expired_claimed(self, operation_id: int) -> bool:
        result = await self.session.execute(
            delete(PaymentOperation)
            .where(
                PaymentOperation.id == operation_id,
                PaymentOperation.status == PaymentOperationStatus.CLAIMED.value,
                PaymentOperation.lease_expires_at <= func.clock_timestamp(),
            )
        )
        return cast(int, result.rowcount) == 1  # type: ignore[attr-defined]

    async def claim_reconciliation(
        self,
        operation_id: int,
        *,
        token_hash: str,
        lease_for: timedelta,
    ) -> bool:
        if not await self._lock_operation_owner(operation_id):
            return False
        now = func.clock_timestamp()
        result = await self.session.execute(
            update(PaymentOperation)
            .where(
                PaymentOperation.id == operation_id,
                PaymentOperation.status == PaymentOperationStatus.UNKNOWN.value,
                or_(
                    PaymentOperation.reconcile_next_attempt_at.is_(None),
                    PaymentOperation.reconcile_next_attempt_at <= now,
                ),
                PaymentOperation.reconcile_token_hash.is_(None),
            )
            .values(
                reconcile_token_hash=token_hash,
                reconcile_lease_expires_at=now + lease_for,
                reconcile_attempt_count=PaymentOperation.reconcile_attempt_count + 1,
                reconcile_last_attempt_at=now,
                reconcile_last_error=None,
            )
        )
        return cast(int, result.rowcount) == 1  # type: ignore[attr-defined]

    async def mark_expired_provider_replay_manual(
        self,
        operation_id: int,
    ) -> bool:
        now = func.clock_timestamp()
        result = await self.session.execute(
            update(PaymentOperation)
            .where(
                PaymentOperation.id == operation_id,
                PaymentOperation.status == PaymentOperationStatus.UNKNOWN.value,
                PaymentOperation.recovery_mode
                == PaymentOperationRecoveryMode.YOOKASSA_REPLAY.value,
                PaymentOperation.provider_result_snapshot.is_(None),
                PaymentOperation.provider_replay_expires_at.is_not(None),
                PaymentOperation.provider_replay_expires_at <= now,
                PaymentOperation.reconcile_token_hash.is_(None),
            )
            .values(
                status=PaymentOperationStatus.MANUAL_REQUIRED.value,
                reconcile_next_attempt_at=None,
                reconcile_last_error="PROVIDER_REPLAY_EXPIRED",
            )
        )
        return cast(int, result.rowcount) == 1  # type: ignore[attr-defined]

    async def mark_exhausted_reconciliation_manual(
        self,
        operation_id: int,
        *,
        max_attempts: int,
    ) -> bool:
        result = await self.session.execute(
            update(PaymentOperation)
            .where(
                PaymentOperation.id == operation_id,
                PaymentOperation.status == PaymentOperationStatus.UNKNOWN.value,
                PaymentOperation.reconcile_token_hash.is_(None),
                PaymentOperation.reconcile_attempt_count >= max_attempts,
            )
            .values(
                status=PaymentOperationStatus.MANUAL_REQUIRED.value,
                reconcile_next_attempt_at=None,
                reconcile_last_error="RECONCILIATION_RETRIES_EXHAUSTED",
            )
        )
        return cast(int, result.rowcount) == 1  # type: ignore[attr-defined]

    async def expire_reconciliations(self, *, limit: int) -> int:
        now = func.clock_timestamp()
        candidates = (
            select(PaymentOperation.id)
            .where(
                PaymentOperation.status == PaymentOperationStatus.UNKNOWN.value,
                PaymentOperation.reconcile_token_hash.is_not(None),
                PaymentOperation.reconcile_lease_expires_at <= now,
            )
            .order_by(PaymentOperation.reconcile_lease_expires_at, PaymentOperation.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self.session.execute(
            update(PaymentOperation)
            .where(PaymentOperation.id.in_(candidates))
            .values(
                status=PaymentOperationStatus.MANUAL_REQUIRED.value,
                reconcile_next_attempt_at=None,
                reconcile_last_error="RECONCILIATION_LEASE_EXPIRED",
            )
        )
        return cast(int, result.rowcount)  # type: ignore[attr-defined]

    async def release_reconciliation(
        self,
        operation_id: int,
        *,
        token_hash: str,
        retry_after: timedelta,
        error_code: str,
    ) -> bool:
        now = func.clock_timestamp()
        result = await self.session.execute(
            update(PaymentOperation)
            .where(
                PaymentOperation.id == operation_id,
                PaymentOperation.status.in_(
                    (
                        PaymentOperationStatus.UNKNOWN.value,
                        PaymentOperationStatus.MANUAL_REQUIRED.value,
                    )
                ),
                PaymentOperation.reconcile_token_hash == token_hash,
                PaymentOperation.reconcile_lease_expires_at > now,
            )
            .values(
                reconcile_token_hash=None,
                reconcile_lease_expires_at=None,
                reconcile_next_attempt_at=now + retry_after,
                reconcile_last_error=error_code,
            )
        )
        return cast(int, result.rowcount) == 1  # type: ignore[attr-defined]

    async def checkpoint_reconciliation_result(
        self,
        operation_id: int,
        *,
        token_hash: str,
        result: dict[str, Any],
    ) -> bool:
        now = func.clock_timestamp()
        query_result = await self.session.execute(
            update(PaymentOperation)
            .where(
                PaymentOperation.id == operation_id,
                PaymentOperation.status.in_(
                    (
                        PaymentOperationStatus.UNKNOWN.value,
                        PaymentOperationStatus.MANUAL_REQUIRED.value,
                    )
                ),
                PaymentOperation.reconcile_token_hash == token_hash,
                PaymentOperation.reconcile_lease_expires_at > now,
                or_(
                    PaymentOperation.provider_result_snapshot.is_(None),
                    PaymentOperation.provider_result_snapshot == result,
                ),
            )
            .values(provider_result_snapshot=result)
        )
        return cast(int, query_result.rowcount) == 1  # type: ignore[attr-defined]

    async def mark_manual_required(
        self,
        operation_id: int,
        *,
        token_hash: str,
        error_code: str,
    ) -> bool:
        now = func.clock_timestamp()
        result = await self.session.execute(
            update(PaymentOperation)
            .where(
                PaymentOperation.id == operation_id,
                PaymentOperation.status.in_(
                    (
                        PaymentOperationStatus.UNKNOWN.value,
                        PaymentOperationStatus.MANUAL_REQUIRED.value,
                    )
                ),
                PaymentOperation.reconcile_token_hash == token_hash,
                PaymentOperation.reconcile_lease_expires_at > now,
            )
            .values(
                status=PaymentOperationStatus.MANUAL_REQUIRED.value,
                reconcile_token_hash=None,
                reconcile_lease_expires_at=None,
                reconcile_next_attempt_at=None,
                reconcile_last_error=error_code,
            )
        )
        return cast(int, result.rowcount) == 1  # type: ignore[attr-defined]

    async def link_manual_reconciliation(
        self,
        operation_id: int,
        *,
        token_hash: str,
        transaction_id: int,
        error_code: str,
    ) -> bool:
        now = func.clock_timestamp()
        result = await self.session.execute(
            update(PaymentOperation)
            .where(
                PaymentOperation.id == operation_id,
                PaymentOperation.status.in_(
                    (
                        PaymentOperationStatus.UNKNOWN.value,
                        PaymentOperationStatus.MANUAL_REQUIRED.value,
                    )
                ),
                PaymentOperation.reconcile_token_hash == token_hash,
                PaymentOperation.reconcile_lease_expires_at > now,
                PaymentOperation.transaction_id.is_(None),
            )
            .values(
                status=PaymentOperationStatus.MANUAL_REQUIRED.value,
                transaction_id=transaction_id,
                reconcile_token_hash=None,
                reconcile_lease_expires_at=None,
                reconcile_next_attempt_at=None,
                reconcile_last_error=error_code,
            )
        )
        return cast(int, result.rowcount) == 1  # type: ignore[attr-defined]

    async def link_pending_fulfillment_reconciliation(
        self,
        operation_id: int,
        *,
        token_hash: str,
        transaction_id: int,
        provider_result: dict[str, Any],
        retry_after: timedelta,
    ) -> bool:
        now = func.clock_timestamp()
        result = await self.session.execute(
            update(PaymentOperation)
            .where(
                PaymentOperation.id == operation_id,
                PaymentOperation.status.in_(
                    (
                        PaymentOperationStatus.UNKNOWN.value,
                        PaymentOperationStatus.MANUAL_REQUIRED.value,
                    )
                ),
                PaymentOperation.reconcile_token_hash == token_hash,
                PaymentOperation.reconcile_lease_expires_at > now,
                PaymentOperation.transaction_id.is_(None),
            )
            .values(
                transaction_id=transaction_id,
                provider_result_snapshot=provider_result,
                reconcile_token_hash=None,
                reconcile_lease_expires_at=None,
                reconcile_next_attempt_at=now + retry_after,
                reconcile_last_error="AWAITING_FULFILLMENT",
            )
        )
        return cast(int, result.rowcount) == 1  # type: ignore[attr-defined]

    async def complete_reconciliation(
        self,
        operation_id: int,
        *,
        token_hash: str,
        transaction_id: int,
        response: dict[str, Any],
        provider_result: Optional[dict[str, Any]] = None,
    ) -> bool:
        now = func.clock_timestamp()
        values: dict[str, Any] = {
            "status": PaymentOperationStatus.SUCCEEDED.value,
            "transaction_id": transaction_id,
            "response": response,
            "lease_expires_at": None,
            "reconcile_token_hash": None,
            "reconcile_lease_expires_at": None,
            "reconcile_next_attempt_at": None,
            "reconcile_last_error": None,
        }
        if provider_result is not None:
            values["provider_result_snapshot"] = provider_result
        result = await self.session.execute(
            update(PaymentOperation)
            .where(
                PaymentOperation.id == operation_id,
                PaymentOperation.status.in_(
                    (
                        PaymentOperationStatus.UNKNOWN.value,
                        PaymentOperationStatus.MANUAL_REQUIRED.value,
                    )
                ),
                PaymentOperation.reconcile_token_hash == token_hash,
                PaymentOperation.reconcile_lease_expires_at > now,
                or_(
                    PaymentOperation.transaction_id.is_(None),
                    PaymentOperation.transaction_id == transaction_id,
                ),
            )
            .values(**values)
        )
        return cast(int, result.rowcount) == 1  # type: ignore[attr-defined]

    async def claim_manual_reconciliation_alerts(
        self,
        *,
        token_hash: str,
        lease_for: timedelta,
        limit: int,
    ) -> list[PaymentOperationRecord]:
        now = func.clock_timestamp()
        candidates = (
            select(PaymentOperation.id)
            .where(
                PaymentOperation.status
                == PaymentOperationStatus.MANUAL_REQUIRED.value,
                PaymentOperation.reconcile_alerted_at.is_(None),
                or_(
                    PaymentOperation.reconcile_alert_next_attempt_at.is_(None),
                    PaymentOperation.reconcile_alert_next_attempt_at <= now,
                ),
                or_(
                    PaymentOperation.reconcile_alert_token_hash.is_(None),
                    PaymentOperation.reconcile_alert_lease_expires_at <= now,
                ),
            )
            .order_by(
                PaymentOperation.reconcile_alert_next_attempt_at.asc().nullsfirst(),
                PaymentOperation.updated_at,
                PaymentOperation.id,
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        operations = list(
            (
                await self.session.scalars(
                    update(PaymentOperation)
                    .where(PaymentOperation.id.in_(candidates))
                    .values(
                        reconcile_alert_token_hash=token_hash,
                        reconcile_alert_lease_expires_at=now + lease_for,
                        reconcile_alert_attempt_count=(
                            PaymentOperation.reconcile_alert_attempt_count + 1
                        ),
                    )
                    .returning(PaymentOperation)
                )
            ).all()
        )
        return [self._to_record(operation) for operation in operations]

    async def mark_reconciliation_alerted(
        self,
        operation_id: int,
        *,
        token_hash: str,
    ) -> bool:
        result = await self.session.execute(
            update(PaymentOperation)
            .where(
                PaymentOperation.id == operation_id,
                PaymentOperation.status
                == PaymentOperationStatus.MANUAL_REQUIRED.value,
                PaymentOperation.reconcile_alerted_at.is_(None),
                PaymentOperation.reconcile_alert_token_hash == token_hash,
            )
            .values(
                reconcile_alerted_at=func.clock_timestamp(),
                reconcile_alert_token_hash=None,
                reconcile_alert_lease_expires_at=None,
                reconcile_alert_next_attempt_at=None,
            )
        )
        return cast(int, result.rowcount) == 1  # type: ignore[attr-defined]

    async def release_reconciliation_alert(
        self,
        operation_id: int,
        *,
        token_hash: str,
        retry_after: timedelta,
    ) -> bool:
        now = func.clock_timestamp()
        result = await self.session.execute(
            update(PaymentOperation)
            .where(
                PaymentOperation.id == operation_id,
                PaymentOperation.reconcile_alerted_at.is_(None),
                PaymentOperation.reconcile_alert_token_hash == token_hash,
            )
            .values(
                reconcile_alert_token_hash=None,
                reconcile_alert_lease_expires_at=None,
                reconcile_alert_next_attempt_at=now + retry_after,
            )
        )
        return cast(int, result.rowcount) == 1  # type: ignore[attr-defined]

    async def delete_claimed(self, operation_id: int) -> bool:
        result = await self.session.execute(
            delete(PaymentOperation).where(
                PaymentOperation.id == operation_id,
                PaymentOperation.status == PaymentOperationStatus.CLAIMED.value,
            )
        )
        return cast(int, result.rowcount) == 1  # type: ignore[attr-defined]
