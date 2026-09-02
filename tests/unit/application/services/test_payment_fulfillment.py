import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from remnapy.enums.users import TrafficLimitStrategy

from src.application.dto import (
    PaymentWebhookEventDto,
    PlanSnapshotDto,
    PriceDetailsDto,
    TransactionDto,
)
from src.application.use_cases.gateways.commands.payment import (
    PaymentEventNotAppliedError,
    PaymentTransactionNotReadyError,
    ProcessPayment,
    ProcessPaymentDto,
)
from src.application.use_cases.misc.commands.maintenance import (
    ReplayPendingPaymentWebhooks,
    SweepPaymentFulfillments,
)
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


class FakeTransactionDao:
    def __init__(self, transaction: Optional[TransactionDto]) -> None:
        self.transaction = transaction
        self.events: list[PaymentWebhookEventDto] = []

    async def get_by_payment_id(self, payment_id: UUID) -> Optional[TransactionDto]:
        if self.transaction and self.transaction.payment_id == payment_id:
            return self.transaction
        return None

    async def set_payment_method_if_absent_or_equal(
        self,
        payment_id: UUID,
        *,
        payment_method: str,
    ) -> bool:
        transaction = await self.get_by_payment_id(payment_id)
        if (
            transaction is None
            or transaction.gateway_type != PaymentGatewayType.PLATEGA
            or transaction.payment_method not in {None, payment_method}
        ):
            return False
        self.transaction = replace(transaction, payment_method=payment_method)
        return True

    async def claim_fulfillment(
        self,
        payment_id: UUID,
        *,
        token_hash: str,
        lease_for: timedelta,
    ) -> Optional[TransactionDto]:
        transaction = await self.get_by_payment_id(payment_id)
        if transaction is None or transaction.fulfillment_status != (
            TransactionFulfillmentStatus.NOT_STARTED
        ):
            return None
        claimable = transaction.status == TransactionStatus.PENDING or (
            transaction.status == TransactionStatus.CANCELED
            and transaction.cancellation_reason == "LOCAL_TIMEOUT"
        )
        if not claimable:
            return None
        now = datetime_now()
        self.transaction = replace(
            transaction,
            status=TransactionStatus.COMPLETED,
            cancellation_reason=None,
            fulfillment_status=TransactionFulfillmentStatus.PROCESSING,
            fulfillment_token_hash=token_hash,
            fulfillment_started_at=now,
            fulfillment_lease_expires_at=now + lease_for,
            fulfillment_last_error=None,
        )
        self.token_hash = token_hash
        return self.transaction

    async def complete_fulfillment(self, payment_id: UUID, *, token_hash: str) -> bool:
        transaction = await self.get_by_payment_id(payment_id)
        if (
            transaction is None
            or transaction.status != TransactionStatus.COMPLETED
            or transaction.fulfillment_status != TransactionFulfillmentStatus.PROCESSING
            or transaction.fulfillment_token_hash != token_hash
            or transaction.fulfillment_lease_expires_at is None
            or transaction.fulfillment_lease_expires_at <= datetime_now()
        ):
            return False
        self.transaction = replace(
            transaction,
            fulfillment_status=TransactionFulfillmentStatus.SUCCEEDED,
            fulfillment_token_hash=None,
            fulfillment_lease_expires_at=None,
            fulfillment_completed_at=datetime_now(),
            fulfillment_last_error=None,
        )
        return True

    async def mark_fulfillment_manual_required(
        self,
        payment_id: UUID,
        *,
        token_hash: str,
        error_code: str,
    ) -> bool:
        transaction = await self.get_by_payment_id(payment_id)
        if (
            transaction is None
            or transaction.status
            not in {TransactionStatus.COMPLETED, TransactionStatus.REFUNDED}
            or transaction.fulfillment_status
            not in {
                TransactionFulfillmentStatus.PROCESSING,
                TransactionFulfillmentStatus.MANUAL_REQUIRED,
            }
            or transaction.fulfillment_token_hash != token_hash
        ):
            return False
        self.transaction = replace(
            transaction,
            fulfillment_status=TransactionFulfillmentStatus.MANUAL_REQUIRED,
            fulfillment_lease_expires_at=None,
            fulfillment_last_error=error_code,
        )
        return True

    async def expire_fulfillment(self, payment_id: UUID) -> bool:
        transaction = await self.get_by_payment_id(payment_id)
        if (
            transaction is None
            or transaction.status
            not in {TransactionStatus.COMPLETED, TransactionStatus.REFUNDED}
            or transaction.fulfillment_status != TransactionFulfillmentStatus.PROCESSING
            or transaction.fulfillment_lease_expires_at is None
            or transaction.fulfillment_lease_expires_at > datetime_now()
        ):
            return False
        self.transaction = replace(
            transaction,
            fulfillment_status=TransactionFulfillmentStatus.MANUAL_REQUIRED,
            fulfillment_lease_expires_at=None,
            fulfillment_last_error="FULFILLMENT_LEASE_EXPIRED",
        )
        return True

    async def expire_fulfillments(self, *, limit: int) -> int:
        if self.transaction is None:
            return 0
        return int(await self.expire_fulfillment(self.transaction.payment_id))

    async def claim_manual_fulfillment_alerts(
        self,
        *,
        token_hash: str,
        lease_for: timedelta,
        limit: int,
    ) -> list[TransactionDto]:
        if (
            self.transaction
            and self.transaction.fulfillment_status
            == TransactionFulfillmentStatus.MANUAL_REQUIRED
            and self.transaction.fulfillment_alerted_at is None
        ):
            self.fulfillment_alert_token_hash = token_hash
            return [self.transaction]
        return []

    async def mark_fulfillment_alerted(
        self,
        payment_id: UUID,
        *,
        token_hash: Optional[str] = None,
    ) -> bool:
        transaction = await self.get_by_payment_id(payment_id)
        if (
            transaction is None
            or transaction.fulfillment_alerted_at is not None
            or (
                token_hash is not None
                and token_hash != getattr(self, "fulfillment_alert_token_hash", None)
            )
        ):
            return False
        self.transaction = replace(transaction, fulfillment_alerted_at=datetime_now())
        return True

    async def release_fulfillment_alert(
        self,
        payment_id: UUID,
        *,
        token_hash: str,
        retry_after: timedelta,
    ) -> bool:
        if token_hash != getattr(self, "fulfillment_alert_token_hash", None):
            return False
        self.fulfillment_alert_token_hash = None
        return True

    async def cancel_by_provider(self, payment_id: UUID) -> Optional[TransactionDto]:
        transaction = await self.get_by_payment_id(payment_id)
        if (
            transaction is None
            or transaction.status not in {TransactionStatus.PENDING, TransactionStatus.CANCELED}
            or transaction.fulfillment_status != TransactionFulfillmentStatus.NOT_STARTED
        ):
            return None
        self.transaction = replace(
            transaction,
            status=TransactionStatus.CANCELED,
            cancellation_reason="PROVIDER",
        )
        return self.transaction

    async def transition_refunded(self, payment_id: UUID) -> Optional[TransactionDto]:
        transaction = await self.get_by_payment_id(payment_id)
        if transaction is None:
            return None
        unfulfilled = (
            transaction.status in {TransactionStatus.PENDING, TransactionStatus.CANCELED}
            and transaction.fulfillment_status == TransactionFulfillmentStatus.NOT_STARTED
        )
        fulfilled = (
            transaction.status == TransactionStatus.COMPLETED
            and transaction.fulfillment_status == TransactionFulfillmentStatus.SUCCEEDED
            and transaction.fulfillment_completed_at is not None
        )
        if not (unfulfilled or fulfilled):
            return None
        self.transaction = replace(
            transaction,
            status=TransactionStatus.REFUNDED,
            cancellation_reason=None,
        )
        return self.transaction

    async def mark_refund_manual_required(self, payment_id: UUID) -> bool:
        transaction = await self.get_by_payment_id(payment_id)
        if transaction is None or not (
            transaction.status == TransactionStatus.COMPLETED
            and transaction.fulfillment_status
            in {
                TransactionFulfillmentStatus.PROCESSING,
                TransactionFulfillmentStatus.MANUAL_REQUIRED,
            }
        ):
            return False
        self.transaction = replace(
            transaction,
            status=TransactionStatus.REFUNDED,
            fulfillment_last_error="REFUND_DURING_UNPROVEN_FULFILLMENT",
        )
        return True

    async def store_webhook_event(
        self,
        *,
        payment_id: UUID,
        gateway_type: PaymentGatewayType,
        status: TransactionStatus,
        selected_payment_method: Optional[str] = None,
        error_code: Optional[str] = None,
    ) -> None:
        if not self.events:
            now = datetime_now()
            self.events.append(
                PaymentWebhookEventDto(
                    id=1,
                    payment_id=payment_id,
                    gateway_type=gateway_type,
                    status=status,
                    selected_payment_method=selected_payment_method,
                    processing_token_hash=None,
                    processing_lease_expires_at=None,
                    processing_attempt_count=0,
                    processing_next_attempt_at=None,
                    processing_last_error=error_code,
                    manual_required_at=now if error_code else None,
                    alerted_at=None,
                    created_at=now,
                )
            )

    async def claim_webhook_event_by_identity(
        self,
        *,
        payment_id: UUID,
        gateway_type: PaymentGatewayType,
        status: TransactionStatus,
        token_hash: str,
        lease_for: timedelta,
    ) -> Optional[PaymentWebhookEventDto]:
        for index, event in enumerate(self.events):
            if (
                event.payment_id == payment_id
                and event.gateway_type == gateway_type
                and event.status == status
                and event.manual_required_at is None
                and event.processing_token_hash is None
            ):
                claimed = replace(
                    event,
                    processing_token_hash=token_hash,
                    processing_lease_expires_at=datetime_now() + lease_for,
                    processing_attempt_count=event.processing_attempt_count + 1,
                )
                self.events[index] = claimed
                return claimed
        return None

    async def claim_replayable_webhook_events(
        self,
        *,
        token_hash: str,
        lease_for: timedelta,
        limit: int,
    ) -> list[PaymentWebhookEventDto]:
        if self.transaction is None:
            return []
        claimed: list[PaymentWebhookEventDto] = []
        for index, event in enumerate(self.events):
            if (
                len(claimed) < limit
                and event.manual_required_at is None
                and event.processing_token_hash is None
            ):
                updated = replace(
                    event,
                    processing_token_hash=token_hash,
                    processing_lease_expires_at=datetime_now() + lease_for,
                    processing_attempt_count=event.processing_attempt_count + 1,
                )
                self.events[index] = updated
                claimed.append(updated)
        return claimed

    async def delete_webhook_event(self, event_id: int, *, token_hash: str) -> bool:
        before = len(self.events)
        self.events = [
            event
            for event in self.events
            if not (
                event.id == event_id
                and event.processing_token_hash == token_hash
                and event.manual_required_at is None
            )
        ]
        return len(self.events) != before

    async def release_webhook_event(
        self,
        event_id: int,
        *,
        token_hash: str,
        retry_after: timedelta,
        error_code: str,
        manual_required: bool,
    ) -> bool:
        for index, event in enumerate(self.events):
            if event.id == event_id and event.processing_token_hash == token_hash:
                self.events[index] = replace(
                    event,
                    processing_token_hash=None,
                    processing_lease_expires_at=None,
                    processing_last_error=error_code,
                    processing_next_attempt_at=datetime_now() + retry_after,
                    manual_required_at=(
                        event.manual_required_at or datetime_now()
                        if manual_required
                        else event.manual_required_at
                    ),
                )
                return True
        return False

    async def claim_manual_webhook_alerts(
        self,
        *,
        token_hash: str,
        lease_for: timedelta,
        limit: int,
    ) -> list[PaymentWebhookEventDto]:
        claimed: list[PaymentWebhookEventDto] = []
        for index, event in enumerate(self.events):
            if (
                len(claimed) < limit
                and event.manual_required_at is not None
                and event.alerted_at is None
                and event.processing_token_hash is None
            ):
                updated = replace(
                    event,
                    processing_token_hash=token_hash,
                    processing_lease_expires_at=datetime_now() + lease_for,
                )
                self.events[index] = updated
                claimed.append(updated)
        return claimed

    async def mark_webhook_alerted(self, event_id: int, *, token_hash: str) -> bool:
        for index, event in enumerate(self.events):
            if event.id == event_id and event.processing_token_hash == token_hash:
                self.events[index] = replace(
                    event,
                    processing_token_hash=None,
                    processing_lease_expires_at=None,
                    alerted_at=datetime_now(),
                )
                return True
        return False

    async def mark_expired_orphaned_webhook_events(
        self,
        **kwargs: Any,
    ) -> int:
        return 0


