import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Optional, cast
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from remnapy.enums.users import TrafficLimitStrategy

from src.application.common.dao.payment_operation import (
    PaymentOperationRecord,
    PaymentOperationRecoveryMode,
    PaymentOperationStatus,
)
from src.application.dto import (
    PaymentResultDto,
    PlanSnapshotDto,
    PriceDetailsDto,
    TransactionDto,
)
from src.application.services.payment_reconciliation import (
    MAX_RECONCILIATION_ATTEMPTS,
    PaymentOperationNotFoundError,
    PaymentOperationPublicState,
    PaymentReconciliationService,
)
from src.application.services.payment_recovery_snapshot import (
    build_payment_response,
    build_resolved_payment_snapshot,
)
from src.application.use_cases.misc.commands.maintenance import SweepPaymentOperationAlerts
from src.core.enums import (
    Currency,
    PaymentGatewayType,
    PlanType,
    PurchaseType,
    TransactionFulfillmentStatus,
    TransactionStatus,
)
from src.core.utils.time import datetime_now


class FakeUnitOfWork:
    async def __aenter__(self) -> "FakeUnitOfWork":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class FakeOperationDao:
    def __init__(self, record: PaymentOperationRecord) -> None:
        self.record = record
        self.deleted = False
        self._claim_lock = asyncio.Lock()

    async def get_by_identity(self, **kwargs: Any) -> Optional[PaymentOperationRecord]:
        if self.deleted:
            return None
        if (
            kwargs["user_id"] == self.record.user_id
            and kwargs["operation"] == self.record.operation
            and kwargs["idempotency_key"] == self.record.idempotency_key
        ):
            return self.record
        return None

    async def get_by_id(self, operation_id: int) -> Optional[PaymentOperationRecord]:
        return self.record if not self.deleted and operation_id == self.record.id else None

    async def claim_reconciliation(
        self,
        operation_id: int,
        *,
        token_hash: str,
        lease_for: timedelta,
    ) -> bool:
        async with self._claim_lock:
            if (
                operation_id != self.record.id
                or self.record.status != PaymentOperationStatus.UNKNOWN
                or self.record.reconcile_token_hash is not None
            ):
                return False
            self.record = replace(
                self.record,
                reconcile_token_hash=token_hash,
                reconcile_lease_expires_at=datetime_now() + lease_for,
                reconcile_attempt_count=self.record.reconcile_attempt_count + 1,
            )
            return True

    async def mark_expired_provider_replay_manual(
        self,
        operation_id: int,
    ) -> bool:
        if (
            operation_id != self.record.id
            or self.record.status != PaymentOperationStatus.UNKNOWN
            or self.record.recovery_mode
            != PaymentOperationRecoveryMode.YOOKASSA_REPLAY
            or self.record.provider_result_snapshot is not None
            or self.record.provider_replay_expires_at is None
            or self.record.provider_replay_expires_at > datetime_now()
            or self.record.reconcile_token_hash is not None
        ):
            return False
        self.record = replace(
            self.record,
            status=PaymentOperationStatus.MANUAL_REQUIRED,
            reconcile_next_attempt_at=None,
            reconcile_last_error="PROVIDER_REPLAY_EXPIRED",
        )
        return True

    async def mark_exhausted_reconciliation_manual(
        self,
        operation_id: int,
        *,
        max_attempts: int,
    ) -> bool:
        if (
            operation_id != self.record.id
            or self.record.status != PaymentOperationStatus.UNKNOWN
            or self.record.reconcile_token_hash is not None
            or self.record.reconcile_attempt_count < max_attempts
        ):
            return False
        self.record = replace(
            self.record,
            status=PaymentOperationStatus.MANUAL_REQUIRED,
            reconcile_next_attempt_at=None,
            reconcile_last_error="RECONCILIATION_RETRIES_EXHAUSTED",
        )
        return True

    async def expire_processing(self, operation_id: int) -> bool:
        if (
            operation_id != self.record.id
            or self.record.status != PaymentOperationStatus.PROCESSING
            or self.record.lease_expires_at is None
            or self.record.lease_expires_at > datetime_now()
        ):
            return False
        self.record = replace(
            self.record,
            status=PaymentOperationStatus.UNKNOWN,
            lease_expires_at=None,
        )
        return True

    async def delete_expired_claimed(self, operation_id: int) -> bool:
        if (
            operation_id != self.record.id
            or self.record.status != PaymentOperationStatus.CLAIMED
            or self.record.lease_expires_at is None
            or self.record.lease_expires_at > datetime_now()
        ):
            return False
        self.deleted = True
        return True

    async def checkpoint_reconciliation_result(
        self,
        operation_id: int,
        *,
        token_hash: str,
        result: dict[str, Any],
    ) -> bool:
        if not self._owns(operation_id, token_hash):
            return False
        self.record = replace(self.record, provider_result_snapshot=result)
        return True

    async def complete_reconciliation(
        self,
        operation_id: int,
        *,
        token_hash: str,
        transaction_id: int,
        response: dict[str, Any],
        provider_result: Optional[dict[str, Any]] = None,
    ) -> bool:
        if not self._owns(operation_id, token_hash):
            return False
        self.record = replace(
            self.record,
            status=PaymentOperationStatus.SUCCEEDED,
            transaction_id=transaction_id,
            response=response,
            provider_result_snapshot=provider_result or self.record.provider_result_snapshot,
            reconcile_token_hash=None,
            reconcile_lease_expires_at=None,
        )
        return True

    async def mark_manual_required(
        self,
        operation_id: int,
        *,
        token_hash: str,
        error_code: str,
    ) -> bool:
        if not self._owns(operation_id, token_hash):
            return False
        self.record = replace(
            self.record,
            status=PaymentOperationStatus.MANUAL_REQUIRED,
            reconcile_token_hash=None,
            reconcile_lease_expires_at=None,
            reconcile_last_error=error_code,
        )
        return True

    async def link_manual_reconciliation(
        self,
        operation_id: int,
        *,
        token_hash: str,
        transaction_id: int,
        error_code: str,
    ) -> bool:
        if not self._owns(operation_id, token_hash):
            return False
        self.record = replace(
            self.record,
            status=PaymentOperationStatus.MANUAL_REQUIRED,
            transaction_id=transaction_id,
            reconcile_token_hash=None,
            reconcile_lease_expires_at=None,
            reconcile_last_error=error_code,
        )
        return True

    async def link_pending_fulfillment_reconciliation(
        self,
        operation_id: int,
        *,
        token_hash: str,
        transaction_id: int,
        provider_result: dict[str, Any],
        retry_after: timedelta,
    ) -> bool:
        if not self._owns(operation_id, token_hash):
            return False
        self.record = replace(
            self.record,
            transaction_id=transaction_id,
            provider_result_snapshot=provider_result,
            reconcile_token_hash=None,
            reconcile_lease_expires_at=None,
            reconcile_next_attempt_at=datetime_now() + retry_after,
            reconcile_last_error="AWAITING_FULFILLMENT",
        )
        return True

    async def release_reconciliation(
        self,
        operation_id: int,
        *,
        token_hash: str,
        retry_after: timedelta,
        error_code: str,
    ) -> bool:
        if not self._owns(operation_id, token_hash):
            return False
        self.record = replace(
            self.record,
            reconcile_token_hash=None,
            reconcile_lease_expires_at=None,
            reconcile_next_attempt_at=datetime_now() + retry_after,
            reconcile_last_error=error_code,
        )
        return True

    def _owns(self, operation_id: int, token_hash: str) -> bool:
        return (
            operation_id == self.record.id
            and self.record.status == PaymentOperationStatus.UNKNOWN
            and self.record.reconcile_token_hash == token_hash
        )

    async def expire_reconciliations(self, *, limit: int) -> int:
        return 0

    async def claim_manual_reconciliation_alerts(
        self,
        *,
        token_hash: str,
        lease_for: timedelta,
        limit: int,
    ) -> list[PaymentOperationRecord]:
        if (
            not self.deleted
            and self.record.status == PaymentOperationStatus.MANUAL_REQUIRED
            and self.record.reconcile_alerted_at is None
        ):
            self.record = replace(
                self.record,
                reconcile_alert_token_hash=token_hash,
                reconcile_alert_lease_expires_at=datetime_now() + lease_for,
                reconcile_alert_attempt_count=(
                    self.record.reconcile_alert_attempt_count + 1
                ),
            )
            return [self.record]
        return []

    async def mark_reconciliation_alerted(
        self,
        operation_id: int,
        *,
        token_hash: str,
    ) -> bool:
        if (
            operation_id != self.record.id
            or self.record.status != PaymentOperationStatus.MANUAL_REQUIRED
            or self.record.reconcile_alerted_at is not None
            or self.record.reconcile_alert_token_hash != token_hash
        ):
            return False
        self.record = replace(
            self.record,
            reconcile_alerted_at=datetime_now(),
            reconcile_alert_token_hash=None,
            reconcile_alert_lease_expires_at=None,
        )
        return True

    async def release_reconciliation_alert(
        self,
        operation_id: int,
        *,
        token_hash: str,
        retry_after: timedelta,
    ) -> bool:
        if (
            operation_id != self.record.id
            or self.record.reconcile_alert_token_hash != token_hash
        ):
            return False
        self.record = replace(
            self.record,
            reconcile_alert_token_hash=None,
            reconcile_alert_lease_expires_at=None,
        )
        return True


