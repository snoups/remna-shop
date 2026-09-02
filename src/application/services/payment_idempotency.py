import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Optional

from src.application.common.dao import PaymentOperationDao
from src.application.common.dao.payment_operation import (
    PaymentOperationRecord,
    PaymentOperationRecoveryMode,
    PaymentOperationStatus,
)
from src.application.common.uow import UnitOfWork

CLAIM_LEASE = timedelta(minutes=5)
PROCESSING_LEASE = timedelta(minutes=30)


class PaymentOperationConflictError(Exception): ...


class PaymentOperationInProgressError(Exception): ...


class PaymentOperationOutcomeUnknownError(Exception): ...


@dataclass(frozen=True)
class PaymentOperationStart:
    operation_id: int
    provider_key: str
    replay_response: Optional[dict[str, Any]] = None


class PaymentIdempotencyService:
    def __init__(self, uow: UnitOfWork, payment_operation_dao: PaymentOperationDao) -> None:
        self.uow = uow
        self.payment_operation_dao = payment_operation_dao

    async def _recover_stale(
        self,
        record: PaymentOperationRecord,
    ) -> tuple[PaymentOperationRecord, bool]:
        became_leader = False
        if record.status == PaymentOperationStatus.CLAIMED:
            became_leader = await self.payment_operation_dao.reclaim_claimed(
                record.id,
                lease_for=CLAIM_LEASE,
            )
        elif record.status == PaymentOperationStatus.PROCESSING:
            await self.payment_operation_dao.expire_processing(record.id)
        else:
            return record, False

        if became_leader:
            return record, True

        refreshed = await self.payment_operation_dao.get_by_id(record.id)
        if refreshed is None:
            raise RuntimeError("Payment operation disappeared during lease recovery")
        return refreshed, False

    async def start(
        self,
        *,
        user_id: int,
        operation: str,
        idempotency_key: str,
        request_hash: str,
    ) -> PaymentOperationStart:
        became_leader = False
        async with self.uow:
            record, created = await self.payment_operation_dao.claim(
                user_id=user_id,
                operation=operation,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                provider_key=str(uuid.uuid4()),
                lease_for=CLAIM_LEASE,
            )

            if not created and record.request_hash == request_hash:
                record, became_leader = await self._recover_stale(record)

            await self.uow.commit()

        if record.request_hash != request_hash:
            raise PaymentOperationConflictError

        if created or became_leader:
            return PaymentOperationStart(
                operation_id=record.id,
                provider_key=record.provider_key,
            )

        if record.status == PaymentOperationStatus.SUCCEEDED:
            if record.response is None:
                raise PaymentOperationOutcomeUnknownError
            return PaymentOperationStart(
                operation_id=record.id,
                provider_key=record.provider_key,
                replay_response=record.response,
            )

        if record.status in (
            PaymentOperationStatus.UNKNOWN,
            PaymentOperationStatus.MANUAL_REQUIRED,
        ):
            raise PaymentOperationOutcomeUnknownError

        raise PaymentOperationInProgressError

    async def mark_processing(
        self,
        operation_id: int,
        *,
        gateway_type: str,
        resolved_payment_snapshot: dict[str, Any],
        provider_request_snapshot: dict[str, Any],
        provider_owner_hash: Optional[str],
        recovery_mode: PaymentOperationRecoveryMode,
        provider_replay_for: Optional[timedelta],
    ) -> None:
        async with self.uow:
            updated = await self.payment_operation_dao.mark_processing(
                operation_id,
                lease_for=PROCESSING_LEASE,
                gateway_type=gateway_type,
                resolved_payment_snapshot=resolved_payment_snapshot,
                provider_request_snapshot=provider_request_snapshot,
                provider_owner_hash=provider_owner_hash,
                recovery_mode=recovery_mode,
                provider_replay_for=provider_replay_for,
            )
            if not updated:
                raise RuntimeError("Payment operation is no longer claimable")
            await self.uow.commit()

    async def checkpoint_provider_result(
        self,
        operation_id: int,
        result: dict[str, Any],
    ) -> None:
        async with self.uow:
            updated = await self.payment_operation_dao.checkpoint_provider_result(
                operation_id,
                result,
            )
            if not updated:
                raise RuntimeError("Payment operation lost its execution lease")
            await self.uow.commit()

    async def link_transaction(self, operation_id: int, transaction_id: int) -> None:
        updated = await self.payment_operation_dao.link_transaction(operation_id, transaction_id)
        if not updated:
            raise RuntimeError("Payment operation is no longer owned by the request")

    async def complete_in_current_transaction(
        self,
        operation_id: int,
        response: dict[str, Any],
    ) -> None:
        updated = await self.payment_operation_dao.complete(operation_id, response)
        if not updated:
            raise RuntimeError("Payment operation is no longer processing")

    async def get_owned_operation(
        self,
        *,
        user_id: int,
        operation: str,
        idempotency_key: str,
    ) -> Optional[PaymentOperationRecord]:
        async with self.uow:
            record = await self.payment_operation_dao.get_by_identity(
                user_id=user_id,
                operation=operation,
                idempotency_key=idempotency_key,
            )
            await self.uow.commit()
        return record

    async def complete(self, operation_id: int, response: dict[str, Any]) -> None:
        async with self.uow:
            updated = await self.payment_operation_dao.complete(operation_id, response)
            if not updated:
                raise RuntimeError("Payment operation is no longer processing")
            await self.uow.commit()

    async def mark_unknown(self, operation_id: int) -> None:
        # The caller can arrive here after a failed flush/commit in another use case.
        # Reset that transaction before recording the durable ambiguous outcome.
        await self.uow.rollback()
        async with self.uow:
            await self.payment_operation_dao.mark_unknown(operation_id)
            await self.uow.commit()

    async def abandon(self, operation_id: int) -> None:
        # CLAIMED means the endpoint has not crossed the side-effect boundary, so
        # deleting it is safe and permits a corrected request to use the same key.
        await self.uow.rollback()
        async with self.uow:
            await self.payment_operation_dao.delete_claimed(operation_id)
            await self.uow.commit()