class FakeNotifier:
    def __init__(self) -> None:
        self.system_calls = 0
        self.admin_calls = 0
        self.fail_admin_calls = 0

    async def notify_system(self, *args: Any, **kwargs: Any) -> None:
        self.system_calls += 1

    async def notify_admins(self, *args: Any, **kwargs: Any) -> None:
        self.admin_calls += 1
        if self.fail_admin_calls:
            self.fail_admin_calls -= 1
            raise RuntimeError("notification transport unavailable")


def transaction(
    *,
    status: TransactionStatus = TransactionStatus.PENDING,
    cancellation_reason: Optional[str] = None,
) -> TransactionDto:
    return TransactionDto(
        id=1,
        payment_id=UUID("00000000-0000-0000-0000-000000000777"),
        user_id=7,
        status=status,
        cancellation_reason=cancellation_reason,
        purchase_type=PurchaseType.NEW,
        gateway_type=PaymentGatewayType.YOOKASSA,
        pricing=PriceDetailsDto(
            original_amount=Decimal("100"),
            discount_percent=0,
            final_amount=Decimal("100"),
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
    )


def process_payment(
    dao: FakeTransactionDao,
    notifier: FakeNotifier,
) -> ProcessPayment:
    user = SimpleNamespace(
        id=7,
        remna_name="user-7",
        log="user-7",
        telegram_id=None,
        username=None,
        name="User",
        email=None,
    )
    process = ProcessPayment(
        FakeUnitOfWork(),  # type: ignore[arg-type]
        SimpleNamespace(get_by_id=AsyncMock(return_value=user)),  # type: ignore[arg-type]
        dao,  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        notifier,  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
    )
    process._handle_success = AsyncMock()  # type: ignore[method-assign]
    return process


def completed_dto(payment_id: UUID) -> ProcessPaymentDto:
    return ProcessPaymentDto(
        payment_id=payment_id,
        new_transaction_status=TransactionStatus.COMPLETED,
        gateway_type=PaymentGatewayType.YOOKASSA,
    )


@pytest.mark.asyncio
async def test_concurrent_success_has_one_fulfillment_winner() -> None:
    dao = FakeTransactionDao(transaction())
    notifier = FakeNotifier()
    process = process_payment(dao, notifier)

    await asyncio.gather(
        process._execute(SimpleNamespace(), completed_dto(dao.transaction.payment_id)),
        process._execute(SimpleNamespace(), completed_dto(dao.transaction.payment_id)),
    )

    assert process._handle_success.await_count == 1  # type: ignore[attr-defined]
    assert dao.transaction.fulfillment_status == TransactionFulfillmentStatus.SUCCEEDED
    assert dao.transaction.fulfillment_completed_at is not None


@pytest.mark.asyncio
async def test_hard_crash_is_swept_to_manual_and_never_replayed() -> None:
    dao = FakeTransactionDao(transaction())
    notifier = FakeNotifier()
    process = process_payment(dao, notifier)
    process._handle_success = AsyncMock(side_effect=asyncio.CancelledError)  # type: ignore[method-assign]

    with pytest.raises(asyncio.CancelledError):
        await process._execute(SimpleNamespace(), completed_dto(dao.transaction.payment_id))

    assert dao.transaction.fulfillment_status == TransactionFulfillmentStatus.PROCESSING
    dao.transaction = replace(
        dao.transaction,
        fulfillment_lease_expires_at=datetime_now() - timedelta(seconds=1),
    )
    user = SimpleNamespace(
        id=7,
        telegram_id=None,
        username=None,
        name="User",
        email=None,
    )
    sweep = SweepPaymentFulfillments(
        FakeUnitOfWork(),  # type: ignore[arg-type]
        dao,  # type: ignore[arg-type]
        SimpleNamespace(get_by_id=AsyncMock(return_value=user)),  # type: ignore[arg-type]
        notifier,  # type: ignore[arg-type]
    )

    await sweep._execute(SimpleNamespace(), None)

    assert dao.transaction.fulfillment_status == TransactionFulfillmentStatus.MANUAL_REQUIRED
    assert dao.transaction.fulfillment_alerted_at is not None
    assert notifier.system_calls == 1


@pytest.mark.asyncio
async def test_success_returning_after_lease_stays_fenced_for_manual_review() -> None:
    dao = FakeTransactionDao(transaction())
    notifier = FakeNotifier()
    process = process_payment(dao, notifier)

    async def finish_after_lease(*args: Any, **kwargs: Any) -> None:
        assert dao.transaction is not None
        dao.transaction = replace(
            dao.transaction,
            fulfillment_lease_expires_at=datetime_now() - timedelta(seconds=1),
        )

    process._handle_success = AsyncMock(side_effect=finish_after_lease)  # type: ignore[method-assign]

    await process._execute(SimpleNamespace(), completed_dto(dao.transaction.payment_id))

    assert dao.transaction.fulfillment_status == TransactionFulfillmentStatus.MANUAL_REQUIRED
    assert dao.transaction.fulfillment_token_hash is not None
    assert dao.transaction.fulfillment_completed_at is None
    assert dao.transaction.fulfillment_last_error == "FULFILLMENT_RESULT_AFTER_LEASE"
    assert notifier.system_calls == 1


@pytest.mark.asyncio
async def test_local_timeout_can_accept_late_success_once() -> None:
    dao = FakeTransactionDao(
        transaction(
            status=TransactionStatus.CANCELED,
            cancellation_reason="LOCAL_TIMEOUT",
        )
    )
    process = process_payment(dao, FakeNotifier())

    await process._execute(SimpleNamespace(), completed_dto(dao.transaction.payment_id))
    await process._execute(SimpleNamespace(), completed_dto(dao.transaction.payment_id))

    assert process._handle_success.await_count == 1  # type: ignore[attr-defined]
    assert dao.transaction.status == TransactionStatus.COMPLETED
    assert dao.transaction.fulfillment_status == TransactionFulfillmentStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_provider_cancel_blocks_late_success() -> None:
    dao = FakeTransactionDao(
        transaction(
            status=TransactionStatus.CANCELED,
            cancellation_reason="PROVIDER",
        )
    )
    process = process_payment(dao, FakeNotifier())

    with pytest.raises(PaymentEventNotAppliedError):
        await process._execute(SimpleNamespace(), completed_dto(dao.transaction.payment_id))

    assert process._handle_success.await_count == 0  # type: ignore[attr-defined]
    assert dao.transaction.status == TransactionStatus.CANCELED


@pytest.mark.asyncio
async def test_provider_cancel_overrides_local_timeout_and_blocks_late_success() -> None:
    dao = FakeTransactionDao(
        transaction(
            status=TransactionStatus.CANCELED,
            cancellation_reason="LOCAL_TIMEOUT",
        )
    )
    process = process_payment(dao, FakeNotifier())

    await process._execute(
        SimpleNamespace(),
        ProcessPaymentDto(
            payment_id=dao.transaction.payment_id,
            new_transaction_status=TransactionStatus.CANCELED,
            gateway_type=PaymentGatewayType.YOOKASSA,
        ),
    )
    with pytest.raises(PaymentEventNotAppliedError):
        await process._execute(SimpleNamespace(), completed_dto(dao.transaction.payment_id))

    assert dao.transaction.status == TransactionStatus.CANCELED
    assert dao.transaction.cancellation_reason == "PROVIDER"
    assert process._handle_success.await_count == 0  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_refund_before_success_is_terminal_without_fulfillment() -> None:
    dao = FakeTransactionDao(transaction())
    process = process_payment(dao, FakeNotifier())

    await process._execute(
        SimpleNamespace(),
        ProcessPaymentDto(
            payment_id=dao.transaction.payment_id,
            new_transaction_status=TransactionStatus.REFUNDED,
            gateway_type=PaymentGatewayType.YOOKASSA,
        ),
    )

    assert dao.transaction.status == TransactionStatus.REFUNDED
    assert dao.transaction.fulfillment_status == TransactionFulfillmentStatus.NOT_STARTED
    assert process._handle_success.await_count == 0  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_platega_cross_status_method_conflict_preserves_refund_and_first_method() -> None:
    current = replace(
        transaction(),
        gateway_type=PaymentGatewayType.PLATEGA,
        payment_method="CARD-A",
    )
    dao = FakeTransactionDao(current)
    notifier = FakeNotifier()
    process = process_payment(dao, notifier)

    with pytest.raises(PaymentEventNotAppliedError):
        await process._execute(
            SimpleNamespace(),
            ProcessPaymentDto(
                payment_id=current.payment_id,
                new_transaction_status=TransactionStatus.REFUNDED,
                gateway_type=PaymentGatewayType.PLATEGA,
                selected_payment_method="CARD-B",
            ),
        )

    assert dao.transaction.status == TransactionStatus.REFUNDED
    assert dao.transaction.payment_method == "CARD-A"
    assert notifier.admin_calls == 1


@pytest.mark.asyncio
async def test_refund_during_fulfillment_retains_active_fence() -> None:
    current = transaction(status=TransactionStatus.COMPLETED)
    now = datetime_now()
    current = replace(
        current,
        fulfillment_status=TransactionFulfillmentStatus.PROCESSING,
        fulfillment_started_at=now,
        fulfillment_lease_expires_at=now + timedelta(minutes=5),
    )
    dao = FakeTransactionDao(current)
    notifier = FakeNotifier()
    process = process_payment(dao, notifier)

    await process._execute(
        SimpleNamespace(),
        ProcessPaymentDto(
            payment_id=current.payment_id,
            new_transaction_status=TransactionStatus.REFUNDED,
            gateway_type=PaymentGatewayType.YOOKASSA,
        ),
    )

    assert dao.transaction.status == TransactionStatus.REFUNDED
    assert dao.transaction.fulfillment_status == TransactionFulfillmentStatus.PROCESSING
    assert dao.transaction.fulfillment_lease_expires_at is not None
    assert notifier.admin_calls == 1


@pytest.mark.asyncio
async def test_refund_racing_slow_success_releases_fence_only_after_worker_exit() -> None:
    dao = FakeTransactionDao(transaction())
    notifier = FakeNotifier()
    process = process_payment(dao, notifier)
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_success(*args: Any, **kwargs: Any) -> None:
        started.set()
        await release.wait()

    process._handle_success = AsyncMock(side_effect=slow_success)  # type: ignore[method-assign]
    success = asyncio.create_task(
        process._execute(SimpleNamespace(), completed_dto(dao.transaction.payment_id))
    )
    await started.wait()

    await process._execute(
        SimpleNamespace(),
        ProcessPaymentDto(
            payment_id=dao.transaction.payment_id,
            new_transaction_status=TransactionStatus.REFUNDED,
            gateway_type=PaymentGatewayType.YOOKASSA,
        ),
    )
    assert dao.transaction.status == TransactionStatus.REFUNDED
    assert dao.transaction.fulfillment_status == TransactionFulfillmentStatus.PROCESSING
    assert dao.transaction.fulfillment_lease_expires_at is not None

    release.set()
    await success

    assert dao.transaction.fulfillment_status == TransactionFulfillmentStatus.MANUAL_REQUIRED
    assert dao.transaction.fulfillment_lease_expires_at is None
    assert dao.transaction.fulfillment_alerted_at is not None
    assert notifier.system_calls == 1


@pytest.mark.asyncio
async def test_early_success_webhook_is_replayed_after_transaction_exists() -> None:
    dao = FakeTransactionDao(None)
    notifier = FakeNotifier()
    process = process_payment(dao, notifier)
    payment_id = UUID("00000000-0000-0000-0000-000000000777")

    with pytest.raises(PaymentTransactionNotReadyError):
        await process._execute(SimpleNamespace(), completed_dto(payment_id))
    assert len(dao.events) == 1

    dao.transaction = transaction()
    replay = ReplayPendingPaymentWebhooks(
        FakeUnitOfWork(),  # type: ignore[arg-type]
        dao,  # type: ignore[arg-type]
        process,
        notifier,
    )
    await replay._execute(SimpleNamespace(), None)

    assert dao.events == []
    assert process._handle_success.await_count == 1  # type: ignore[attr-defined]
    assert dao.transaction.fulfillment_status == TransactionFulfillmentStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_refund_notification_failure_is_replayed_before_inbox_delete() -> None:
    dao = FakeTransactionDao(transaction())
    assert dao.transaction is not None
    payment_id = dao.transaction.payment_id
    await dao.store_webhook_event(
        payment_id=payment_id,
        gateway_type=PaymentGatewayType.YOOKASSA,
        status=TransactionStatus.REFUNDED,
    )
    notifier = FakeNotifier()
    notifier.fail_admin_calls = 1
    process = process_payment(dao, notifier)
    refund = ProcessPaymentDto(
        payment_id=payment_id,
        new_transaction_status=TransactionStatus.REFUNDED,
        gateway_type=PaymentGatewayType.YOOKASSA,
    )

    with pytest.raises(RuntimeError, match="notification transport unavailable"):
        await process._execute(SimpleNamespace(), refund)

    assert dao.transaction.status == TransactionStatus.REFUNDED
    assert len(dao.events) == 1

    replay = ReplayPendingPaymentWebhooks(
        FakeUnitOfWork(),  # type: ignore[arg-type]
        dao,  # type: ignore[arg-type]
        process,
        notifier,
    )
    await replay._execute(SimpleNamespace(), None)

    assert notifier.admin_calls == 2
    assert dao.events == []