class FakeTransactionDao:
    def __init__(self, transactions: Optional[list[TransactionDto]] = None) -> None:
        self.transactions = {item.payment_id: item for item in transactions or []}
        self.create_calls = 0
        self.events: list[tuple[UUID, PaymentGatewayType, TransactionStatus]] = []

    async def get_by_internal_id_for_user(
        self,
        user_id: int,
        transaction_id: int,
    ) -> Optional[TransactionDto]:
        return next(
            (
                item
                for item in self.transactions.values()
                if item.id == transaction_id and item.user_id == user_id
            ),
            None,
        )

    async def get_by_payment_id(self, payment_id: UUID) -> Optional[TransactionDto]:
        return self.transactions.get(payment_id)

    async def create(self, transaction: TransactionDto) -> TransactionDto:
        self.create_calls += 1
        now = datetime_now()
        created = replace(
            transaction,
            id=100 + self.create_calls,
            created_at=now,
            updated_at=now,
        )
        self.transactions[created.payment_id] = created
        return created

    async def store_webhook_event(
        self,
        *,
        payment_id: UUID,
        gateway_type: PaymentGatewayType,
        status: TransactionStatus,
    ) -> None:
        event = (payment_id, gateway_type, status)
        if event not in self.events:
            self.events.append(event)

    async def cancel_by_provider(self, payment_id: UUID) -> Optional[TransactionDto]:
        current = self.transactions.get(payment_id)
        if (
            current is None
            or current.status not in {TransactionStatus.PENDING, TransactionStatus.CANCELED}
            or current.fulfillment_status != TransactionFulfillmentStatus.NOT_STARTED
        ):
            return None
        canceled = replace(
            current,
            status=TransactionStatus.CANCELED,
            cancellation_reason="PROVIDER",
        )
        self.transactions[payment_id] = canceled
        return canceled


