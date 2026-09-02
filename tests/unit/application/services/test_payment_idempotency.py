import asyncio
from dataclasses import replace
from datetime import timedelta
from typing import Any, Optional

import pytest

from src.application.common.dao.payment_operation import (
    PaymentOperationRecord,
    PaymentOperationRecoveryMode,
    PaymentOperationStatus,
)
from src.application.services.payment_idempotency import (
    PaymentIdempotencyService,
    PaymentOperationConflictError,
    PaymentOperationInProgressError,
    PaymentOperationOutcomeUnknownError,
)
from src.core.utils.time import datetime_now


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def __aenter__(self) -> "FakeUnitOfWork":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class FakePaymentOperationDao:
    def __init__(self) -> None:
        self.records: dict[tuple[int, str, str], PaymentOperationRecord] = {}
        self.next_id = 1

    def _find(self, operation_id: int) -> tuple[tuple[int, str, str], PaymentOperationRecord]:
        return next((item for item in self.records.items() if item[1].id == operation_id))

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
        identity = (user_id, operation, idempotency_key)
        if identity in self.records:
            return self.records[identity], False
        record = PaymentOperationRecord(
            id=self.next_id,
            user_id=user_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            status=PaymentOperationStatus.CLAIMED,
            provider_key=provider_key,
            response=None,
            lease_expires_at=datetime_now() + lease_for,
            transaction_id=None,
            gateway_type=None,
            resolved_payment_snapshot=None,
            provider_request_snapshot=None,
            provider_owner_hash=None,
            provider_result_snapshot=None,
            recovery_mode=PaymentOperationRecoveryMode.MANUAL_REQUIRED,
            provider_replay_expires_at=None,
            reconcile_token_hash=None,
            reconcile_lease_expires_at=None,
            reconcile_attempt_count=0,
            reconcile_next_attempt_at=None,
            reconcile_last_attempt_at=None,
            reconcile_last_error=None,
            reconcile_alerted_at=None,
            reconcile_alert_token_hash=None,
            reconcile_alert_lease_expires_at=None,
            reconcile_alert_attempt_count=0,
            reconcile_alert_next_attempt_at=None,
            created_at=datetime_now(),
            updated_at=datetime_now(),
        )
        self.next_id += 1
        self.records[identity] = record
        return record, True

    async def get_by_id(self, operation_id: int) -> Optional[PaymentOperationRecord]:
        try:
            return self._find(operation_id)[1]
        except StopIteration:
            return None

    async def reclaim_claimed(
        self,
        operation_id: int,
        *,
        lease_for: timedelta,
    ) -> bool:
        identity, record = self._find(operation_id)
        if (
            record.status != PaymentOperationStatus.CLAIMED
            or record.lease_expires_at is None
            or record.lease_expires_at > datetime_now()
        ):
            return False
        self.records[identity] = replace(
            record,
            lease_expires_at=datetime_now() + lease_for,
            updated_at=datetime_now(),
        )
        return True

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
        identity, record = self._find(operation_id)
        if record.status != PaymentOperationStatus.CLAIMED:
            return False
        self.records[identity] = replace(
            record,
            status=PaymentOperationStatus.PROCESSING,
            lease_expires_at=datetime_now() + lease_for,
            gateway_type=gateway_type,
            resolved_payment_snapshot=resolved_payment_snapshot,
            provider_request_snapshot=provider_request_snapshot,
            provider_owner_hash=provider_owner_hash,
            recovery_mode=recovery_mode,
            provider_replay_expires_at=(
                datetime_now() + provider_replay_for
                if provider_replay_for is not None
                else None
            ),
            updated_at=datetime_now(),
        )
        return True

    async def complete(self, operation_id: int, response: dict[str, Any]) -> bool:
        identity, record = self._find(operation_id)
        if record.status != PaymentOperationStatus.PROCESSING:
            return False
        self.records[identity] = replace(
            record,
            status=PaymentOperationStatus.SUCCEEDED,
            response=response,
            lease_expires_at=None,
            updated_at=datetime_now(),
        )
        return True

    async def mark_unknown(self, operation_id: int) -> bool:
        identity, record = self._find(operation_id)
        if record.status != PaymentOperationStatus.PROCESSING:
            return False
        self.records[identity] = replace(
            record,
            status=PaymentOperationStatus.UNKNOWN,
            lease_expires_at=None,
            updated_at=datetime_now(),
        )
        return True

    async def expire_processing(self, operation_id: int) -> bool:
        identity, record = self._find(operation_id)
        if (
            record.status != PaymentOperationStatus.PROCESSING
            or record.lease_expires_at is None
            or record.lease_expires_at > datetime_now()
        ):
            return False
        self.records[identity] = replace(
            record,
            status=PaymentOperationStatus.UNKNOWN,
            lease_expires_at=None,
            updated_at=datetime_now(),
        )
        return True

    async def delete_claimed(self, operation_id: int) -> bool:
        identity, record = self._find(operation_id)
        if record.status != PaymentOperationStatus.CLAIMED:
            return False
        del self.records[identity]
        return True


def make_service(
    dao: Optional[FakePaymentOperationDao] = None,
) -> tuple[PaymentIdempotencyService, FakePaymentOperationDao]:
    operation_dao = dao or FakePaymentOperationDao()
    return PaymentIdempotencyService(FakeUnitOfWork(), operation_dao), operation_dao  # type: ignore[arg-type]


async def mark_processing(service: PaymentIdempotencyService, operation_id: int) -> None:
    await service.mark_processing(
        operation_id,
        gateway_type="YOOKASSA",
        resolved_payment_snapshot={"version": 1},
        provider_request_snapshot={"amount": {"value": "10", "currency": "RUB"}},
        provider_owner_hash="a" * 64,
        recovery_mode=PaymentOperationRecoveryMode.YOOKASSA_REPLAY,
            provider_replay_for=timedelta(hours=23),
    )


@pytest.mark.asyncio
async def test_completed_operation_replays_same_response_and_provider_key() -> None:
    service, _ = make_service()
    started = await service.start(
        user_id=7,
        operation="PURCHASE",
        idempotency_key="request-key-0001",
        request_hash="a" * 64,
    )
    await mark_processing(service, started.operation_id)
    response = {"payment_id": "payment-1", "status": "PENDING"}
    await service.complete(started.operation_id, response)

    replay = await service.start(
        user_id=7,
        operation="PURCHASE",
        idempotency_key="request-key-0001",
        request_hash="a" * 64,
    )

    assert replay.provider_key == started.provider_key
    assert replay.replay_response == response


@pytest.mark.asyncio
async def test_same_key_with_different_payload_is_conflict() -> None:
    service, _ = make_service()
    await service.start(
        user_id=7,
        operation="PURCHASE",
        idempotency_key="request-key-0002",
        request_hash="a" * 64,
    )

    with pytest.raises(PaymentOperationConflictError):
        await service.start(
            user_id=7,
            operation="PURCHASE",
            idempotency_key="request-key-0002",
            request_hash="b" * 64,
        )


@pytest.mark.asyncio
async def test_concurrent_claim_has_exactly_one_leader() -> None:
    first, dao = make_service()
    second, _ = make_service(dao)

    results = await asyncio.gather(
        first.start(
            user_id=7,
            operation="EXTEND",
            idempotency_key="request-key-0003",
            request_hash="c" * 64,
        ),
        second.start(
            user_id=7,
            operation="EXTEND",
            idempotency_key="request-key-0003",
            request_hash="c" * 64,
        ),
        return_exceptions=True,
    )

    assert sum(not isinstance(result, BaseException) for result in results) == 1
    assert sum(isinstance(result, PaymentOperationInProgressError) for result in results) == 1


@pytest.mark.asyncio
async def test_stale_claimed_operation_is_reclaimed_with_single_cas_winner() -> None:
    first, dao = make_service()
    second, _ = make_service(dao)
    started = await first.start(
        user_id=7,
        operation="PURCHASE",
        idempotency_key="request-key-claim-crash",
        request_hash="e" * 64,
    )
    identity, record = dao._find(started.operation_id)
    dao.records[identity] = replace(
        record,
        lease_expires_at=datetime_now() - timedelta(seconds=1),
    )

    reclaimed = await second.start(
        user_id=7,
        operation="PURCHASE",
        idempotency_key="request-key-claim-crash",
        request_hash="e" * 64,
    )
    assert reclaimed.operation_id == started.operation_id
    assert reclaimed.provider_key == started.provider_key

    transitions = await asyncio.gather(
        mark_processing(first, started.operation_id),
        mark_processing(second, reclaimed.operation_id),
        return_exceptions=True,
    )
    assert sum(result is None for result in transitions) == 1
    assert sum(isinstance(result, RuntimeError) for result in transitions) == 1


@pytest.mark.asyncio
async def test_stale_processing_operation_becomes_unknown_without_retry() -> None:
    first, dao = make_service()
    second, _ = make_service(dao)
    started = await first.start(
        user_id=7,
        operation="EXTEND",
        idempotency_key="request-key-processing-crash",
        request_hash="f" * 64,
    )
    await mark_processing(first, started.operation_id)
    identity, record = dao._find(started.operation_id)
    dao.records[identity] = replace(
        record,
        lease_expires_at=datetime_now() - timedelta(seconds=1),
    )

    with pytest.raises(PaymentOperationOutcomeUnknownError):
        await second.start(
            user_id=7,
            operation="EXTEND",
            idempotency_key="request-key-processing-crash",
            request_hash="f" * 64,
        )

    assert dao.records[identity].status == PaymentOperationStatus.UNKNOWN
    assert dao.records[identity].lease_expires_at is None


@pytest.mark.asyncio
async def test_unknown_outcome_never_restarts_side_effect() -> None:
    service, _ = make_service()
    started = await service.start(
        user_id=7,
        operation="PURCHASE",
        idempotency_key="request-key-0004",
        request_hash="d" * 64,
    )
    await mark_processing(service, started.operation_id)
    await service.mark_unknown(started.operation_id)

    with pytest.raises(PaymentOperationOutcomeUnknownError):
        await service.start(
            user_id=7,
            operation="PURCHASE",
            idempotency_key="request-key-0004",
            request_hash="d" * 64,
        )