class FakeGateway:
    def __init__(self, owner_hash: str) -> None:
        self.owner_hash = owner_hash
        self.provider_status = "pending"
        self.create_calls = 0
        self.verify_calls = 0

    def payment_owner_fingerprint(self) -> str:
        return self.owner_hash

    async def create_payment_from_request(
        self,
        request: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> PaymentResultDto:
        self.create_calls += 1
        await asyncio.sleep(0)
        return PaymentResultDto(
            id=UUID("00000000-0000-0000-0000-000000000777"),
            url="https://payments.example/777",
            provider_status=self.provider_status,
        )

    async def verify_payment_result(
        self,
        payment_id: UUID,
        request: dict[str, Any],
    ) -> PaymentResultDto:
        self.verify_calls += 1
        return PaymentResultDto(
            id=payment_id,
            url="https://payments.example/777",
            provider_status=self.provider_status,
        )


class FakeGatewayFactory:
    def __init__(self, gateway: FakeGateway) -> None:
        self.gateway = gateway

    async def system(self, gateway_type: PaymentGatewayType) -> FakeGateway:
        return self.gateway


def transaction(*, fulfilled: bool = False, is_free: bool = False) -> TransactionDto:
    now = datetime_now()
    return TransactionDto(
        id=21,
        payment_id=UUID("00000000-0000-0000-0000-000000000777"),
        user_id=7,
        status=TransactionStatus.COMPLETED if fulfilled else TransactionStatus.PENDING,
        purchase_type=PurchaseType.NEW,
        gateway_type=PaymentGatewayType.YOOKASSA,
        pricing=PriceDetailsDto(
            original_amount=Decimal("0" if is_free else "100"),
            discount_percent=0,
            final_amount=Decimal("0" if is_free else "100"),
        ),
        currency=Currency.RUB,
        plan_snapshot=PlanSnapshotDto(
            id=1,
            name="Basic",
            type=PlanType.UNLIMITED,
            traffic_limit_strategy=TrafficLimitStrategy.NO_RESET,
            traffic_limit=0,
            device_limit=1,
            duration=30,
        ),
        fulfillment_status=(
            TransactionFulfillmentStatus.SUCCEEDED
            if fulfilled
            else TransactionFulfillmentStatus.NOT_STARTED
        ),
        fulfillment_started_at=now if fulfilled else None,
        fulfillment_completed_at=now if fulfilled else None,
        created_at=now,
        updated_at=now,
    )


def test_payment_recovery_serializers_accept_legacy_dao_enum_strings() -> None:
    current = transaction()
    legacy_plan = replace(
        current.plan_snapshot,
        type=cast(Any, current.plan_snapshot.type.value),
        traffic_limit_strategy=cast(
            Any,
            current.plan_snapshot.traffic_limit_strategy.value,
        ),
    )
    legacy = replace(
        current,
        status=cast(Any, current.status.value),
        purchase_type=cast(Any, current.purchase_type.value),
        gateway_type=cast(Any, current.gateway_type.value),
        currency=cast(Any, current.currency.value),
        plan_snapshot=legacy_plan,
    )

    snapshot = build_resolved_payment_snapshot(legacy)
    response = build_payment_response(legacy, payment_url="https://payments.example/777")

    assert snapshot["purchase_type"] == PurchaseType.NEW.value
    assert snapshot["gateway_type"] == PaymentGatewayType.YOOKASSA.value
    assert snapshot["currency"] == Currency.RUB.value
    assert snapshot["plan"]["type"] == PlanType.UNLIMITED.value
    assert response == {
        "payment_id": "00000000-0000-0000-0000-000000000777",
        "payment_url": "https://payments.example/777",
        "purchase_type": PurchaseType.NEW.value,
        "status": TransactionStatus.PENDING.value,
        "is_free": False,
        "final_amount": "100",
        "currency": Currency.RUB.symbol,
    }


def operation_record(
    *,
    recovery_mode: PaymentOperationRecoveryMode,
    transaction_id: Optional[int] = None,
    provider_result: Optional[dict[str, Any]] = None,
    replay_in: timedelta = timedelta(hours=23),
) -> PaymentOperationRecord:
    template = transaction()
    now = datetime_now()
    return PaymentOperationRecord(
        id=9,
        user_id=7,
        operation="PURCHASE",
        idempotency_key="request-key-reconcile-0001",
        request_hash="a" * 64,
        status=PaymentOperationStatus.UNKNOWN,
        provider_key="00000000-0000-0000-0000-000000000999",
        response=None,
        lease_expires_at=None,
        transaction_id=transaction_id,
        gateway_type=PaymentGatewayType.YOOKASSA.value,
        resolved_payment_snapshot=build_resolved_payment_snapshot(template),
        provider_request_snapshot={
            "amount": {"value": "100", "currency": "RUB"},
            "confirmation": {
                "type": "redirect",
                "return_url": "https://shop.example/payment/return",
            },
            "capture": True,
            "description": "Basic plan for 30 days",
            "receipt": {
                "customer": {"email": "billing@example.test"},
                "items": [
                    {
                        "description": "Basic plan for 30 days",
                        "quantity": "1.00",
                        "amount": {"value": "100", "currency": "RUB"},
                        "vat_code": 1,
                        "payment_subject": "service",
                        "payment_mode": "full_payment",
                    }
                ],
            },
            "metadata": {"remnashop_operation_id": "9"},
        },
        provider_owner_hash="b" * 64,
        provider_result_snapshot=provider_result,
        recovery_mode=recovery_mode,
        provider_replay_expires_at=now + replay_in,
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
        created_at=now,
        updated_at=now,
    )


def service(
    record: PaymentOperationRecord,
    *,
    transactions: Optional[list[TransactionDto]] = None,
    gateway_owner_hash: str = "b" * 64,
) -> tuple[
    PaymentReconciliationService,
    FakeOperationDao,
    FakeTransactionDao,
    FakeGateway,
]:
    operation_dao = FakeOperationDao(record)
    transaction_dao = FakeTransactionDao(transactions)
    gateway = FakeGateway(gateway_owner_hash)
    gateway_dao = SimpleNamespace(
        get_by_type=lambda gateway_type: asyncio.sleep(
            0,
            result=SimpleNamespace(is_active=True),
        )
    )
    reconciliation = PaymentReconciliationService(
        FakeUnitOfWork(),  # type: ignore[arg-type]
        operation_dao,  # type: ignore[arg-type]
        transaction_dao,  # type: ignore[arg-type]
        gateway_dao,  # type: ignore[arg-type]
        FakeGatewayFactory(gateway),  # type: ignore[arg-type]
    )
    return reconciliation, operation_dao, transaction_dao, gateway


@pytest.mark.asyncio
async def test_unsupported_gateway_never_replays_and_becomes_manual() -> None:
    record = replace(
        operation_record(recovery_mode=PaymentOperationRecoveryMode.MANUAL_REQUIRED),
        gateway_type=PaymentGatewayType.PAYMASTER.value,
    )
    reconciliation, operation_dao, _, gateway = service(record)

    view = await reconciliation.reconcile(
        user_id=7,
        operation="PURCHASE",
        idempotency_key=record.idempotency_key,
    )

    assert view.state == PaymentOperationPublicState.MANUAL_REQUIRED
    assert view.payment is None
    assert view.transaction is None
    assert operation_dao.record.status == PaymentOperationStatus.MANUAL_REQUIRED
    assert gateway.create_calls == 0


@pytest.mark.asyncio
async def test_local_link_without_fulfillment_proof_is_in_progress() -> None:
    local_transaction = transaction(fulfilled=False)
    record = replace(
        operation_record(
            recovery_mode=PaymentOperationRecoveryMode.LOCAL,
            transaction_id=local_transaction.id,
        ),
        provider_request_snapshot={
            "version": 1,
            "kind": "LOCAL",
            "payment_id": str(local_transaction.payment_id),
        },
    )
    reconciliation, operation_dao, transaction_dao, _ = service(
        record,
        transactions=[local_transaction],
    )

    view = await reconciliation.reconcile(
        user_id=7,
        operation="PURCHASE",
        idempotency_key=record.idempotency_key,
    )

    assert view.state == PaymentOperationPublicState.IN_PROGRESS
    assert operation_dao.record.reconcile_last_error == "AWAITING_FULFILLMENT"
    assert transaction_dao.events == [
        (
            local_transaction.payment_id,
            local_transaction.gateway_type,
            TransactionStatus.COMPLETED,
        )
    ]
    assert transaction_dao.create_calls == 0


@pytest.mark.asyncio
async def test_local_link_with_fulfillment_proof_completes_without_side_effect() -> None:
    local_transaction = transaction(fulfilled=True)
    record = replace(
        operation_record(
            recovery_mode=PaymentOperationRecoveryMode.LOCAL,
            transaction_id=local_transaction.id,
        ),
        provider_result_snapshot={
            "version": 1,
            "payment_id": str(local_transaction.payment_id),
            "payment_url": None,
            "provider_status": "LOCAL",
        },
    )
    reconciliation, operation_dao, _, gateway = service(
        record,
        transactions=[local_transaction],
    )

    view = await reconciliation.reconcile(
        user_id=7,
        operation="PURCHASE",
        idempotency_key=record.idempotency_key,
    )

    assert view.state == PaymentOperationPublicState.SUCCEEDED
    assert view.payment is not None
    assert view.payment["currency"] == Currency.RUB.symbol
    assert operation_dao.record.status == PaymentOperationStatus.SUCCEEDED
    assert gateway.create_calls == 0


@pytest.mark.asyncio
async def test_local_crash_before_transaction_is_replayed_once() -> None:
    payment_id = UUID("00000000-0000-0000-0000-000000000777")
    checkpointed_result = {
        "version": 1,
        "payment_id": str(payment_id),
        "payment_url": None,
        "provider_status": "LOCAL",
    }
    record = replace(
        operation_record(
            recovery_mode=PaymentOperationRecoveryMode.LOCAL,
            provider_result=checkpointed_result,
        ),
        provider_request_snapshot={
            "version": 1,
            "kind": "LOCAL",
            "payment_id": str(payment_id),
        },
    )
    reconciliation, operation_dao, transaction_dao, _ = service(record)

    view = await reconciliation.reconcile(
        user_id=7,
        operation="PURCHASE",
        idempotency_key=record.idempotency_key,
    )

    assert view.state == PaymentOperationPublicState.IN_PROGRESS
    assert transaction_dao.create_calls == 1
    assert operation_dao.record.transaction_id == 101
    assert operation_dao.record.reconcile_last_error == "AWAITING_FULFILLMENT"
    assert len(transaction_dao.events) == 1


@pytest.mark.asyncio
async def test_live_processing_lease_remains_in_progress() -> None:
    record = replace(
        operation_record(recovery_mode=PaymentOperationRecoveryMode.MANUAL_REQUIRED),
        status=PaymentOperationStatus.PROCESSING,
        lease_expires_at=datetime_now() + timedelta(minutes=1),
    )
    reconciliation, operation_dao, _, _ = service(record)

    view = await reconciliation.reconcile(
        user_id=7,
        operation="PURCHASE",
        idempotency_key=record.idempotency_key,
    )

    assert view.state == PaymentOperationPublicState.IN_PROGRESS
    assert operation_dao.record.status == PaymentOperationStatus.PROCESSING
    assert operation_dao.record.reconcile_attempt_count == 0


@pytest.mark.asyncio
async def test_live_claim_lease_remains_in_progress() -> None:
    record = replace(
        operation_record(recovery_mode=PaymentOperationRecoveryMode.MANUAL_REQUIRED),
        status=PaymentOperationStatus.CLAIMED,
        lease_expires_at=datetime_now() + timedelta(minutes=1),
    )
    reconciliation, operation_dao, _, _ = service(record)

    view = await reconciliation.reconcile(
        user_id=7,
        operation="PURCHASE",
        idempotency_key=record.idempotency_key,
    )

    assert view.state == PaymentOperationPublicState.IN_PROGRESS
    assert operation_dao.record.status == PaymentOperationStatus.CLAIMED


@pytest.mark.asyncio
async def test_expired_claim_is_deleted_and_returns_not_found_without_provider_call() -> None:
    record = replace(
        operation_record(recovery_mode=PaymentOperationRecoveryMode.MANUAL_REQUIRED),
        status=PaymentOperationStatus.CLAIMED,
        lease_expires_at=datetime_now() - timedelta(seconds=1),
    )
    reconciliation, operation_dao, _, gateway = service(record)

    with pytest.raises(PaymentOperationNotFoundError):
        await reconciliation.reconcile(
            user_id=7,
            operation="PURCHASE",
            idempotency_key=record.idempotency_key,
        )

    assert operation_dao.deleted is True
    assert gateway.create_calls == 0


@pytest.mark.asyncio
async def test_expired_processing_lease_transitions_to_reconciliation() -> None:
    record = replace(
        operation_record(recovery_mode=PaymentOperationRecoveryMode.MANUAL_REQUIRED),
        status=PaymentOperationStatus.PROCESSING,
        lease_expires_at=datetime_now() - timedelta(seconds=1),
    )
    reconciliation, operation_dao, _, gateway = service(record)

    view = await reconciliation.reconcile(
        user_id=7,
        operation="PURCHASE",
        idempotency_key=record.idempotency_key,
    )

    assert view.state == PaymentOperationPublicState.MANUAL_REQUIRED
    assert operation_dao.record.reconcile_attempt_count == 1
    assert gateway.create_calls == 0


@pytest.mark.asyncio
async def test_yookassa_replay_after_deadline_is_manual_without_provider_call() -> None:
    record = operation_record(
        recovery_mode=PaymentOperationRecoveryMode.YOOKASSA_REPLAY,
        replay_in=timedelta(seconds=-1),
    )
    reconciliation, _, _, gateway = service(record)

    view = await reconciliation.reconcile(
        user_id=7,
        operation="PURCHASE",
        idempotency_key=record.idempotency_key,
    )

    assert view.state == PaymentOperationPublicState.MANUAL_REQUIRED
    assert gateway.create_calls == 0
    assert gateway.verify_calls == 0


@pytest.mark.asyncio
async def test_yookassa_replay_rejects_tampered_request_before_provider_call() -> None:
    record = operation_record(
        recovery_mode=PaymentOperationRecoveryMode.YOOKASSA_REPLAY,
    )
    assert record.provider_request_snapshot is not None
    record = replace(
        record,
        provider_request_snapshot={
            **record.provider_request_snapshot,
            "amount": {"value": "1000", "currency": "RUB"},
        },
    )
    reconciliation, operation_dao, _, gateway = service(record)

    view = await reconciliation.reconcile(
        user_id=7,
        operation="PURCHASE",
        idempotency_key=record.idempotency_key,
    )

    assert view.state == PaymentOperationPublicState.MANUAL_REQUIRED
    assert operation_dao.record.reconcile_last_error == "MANUAL_REQUIRED"
    assert gateway.create_calls == 0
    assert gateway.verify_calls == 0


@pytest.mark.asyncio
async def test_reconciliation_attempt_budget_is_terminal_before_new_claim() -> None:
    record = replace(
        operation_record(
            recovery_mode=PaymentOperationRecoveryMode.MANUAL_REQUIRED,
        ),
        reconcile_attempt_count=MAX_RECONCILIATION_ATTEMPTS,
    )
    reconciliation, operation_dao, _, gateway = service(record)

    view = await reconciliation.reconcile(
        user_id=7,
        operation="PURCHASE",
        idempotency_key=record.idempotency_key,
    )

    assert view.state == PaymentOperationPublicState.MANUAL_REQUIRED
    assert operation_dao.record.reconcile_last_error == (
        "RECONCILIATION_RETRIES_EXHAUSTED"
    )
    assert operation_dao.record.reconcile_attempt_count == MAX_RECONCILIATION_ATTEMPTS
    assert gateway.create_calls == 0
    assert gateway.verify_calls == 0


@pytest.mark.asyncio
async def test_checkpointed_yookassa_result_is_verified_and_recovers_transaction() -> None:
    result = {
        "version": 1,
        "payment_id": "00000000-0000-0000-0000-000000000777",
        "payment_url": "https://payments.example/777",
        "provider_status": "pending",
    }
    record = operation_record(
        recovery_mode=PaymentOperationRecoveryMode.YOOKASSA_REPLAY,
        provider_result=result,
    )
    reconciliation, operation_dao, transaction_dao, gateway = service(record)

    view = await reconciliation.reconcile(
        user_id=7,
        operation="PURCHASE",
        idempotency_key=record.idempotency_key,
    )

    assert view.state == PaymentOperationPublicState.SUCCEEDED
    assert operation_dao.record.transaction_id == 101
    assert transaction_dao.create_calls == 1
    assert gateway.verify_calls == 1
    assert gateway.create_calls == 0


@pytest.mark.asyncio
async def test_provider_succeeded_creates_durable_fulfillment_and_completes_invoice() -> None:
    result = {
        "version": 1,
        "payment_id": "00000000-0000-0000-0000-000000000777",
        "payment_url": None,
        "provider_status": "succeeded",
    }
    record = operation_record(
        recovery_mode=PaymentOperationRecoveryMode.YOOKASSA_REPLAY,
        provider_result=result,
    )
    reconciliation, operation_dao, transaction_dao, gateway = service(record)
    gateway.provider_status = "succeeded"

    view = await reconciliation.reconcile(
        user_id=7,
        operation="PURCHASE",
        idempotency_key=record.idempotency_key,
    )

    recovered = next(iter(transaction_dao.transactions.values()))
    assert view.state == PaymentOperationPublicState.SUCCEEDED
    assert view.payment is not None
    assert recovered.status == TransactionStatus.PENDING
    assert recovered.fulfillment_completed_at is None
    assert operation_dao.record.status == PaymentOperationStatus.SUCCEEDED
    assert operation_dao.record.provider_result_snapshot is not None
    assert operation_dao.record.provider_result_snapshot["provider_status"] == "succeeded"
    assert operation_dao.record.provider_result_snapshot["payment_url"] == (
        "https://payments.example/777"
    )
    assert len(transaction_dao.events) == 1
    assert gateway.verify_calls == 1


@pytest.mark.asyncio
async def test_provider_canceled_checkpoint_is_materialized_exactly() -> None:
    result = {
        "version": 1,
        "payment_id": "00000000-0000-0000-0000-000000000777",
        "payment_url": "https://payments.example/777",
        "provider_status": "pending",
    }
    record = operation_record(
        recovery_mode=PaymentOperationRecoveryMode.YOOKASSA_REPLAY,
        provider_result=result,
    )
    reconciliation, operation_dao, transaction_dao, gateway = service(record)
    gateway.provider_status = "canceled"

    view = await reconciliation.reconcile(
        user_id=7,
        operation="PURCHASE",
        idempotency_key=record.idempotency_key,
    )

    recovered = next(iter(transaction_dao.transactions.values()))
    assert view.state == PaymentOperationPublicState.SUCCEEDED
    assert recovered.status == TransactionStatus.CANCELED
    assert recovered.cancellation_reason == "PROVIDER"
    assert transaction_dao.events == []
    assert operation_dao.record.status == PaymentOperationStatus.SUCCEEDED
    assert operation_dao.record.provider_result_snapshot is not None
    assert operation_dao.record.provider_result_snapshot["provider_status"] == "canceled"
    assert gateway.verify_calls == 1


@pytest.mark.asyncio
async def test_yookassa_owner_change_is_manual() -> None:
    result = {
        "version": 1,
        "payment_id": "00000000-0000-0000-0000-000000000777",
        "payment_url": "https://payments.example/777",
        "provider_status": "pending",
    }
    record = operation_record(
        recovery_mode=PaymentOperationRecoveryMode.YOOKASSA_REPLAY,
        provider_result=result,
    )
    reconciliation, _, _, gateway = service(record, gateway_owner_hash="c" * 64)

    view = await reconciliation.reconcile(
        user_id=7,
        operation="PURCHASE",
        idempotency_key=record.idempotency_key,
    )

    assert view.state == PaymentOperationPublicState.MANUAL_REQUIRED


@pytest.mark.asyncio
async def test_paid_success_replay_is_stable_when_later_fulfillment_is_manual() -> None:
    now = datetime_now()
    paid = replace(
        transaction(),
        status=TransactionStatus.COMPLETED,
        fulfillment_status=TransactionFulfillmentStatus.MANUAL_REQUIRED,
        fulfillment_started_at=now,
        fulfillment_last_error="FULFILLMENT_SIDE_EFFECT_FAILED",
    )
    record = replace(
        operation_record(
            recovery_mode=PaymentOperationRecoveryMode.MANUAL_REQUIRED,
            transaction_id=paid.id,
        ),
        status=PaymentOperationStatus.SUCCEEDED,
        response=build_payment_response(paid, payment_url="https://payments.example/777"),
    )
    reconciliation, _, _, _ = service(record, transactions=[paid])

    view = await reconciliation.lookup(
        user_id=record.user_id,
        operation=record.operation,
        idempotency_key=record.idempotency_key,
    )

    assert view.state == PaymentOperationPublicState.SUCCEEDED
    assert view.payment is not None
    assert view.transaction == paid


@pytest.mark.asyncio
async def test_legacy_free_success_without_fulfillment_proof_is_manual() -> None:
    now = datetime_now()
    free = replace(
        transaction(is_free=True),
        status=TransactionStatus.COMPLETED,
        fulfillment_status=TransactionFulfillmentStatus.MANUAL_REQUIRED,
        fulfillment_started_at=now,
        fulfillment_last_error="LEGACY_WORKER_UNFENCED_TERMINAL",
    )
    record = replace(
        operation_record(
            recovery_mode=PaymentOperationRecoveryMode.MANUAL_REQUIRED,
            transaction_id=free.id,
        ),
        status=PaymentOperationStatus.SUCCEEDED,
        response=build_payment_response(free, payment_url=None),
    )
    reconciliation, _, _, _ = service(record, transactions=[free])

    view = await reconciliation.lookup(
        user_id=record.user_id,
        operation=record.operation,
        idempotency_key=record.idempotency_key,
    )

    assert view.state == PaymentOperationPublicState.MANUAL_REQUIRED
    assert view.payment is None


@pytest.mark.asyncio
async def test_legacy_free_success_with_fulfillment_proof_is_stable() -> None:
    free = transaction(fulfilled=True, is_free=True)
    record = replace(
        operation_record(
            recovery_mode=PaymentOperationRecoveryMode.MANUAL_REQUIRED,
            transaction_id=free.id,
        ),
        status=PaymentOperationStatus.SUCCEEDED,
        response=build_payment_response(free, payment_url=None),
    )
    reconciliation, _, _, _ = service(record, transactions=[free])

    view = await reconciliation.lookup(
        user_id=record.user_id,
        operation=record.operation,
        idempotency_key=record.idempotency_key,
    )

    assert view.state == PaymentOperationPublicState.SUCCEEDED


@pytest.mark.asyncio
async def test_manual_operation_alert_retries_and_marks_only_after_delivery() -> None:
    record = replace(
        operation_record(recovery_mode=PaymentOperationRecoveryMode.MANUAL_REQUIRED),
        status=PaymentOperationStatus.MANUAL_REQUIRED,
    )
    operation_dao = FakeOperationDao(record)
    user = SimpleNamespace(
        telegram_id=None,
        username=None,
        name="User",
        email=None,
    )

    class FlakyNotifier:
        def __init__(self) -> None:
            self.calls = 0

        async def notify_system(self, *args: Any, **kwargs: Any) -> None:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("notification transport unavailable")

    notifier = FlakyNotifier()
    sweep = SweepPaymentOperationAlerts(
        FakeUnitOfWork(),  # type: ignore[arg-type]
        operation_dao,  # type: ignore[arg-type]
        SimpleNamespace(get_by_id=AsyncMock(return_value=user)),  # type: ignore[arg-type]
        notifier,  # type: ignore[arg-type]
    )

    await sweep._execute(SimpleNamespace(), None)
    assert operation_dao.record.reconcile_alerted_at is None

    await sweep._execute(SimpleNamespace(), None)
    assert notifier.calls == 2
    assert operation_dao.record.reconcile_alerted_at is not None


@pytest.mark.asyncio
async def test_two_reconcilers_have_one_provider_replay_winner() -> None:
    record = operation_record(recovery_mode=PaymentOperationRecoveryMode.YOOKASSA_REPLAY)
    first, operation_dao, transaction_dao, gateway = service(record)
    second = PaymentReconciliationService(
        FakeUnitOfWork(),  # type: ignore[arg-type]
        operation_dao,  # type: ignore[arg-type]
        transaction_dao,  # type: ignore[arg-type]
        first.payment_gateway_dao,
        first.get_payment_gateway_instance,
    )

    await asyncio.gather(
        first.reconcile(
            user_id=7,
            operation="PURCHASE",
            idempotency_key=record.idempotency_key,
        ),
        second.reconcile(
            user_id=7,
            operation="PURCHASE",
            idempotency_key=record.idempotency_key,
        ),
    )

    assert gateway.create_calls == 1
    assert gateway.verify_calls == 1
    assert transaction_dao.create_calls == 1
    assert operation_dao.record.status == PaymentOperationStatus.SUCCEEDED
