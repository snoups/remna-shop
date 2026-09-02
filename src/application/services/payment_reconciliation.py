import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Optional
from urllib.parse import urlparse
from uuid import UUID

from httpx import HTTPStatusError
from loguru import logger

from src.application.common.dao import PaymentGatewayDao, PaymentOperationDao, TransactionDao
from src.application.common.dao.payment_operation import (
    PaymentOperationRecord,
    PaymentOperationRecoveryMode,
    PaymentOperationStatus,
)
from src.application.common.uow import UnitOfWork
from src.application.dto import TransactionDto
from src.application.services.payment_recovery_snapshot import (
    InvalidPaymentRecoverySnapshotError,
    build_payment_response,
    transaction_from_resolved_snapshot,
)
from src.application.use_cases.gateways.queries.providers import GetPaymentGatewayInstance
from src.core.enums import (
    PaymentGatewayType,
    TransactionFulfillmentStatus,
    TransactionStatus,
)
from src.core.utils.time import datetime_now

RECONCILIATION_LEASE = timedelta(minutes=5)
MAX_RECONCILIATION_ATTEMPTS = 12
MIN_RETRY_SECONDS = 5
MAX_RETRY_SECONDS = 300


class PaymentOperationPublicState(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    IN_PROGRESS = "IN_PROGRESS"
    UNKNOWN = "UNKNOWN"
    MANUAL_REQUIRED = "MANUAL_REQUIRED"


@dataclass(frozen=True)
class PaymentOperationView:
    operation: str
    state: PaymentOperationPublicState
    payment: Optional[dict[str, Any]]
    transaction: Optional[TransactionDto]
    retry_after_seconds: Optional[int]


class PaymentOperationNotFoundError(Exception): ...


class PaymentFulfillmentInProgressError(Exception): ...


class PaymentReconciliationService:
    def __init__(
        self,
        uow: UnitOfWork,
        payment_operation_dao: PaymentOperationDao,
        transaction_dao: TransactionDao,
        payment_gateway_dao: PaymentGatewayDao,
        get_payment_gateway_instance: GetPaymentGatewayInstance,
    ) -> None:
        self.uow = uow
        self.payment_operation_dao = payment_operation_dao
        self.transaction_dao = transaction_dao
        self.payment_gateway_dao = payment_gateway_dao
        self.get_payment_gateway_instance = get_payment_gateway_instance

    async def _owned_record(
        self,
        *,
        user_id: int,
        operation: str,
        idempotency_key: str,
    ) -> PaymentOperationRecord:
        record = await self.payment_operation_dao.get_by_identity(
            user_id=user_id,
            operation=operation,
            idempotency_key=idempotency_key,
        )
        if record is None:
            raise PaymentOperationNotFoundError
        return record

    async def _transaction_for_record(
        self,
        record: PaymentOperationRecord,
    ) -> Optional[TransactionDto]:
        if record.transaction_id is None:
            return None
        transaction = await self.transaction_dao.get_by_internal_id_for_user(
            record.user_id,
            record.transaction_id,
        )
        if transaction is None:
            raise RuntimeError("Linked payment transaction is unavailable")
        return transaction

    @staticmethod
    def _retry_after(record: PaymentOperationRecord) -> int:
        if record.reconcile_next_attempt_at is None:
            return MIN_RETRY_SECONDS
        return max(
            MIN_RETRY_SECONDS,
            min(
                MAX_RETRY_SECONDS,
                int((record.reconcile_next_attempt_at - datetime_now()).total_seconds()) + 1,
            ),
        )

    async def _view(  # noqa: C901
        self,
        record: PaymentOperationRecord,
    ) -> PaymentOperationView:
        if record.status == PaymentOperationStatus.SUCCEEDED:
            transaction = await self._transaction_for_record(record)
            payment = record.response
            if payment is None and transaction is not None:
                payment = build_payment_response(
                    transaction,
                    payment_url=self._payment_url(record.provider_result_snapshot),
                )
            requires_fulfillment_proof = (
                record.recovery_mode == PaymentOperationRecoveryMode.LOCAL
                or (transaction is not None and transaction.pricing.is_free)
            )
            if (
                requires_fulfillment_proof
                and
                transaction is not None
                and transaction.fulfillment_status
                == TransactionFulfillmentStatus.PROCESSING
            ):
                expired = await self.transaction_dao.expire_fulfillment(
                    transaction.payment_id
                )
                if expired:
                    logger.critical(
                        "Payment fulfillment expired without proof for transaction '{}'",
                        transaction.payment_id,
                    )
                    transaction = await self._transaction_for_record(record)
                else:
                    return PaymentOperationView(
                        operation=record.operation,
                        state=PaymentOperationPublicState.IN_PROGRESS,
                        payment=None,
                        transaction=None,
                        retry_after_seconds=2,
                    )
            fulfillment_invalid = (
                requires_fulfillment_proof
                and transaction is not None
                and (
                    transaction.fulfillment_status
                    != TransactionFulfillmentStatus.SUCCEEDED
                    or transaction.fulfillment_completed_at is None
                )
            )
            if payment is None or transaction is None or fulfillment_invalid:
                return PaymentOperationView(
                    operation=record.operation,
                    state=PaymentOperationPublicState.MANUAL_REQUIRED,
                    payment=None,
                    transaction=None,
                    retry_after_seconds=None,
                )
            return PaymentOperationView(
                operation=record.operation,
                state=PaymentOperationPublicState.SUCCEEDED,
                payment=payment,
                transaction=transaction,
                retry_after_seconds=None,
            )
        if record.status == PaymentOperationStatus.UNKNOWN and record.transaction_id:
            transaction = await self._transaction_for_record(record)
            requires_fulfillment_proof = (
                record.recovery_mode == PaymentOperationRecoveryMode.LOCAL
                or (transaction is not None and transaction.pricing.is_free)
            )
            if (
                requires_fulfillment_proof
                and
                transaction is not None
                and transaction.fulfillment_status
                == TransactionFulfillmentStatus.MANUAL_REQUIRED
            ):
                return PaymentOperationView(
                    operation=record.operation,
                    state=PaymentOperationPublicState.MANUAL_REQUIRED,
                    payment=None,
                    transaction=None,
                    retry_after_seconds=None,
                )
            if requires_fulfillment_proof and transaction is not None and (
                transaction.fulfillment_status
                in {
                    TransactionFulfillmentStatus.NOT_STARTED,
                    TransactionFulfillmentStatus.PROCESSING,
                }
                and transaction.status != TransactionStatus.REFUNDED
            ):
                return PaymentOperationView(
                    operation=record.operation,
                    state=PaymentOperationPublicState.IN_PROGRESS,
                    payment=None,
                    transaction=None,
                    retry_after_seconds=2,
                )
        if record.status in (
            PaymentOperationStatus.CLAIMED,
            PaymentOperationStatus.PROCESSING,
        ):
            state = PaymentOperationPublicState.IN_PROGRESS
            retry_after = 2
        elif record.status == PaymentOperationStatus.MANUAL_REQUIRED:
            state = PaymentOperationPublicState.MANUAL_REQUIRED
            retry_after = None
        else:
            state = PaymentOperationPublicState.UNKNOWN
            retry_after = self._retry_after(record)
        return PaymentOperationView(
            operation=record.operation,
            state=state,
            payment=None,
            transaction=None,
            retry_after_seconds=retry_after,
        )

    async def lookup(
        self,
        *,
        user_id: int,
        operation: str,
        idempotency_key: str,
    ) -> PaymentOperationView:
        async with self.uow:
            record = await self._owned_record(
                user_id=user_id,
                operation=operation,
                idempotency_key=idempotency_key,
            )
            view = await self._view(record)
            await self.uow.commit()
        return view

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(f"remnashop:reconcile-token:v1\0{token}".encode()).hexdigest()

    @staticmethod
    def _payment_result(
        snapshot: Optional[dict[str, Any]],
    ) -> tuple[UUID, str | None, str | None]:
        if not isinstance(snapshot, dict) or set(snapshot) != {
            "version",
            "payment_id",
            "payment_url",
            "provider_status",
        }:
            raise InvalidPaymentRecoverySnapshotError("Invalid provider result shape")
        if snapshot["version"] != 1 or isinstance(snapshot["version"], bool):
            raise InvalidPaymentRecoverySnapshotError("Invalid provider result version")
        payment_url = snapshot["payment_url"]
        if payment_url is not None and (not isinstance(payment_url, str) or not payment_url):
            raise InvalidPaymentRecoverySnapshotError("Invalid provider payment URL")
        provider_status = snapshot["provider_status"]
        if provider_status not in {
            None,
            "LOCAL",
            "pending",
            "waiting_for_capture",
            "succeeded",
            "canceled",
        }:
            raise InvalidPaymentRecoverySnapshotError("Invalid provider payment status")
        try:
            payment_id = UUID(str(snapshot["payment_id"]))
        except (ValueError, TypeError, AttributeError) as exc:
            raise InvalidPaymentRecoverySnapshotError("Invalid provider payment id") from exc
        return payment_id, payment_url, provider_status

    @classmethod
    def _payment_url(cls, snapshot: Optional[dict[str, Any]]) -> str | None:
        if snapshot is None:
            return None
        return cls._payment_result(snapshot)[1]

    @staticmethod
    def _positive_decimal(value: object, name: str) -> Decimal:
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise InvalidPaymentRecoverySnapshotError(f"Invalid {name}") from exc
        if not parsed.is_finite() or parsed <= 0:
            raise InvalidPaymentRecoverySnapshotError(f"Invalid {name}")
        return parsed

    @classmethod
    def _validated_yookassa_amount(
        cls,
        request: dict[str, Any],
        expected: TransactionDto,
    ) -> dict[str, Any]:
        amount = request["amount"]
        if not isinstance(amount, dict) or set(amount) != {"value", "currency"}:
            raise InvalidPaymentRecoverySnapshotError("Invalid YooKassa amount")
        if (
            cls._positive_decimal(amount["value"], "YooKassa amount")
            != expected.pricing.final_amount
            or amount["currency"] != expected.currency.value
        ):
            raise InvalidPaymentRecoverySnapshotError("YooKassa amount mismatch")
        return amount

    @staticmethod
    def _validated_yookassa_description(
        request: dict[str, Any],
    ) -> str:
        description = request["description"]
        confirmation = request["confirmation"]
        if not isinstance(description, str) or not description:
            raise InvalidPaymentRecoverySnapshotError("Invalid YooKassa description")
        if (
            not isinstance(confirmation, dict)
            or set(confirmation) != {"type", "return_url"}
            or confirmation["type"] != "redirect"
            or not isinstance(confirmation["return_url"], str)
            or urlparse(confirmation["return_url"]).scheme not in {"http", "https"}
        ):
            raise InvalidPaymentRecoverySnapshotError("Invalid YooKassa confirmation")
        return description

    @classmethod
    def _validate_yookassa_receipt(
        cls,
        receipt: object,
        *,
        description: str,
        amount: dict[str, Any],
    ) -> None:
        if not isinstance(receipt, dict) or set(receipt) != {"customer", "items"}:
            raise InvalidPaymentRecoverySnapshotError("Invalid YooKassa receipt")
        customer = receipt["customer"]
        items = receipt["items"]
        if (
            not isinstance(customer, dict)
            or set(customer) != {"email"}
            or not isinstance(customer["email"], str)
            or not customer["email"]
            or not isinstance(items, list)
            or len(items) != 1
            or not isinstance(items[0], dict)
        ):
            raise InvalidPaymentRecoverySnapshotError("Invalid YooKassa receipt body")
        item = items[0]
        if set(item) != {
            "description",
            "quantity",
            "amount",
            "vat_code",
            "payment_subject",
            "payment_mode",
        }:
            raise InvalidPaymentRecoverySnapshotError("Invalid YooKassa receipt item")
        if (
            item["description"] != description
            or item["amount"] != amount
            or cls._positive_decimal(item["quantity"], "YooKassa quantity") != Decimal("1")
            or item["vat_code"] is None
            or item["payment_subject"] != "service"
            or item["payment_mode"] != "full_payment"
        ):
            raise InvalidPaymentRecoverySnapshotError("YooKassa receipt mismatch")

    @classmethod
    def _validated_yookassa_request(
        cls,
        record: PaymentOperationRecord,
    ) -> dict[str, Any]:
        request = record.provider_request_snapshot
        resolved = record.resolved_payment_snapshot
        if request is None or resolved is None:
            raise InvalidPaymentRecoverySnapshotError(
                "Provider recovery snapshot is incomplete"
            )
        expected = transaction_from_resolved_snapshot(
            resolved,
            expected_user_id=record.user_id,
            payment_id=UUID(int=0),
        )
        if (
            expected.gateway_type != PaymentGatewayType.YOOKASSA
            or expected.pricing.is_free
            or set(request)
            != {
                "amount",
                "confirmation",
                "capture",
                "description",
                "receipt",
                "metadata",
            }
        ):
            raise InvalidPaymentRecoverySnapshotError("Invalid YooKassa recovery request")
        if request["metadata"] != {"remnashop_operation_id": str(record.id)}:
            raise InvalidPaymentRecoverySnapshotError("YooKassa metadata mismatch")
        if request["capture"] is not True:
            raise InvalidPaymentRecoverySnapshotError("Invalid YooKassa capture mode")
        amount = cls._validated_yookassa_amount(request, expected)
        description = cls._validated_yookassa_description(request)
        cls._validate_yookassa_receipt(
            request["receipt"],
            description=description,
            amount=amount,
        )
        return request

    @staticmethod
    def _transactions_match(actual: TransactionDto, expected: TransactionDto) -> bool:
        return (
            actual.payment_id == expected.payment_id
            and actual.user_id == expected.user_id
            and actual.purchase_type == expected.purchase_type
            and actual.gateway_type == expected.gateway_type
            and actual.gateway_display_name == expected.gateway_display_name
            and actual.payment_method == expected.payment_method
            and actual.pricing == expected.pricing
            and actual.currency == expected.currency
            and actual.plan_snapshot == expected.plan_snapshot
        )

    @staticmethod
    def _success_event_disposition(transaction: TransactionDto) -> str:
        if transaction.status == TransactionStatus.PENDING or (
            transaction.status == TransactionStatus.CANCELED
            and transaction.cancellation_reason == "LOCAL_TIMEOUT"
        ):
            return "ENQUEUE"
        if transaction.status == TransactionStatus.REFUNDED:
            return "TERMINAL_REFUND"
        if transaction.status == TransactionStatus.COMPLETED:
            return "ALREADY_APPLIED"
        raise InvalidPaymentRecoverySnapshotError(
            "Provider success conflicts with terminal transaction state"
        )

    @staticmethod
    def _requires_fulfillment_proof(
        record: PaymentOperationRecord,
        transaction: TransactionDto,
    ) -> bool:
        return (
            record.recovery_mode == PaymentOperationRecoveryMode.LOCAL
            or transaction.pricing.is_free
        )

    async def _queue_success_event(self, transaction: TransactionDto) -> None:
        if self._success_event_disposition(transaction) == "ENQUEUE":
            await self.transaction_dao.store_webhook_event(
                payment_id=transaction.payment_id,
                gateway_type=transaction.gateway_type,
                status=TransactionStatus.COMPLETED,
            )

    async def _ensure_transaction(
        self,
        record: PaymentOperationRecord,
        payment_id: UUID,
        *,
        recovered_status: TransactionStatus = TransactionStatus.PENDING,
        cancellation_reason: str | None = None,
    ) -> TransactionDto:
        if record.resolved_payment_snapshot is None:
            raise InvalidPaymentRecoverySnapshotError("Resolved payment snapshot is missing")
        expected = transaction_from_resolved_snapshot(
            record.resolved_payment_snapshot,
            expected_user_id=record.user_id,
            payment_id=payment_id,
        )
        expected.status = recovered_status
        expected.cancellation_reason = cancellation_reason
        existing = await self.transaction_dao.get_by_payment_id(payment_id)
        if existing is not None:
            if not self._transactions_match(existing, expected):
                raise InvalidPaymentRecoverySnapshotError("Payment transaction conflict")
            return existing
        return await self.transaction_dao.create(expected)

    async def _ensure_recovered_transaction(
        self,
        record: PaymentOperationRecord,
        payment_id: UUID,
        provider_status: str | None,
    ) -> TransactionDto:
        transaction = await self._ensure_transaction(
            record,
            payment_id,
            recovered_status=(
                TransactionStatus.CANCELED
                if provider_status == "canceled"
                else TransactionStatus.PENDING
            ),
            cancellation_reason=("PROVIDER" if provider_status == "canceled" else None),
        )
        if provider_status != "canceled" or (
            transaction.status == TransactionStatus.CANCELED
            and transaction.cancellation_reason == "PROVIDER"
        ):
            return transaction
        canceled = await self.transaction_dao.cancel_by_provider(payment_id)
        if canceled is None:
            raise InvalidPaymentRecoverySnapshotError(
                "Canceled provider payment conflicts with local transaction state"
            )
        return canceled

    async def _require_or_enqueue_fulfillment(
        self,
        transaction: TransactionDto,
    ) -> None:
        if (
            transaction.fulfillment_status == TransactionFulfillmentStatus.SUCCEEDED
            and transaction.fulfillment_completed_at is not None
        ):
            return
        if transaction.fulfillment_status == TransactionFulfillmentStatus.MANUAL_REQUIRED:
            raise InvalidPaymentRecoverySnapshotError(
                "Payment fulfillment requires manual review"
            )
        if transaction.fulfillment_status == TransactionFulfillmentStatus.PROCESSING:
            await self.uow.commit()
            raise PaymentFulfillmentInProgressError
        if transaction.status == TransactionStatus.REFUNDED:
            raise InvalidPaymentRecoverySnapshotError(
                "Free payment was refunded without fulfillment proof"
            )
        if transaction.status == TransactionStatus.CANCELED and (
            transaction.cancellation_reason != "LOCAL_TIMEOUT"
        ):
            raise InvalidPaymentRecoverySnapshotError(
                "Free payment cancellation is not locally recoverable"
            )
        if transaction.status == TransactionStatus.FAILED:
            raise InvalidPaymentRecoverySnapshotError(
                "Failed free payment cannot be fulfilled automatically"
            )
        await self.transaction_dao.store_webhook_event(
            payment_id=transaction.payment_id,
            gateway_type=transaction.gateway_type,
            status=TransactionStatus.COMPLETED,
        )
        await self.uow.commit()
        raise PaymentFulfillmentInProgressError

    async def _complete_with_result(
        self,
        record: PaymentOperationRecord,
        *,
        token_hash: str,
        provider_result: dict[str, Any],
    ) -> None:
        payment_id, payment_url, provider_status = self._payment_result(provider_result)
        async with self.uow:
            refreshed = await self.payment_operation_dao.get_by_id(record.id)
            if refreshed is None or refreshed.reconcile_token_hash != token_hash:
                raise RuntimeError("Reconciliation lease was lost")
            transaction = await self._ensure_recovered_transaction(
                refreshed,
                payment_id,
                provider_status,
            )
            requires_fulfillment_proof = self._requires_fulfillment_proof(
                refreshed,
                transaction,
            )
            if requires_fulfillment_proof and provider_status != "succeeded":
                raise InvalidPaymentRecoverySnapshotError(
                    "Free payment recovery lacks fulfillment proof"
                )
            if provider_status == "succeeded":
                await self._queue_success_event(transaction)
                if requires_fulfillment_proof:
                    linked = (
                        await self.payment_operation_dao.link_pending_fulfillment_reconciliation(
                            refreshed.id,
                            token_hash=token_hash,
                            transaction_id=transaction.id,
                            provider_result=provider_result,
                            retry_after=timedelta(seconds=MIN_RETRY_SECONDS),
                        )
                    )
                    if not linked:
                        raise RuntimeError("Free fulfillment recovery lost its fence")
                    await self.uow.commit()
                    return
                response = build_payment_response(transaction, payment_url=payment_url)
                completed = await self.payment_operation_dao.complete_reconciliation(
                    refreshed.id,
                    token_hash=token_hash,
                    transaction_id=transaction.id,
                    response=response,
                    provider_result=provider_result,
                )
                if not completed:
                    raise RuntimeError("Provider-success reconciliation lost its fence")
                await self.uow.commit()
                return
            response = build_payment_response(transaction, payment_url=payment_url)
            completed = await self.payment_operation_dao.complete_reconciliation(
                refreshed.id,
                token_hash=token_hash,
                transaction_id=transaction.id,
                response=response,
                provider_result=provider_result,
            )
            if not completed:
                raise RuntimeError("Reconciliation completion lost its fence")
            await self.uow.commit()

    async def _complete_linked(
        self,
        record: PaymentOperationRecord,
        *,
        token_hash: str,
    ) -> None:
        async with self.uow:
            refreshed = await self.payment_operation_dao.get_by_id(record.id)
            if refreshed is None or refreshed.reconcile_token_hash != token_hash:
                raise RuntimeError("Reconciliation lease was lost")
            transaction = await self._transaction_for_record(refreshed)
            if transaction is None:
                raise RuntimeError("Linked payment transaction disappeared")
            requires_fulfillment_proof = self._requires_fulfillment_proof(
                refreshed,
                transaction,
            )
            provider_status = (
                self._payment_result(refreshed.provider_result_snapshot)[2]
                if refreshed.provider_result_snapshot is not None
                else None
            )
            if provider_status == "succeeded":
                await self._queue_success_event(transaction)
            if requires_fulfillment_proof:
                await self._require_or_enqueue_fulfillment(transaction)
            response = build_payment_response(
                transaction,
                payment_url=self._payment_url(refreshed.provider_result_snapshot),
            )
            completed = await self.payment_operation_dao.complete_reconciliation(
                refreshed.id,
                token_hash=token_hash,
                transaction_id=transaction.id,
                response=response,
                provider_result=refreshed.provider_result_snapshot,
            )
            if not completed:
                raise RuntimeError("Reconciliation completion lost its fence")
            await self.uow.commit()

    async def _create_local_transaction_for_fulfillment(
        self,
        record: PaymentOperationRecord,
        *,
        token_hash: str,
        provider_result: dict[str, Any],
    ) -> None:
        payment_id, _, _ = self._payment_result(provider_result)
        async with self.uow:
            refreshed = await self.payment_operation_dao.get_by_id(record.id)
            if refreshed is None or refreshed.reconcile_token_hash != token_hash:
                raise RuntimeError("Reconciliation lease was lost")
            transaction = await self._ensure_transaction(refreshed, payment_id)
            await self.transaction_dao.store_webhook_event(
                payment_id=transaction.payment_id,
                gateway_type=transaction.gateway_type,
                status=TransactionStatus.COMPLETED,
            )
            linked = (
                await self.payment_operation_dao.link_pending_fulfillment_reconciliation(
                    refreshed.id,
                    token_hash=token_hash,
                    transaction_id=transaction.id,
                    provider_result=provider_result,
                    retry_after=timedelta(seconds=MIN_RETRY_SECONDS),
                )
            )
            if not linked:
                raise RuntimeError("Local fulfillment recovery link lost its fence")
            await self.uow.commit()

    async def _checkpoint_result(
        self,
        operation_id: int,
        *,
        token_hash: str,
        result: dict[str, Any],
    ) -> None:
        async with self.uow:
            checkpointed = await self.payment_operation_dao.checkpoint_reconciliation_result(
                operation_id,
                token_hash=token_hash,
                result=result,
            )
            if not checkpointed:
                raise RuntimeError("Reconciliation checkpoint lost its fence")
            await self.uow.commit()

    async def _verify_checkpointed_result(
        self,
        record: PaymentOperationRecord,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        if record.gateway_type != PaymentGatewayType.YOOKASSA.value:
            return result
        if record.provider_owner_hash is None:
            raise InvalidPaymentRecoverySnapshotError("Provider recovery snapshot is incomplete")
        provider_request = self._validated_yookassa_request(record)
        payment_id, stored_url, _ = self._payment_result(result)
        gateway = await self.payment_gateway_dao.get_by_type(PaymentGatewayType.YOOKASSA)
        if gateway is None or not gateway.is_active:
            raise InvalidPaymentRecoverySnapshotError("Recovery gateway is unavailable")
        instance = await self.get_payment_gateway_instance.system(PaymentGatewayType.YOOKASSA)
        if instance.payment_owner_fingerprint() != record.provider_owner_hash:
            raise InvalidPaymentRecoverySnapshotError("Provider owner changed")
        try:
            verified = await instance.verify_payment_result(
                payment_id,
                provider_request,
            )
        except ValueError as exc:
            raise InvalidPaymentRecoverySnapshotError(
                "Provider payment does not match the persisted request"
            ) from exc
        return {
            "version": 1,
            "payment_id": str(verified.id),
            "payment_url": verified.url or stored_url,
            "provider_status": verified.provider_status,
        }

    async def _manual(
        self,
        operation_id: int,
        *,
        token_hash: str,
        error_code: str,
    ) -> None:
        await self.uow.rollback()
        async with self.uow:
            await self.payment_operation_dao.mark_manual_required(
                operation_id,
                token_hash=token_hash,
                error_code=error_code,
            )
            await self.uow.commit()

    async def _release(
        self,
        record: PaymentOperationRecord,
        *,
        token_hash: str,
        error_code: str,
    ) -> None:
        await self.uow.rollback()
        exponent = min(record.reconcile_attempt_count, 6)
        retry_seconds = min(MAX_RETRY_SECONDS, MIN_RETRY_SECONDS * (2**exponent))
        async with self.uow:
            await self.payment_operation_dao.release_reconciliation(
                record.id,
                token_hash=token_hash,
                retry_after=timedelta(seconds=retry_seconds),
                error_code=error_code,
            )
            await self.uow.commit()

    async def _reconcile_claimed(  # noqa: C901
        self,
        record: PaymentOperationRecord,
        *,
        token_hash: str,
    ) -> None:
        if record.transaction_id is not None:
            await self._complete_linked(record, token_hash=token_hash)
            return
        if record.recovery_mode == PaymentOperationRecoveryMode.LOCAL:
            result = record.provider_result_snapshot
            if result is None:
                request = record.provider_request_snapshot
                if not isinstance(request, dict) or set(request) != {
                    "version",
                    "kind",
                    "payment_id",
                }:
                    raise InvalidPaymentRecoverySnapshotError("Invalid local recovery request")
                if request["version"] != 1 or request["kind"] != "LOCAL":
                    raise InvalidPaymentRecoverySnapshotError("Invalid local recovery version")
                result = {
                    "version": 1,
                    "payment_id": str(UUID(str(request["payment_id"]))),
                    "payment_url": None,
                    "provider_status": "LOCAL",
                }
                await self._checkpoint_result(record.id, token_hash=token_hash, result=result)
            await self._create_local_transaction_for_fulfillment(
                record,
                token_hash=token_hash,
                provider_result=result,
            )
            return
        if record.provider_result_snapshot is not None:
            verified_result = await self._verify_checkpointed_result(
                record,
                record.provider_result_snapshot,
            )
            await self._complete_with_result(
                record,
                token_hash=token_hash,
                provider_result=verified_result,
            )
            return
        if record.recovery_mode != PaymentOperationRecoveryMode.YOOKASSA_REPLAY:
            raise InvalidPaymentRecoverySnapshotError("Gateway cannot be replayed safely")
        if record.gateway_type != PaymentGatewayType.YOOKASSA.value:
            raise InvalidPaymentRecoverySnapshotError("Recovery gateway mismatch")
        if record.provider_owner_hash is None:
            raise InvalidPaymentRecoverySnapshotError("Provider recovery snapshot is incomplete")
        provider_request = self._validated_yookassa_request(record)
        gateway = await self.payment_gateway_dao.get_by_type(PaymentGatewayType.YOOKASSA)
        if gateway is None or not gateway.is_active:
            raise InvalidPaymentRecoverySnapshotError("Recovery gateway is unavailable")
        instance = await self.get_payment_gateway_instance.system(PaymentGatewayType.YOOKASSA)
        if instance.payment_owner_fingerprint() != record.provider_owner_hash:
            raise InvalidPaymentRecoverySnapshotError("Provider owner changed")
        payment = await instance.create_payment_from_request(
            provider_request,
            idempotency_key=record.provider_key,
        )
        result = {
            "version": 1,
            "payment_id": str(payment.id),
            "payment_url": payment.url,
            "provider_status": payment.provider_status,
        }
        await self._checkpoint_result(record.id, token_hash=token_hash, result=result)
        verified_result = await self._verify_checkpointed_result(record, result)
        await self._complete_with_result(
            record,
            token_hash=token_hash,
            provider_result=verified_result,
        )

    @staticmethod
    def _same_identity(
        record: PaymentOperationRecord,
        *,
        user_id: int,
        operation: str,
        idempotency_key: str,
    ) -> bool:
        return (
            record.user_id == user_id
            and record.operation == operation
            and record.idempotency_key == idempotency_key
        )

    async def _refresh_owned_record(
        self,
        operation_id: int,
        *,
        user_id: int,
        operation: str,
        idempotency_key: str,
    ) -> PaymentOperationRecord:
        record = await self.payment_operation_dao.get_by_id(operation_id)
        if record is None or not self._same_identity(
            record,
            user_id=user_id,
            operation=operation,
            idempotency_key=idempotency_key,
        ):
            raise PaymentOperationNotFoundError
        return record

    async def _claim_for_reconciliation(
        self,
        *,
        user_id: int,
        operation: str,
        idempotency_key: str,
        token_hash: str,
    ) -> PaymentOperationRecord | PaymentOperationView:
        async with self.uow:
            record = await self._owned_record(
                user_id=user_id,
                operation=operation,
                idempotency_key=idempotency_key,
            )
            if record.status == PaymentOperationStatus.CLAIMED:
                deleted = await self.payment_operation_dao.delete_expired_claimed(record.id)
                if deleted:
                    await self.uow.commit()
                    raise PaymentOperationNotFoundError

            record = await self._refresh_owned_record(
                record.id,
                user_id=user_id,
                operation=operation,
                idempotency_key=idempotency_key,
            )
            if record.status == PaymentOperationStatus.PROCESSING:
                await self.payment_operation_dao.expire_processing(record.id)
                record = await self._refresh_owned_record(
                    record.id,
                    user_id=user_id,
                    operation=operation,
                    idempotency_key=idempotency_key,
                )
            if record.status != PaymentOperationStatus.UNKNOWN:
                view = await self._view(record)
                await self.uow.commit()
                return view

            await self.payment_operation_dao.mark_expired_provider_replay_manual(
                record.id
            )
            await self.payment_operation_dao.mark_exhausted_reconciliation_manual(
                record.id,
                max_attempts=MAX_RECONCILIATION_ATTEMPTS,
            )
            record = await self._refresh_owned_record(
                record.id,
                user_id=user_id,
                operation=operation,
                idempotency_key=idempotency_key,
            )
            if record.status != PaymentOperationStatus.UNKNOWN:
                view = await self._view(record)
                await self.uow.commit()
                return view

            claimed = await self.payment_operation_dao.claim_reconciliation(
                record.id,
                token_hash=token_hash,
                lease_for=RECONCILIATION_LEASE,
            )
            if not claimed:
                # The replay deadline may have crossed while this request waited
                # for a concurrent claimant. Re-evaluate with PostgreSQL's clock.
                await self.payment_operation_dao.mark_expired_provider_replay_manual(
                    record.id
                )
                await self.payment_operation_dao.mark_exhausted_reconciliation_manual(
                    record.id,
                    max_attempts=MAX_RECONCILIATION_ATTEMPTS,
                )
            await self.uow.commit()

        if not claimed:
            return await self.lookup(
                user_id=user_id,
                operation=operation,
                idempotency_key=idempotency_key,
            )

        async with self.uow:
            claimed_record = await self._refresh_owned_record(
                record.id,
                user_id=user_id,
                operation=operation,
                idempotency_key=idempotency_key,
            )
            await self.uow.commit()
        return claimed_record

    async def reconcile(
        self,
        *,
        user_id: int,
        operation: str,
        idempotency_key: str,
    ) -> PaymentOperationView:
        token = secrets.token_urlsafe(32)
        token_hash = self._token_hash(token)
        claim = await self._claim_for_reconciliation(
            user_id=user_id,
            operation=operation,
            idempotency_key=idempotency_key,
            token_hash=token_hash,
        )
        if isinstance(claim, PaymentOperationView):
            return claim
        claimed_record = claim
        try:
            await self._reconcile_claimed(claimed_record, token_hash=token_hash)
        except PaymentFulfillmentInProgressError:
            if claimed_record.reconcile_attempt_count >= MAX_RECONCILIATION_ATTEMPTS:
                await self._manual(
                    claimed_record.id,
                    token_hash=token_hash,
                    error_code="FULFILLMENT_RETRIES_EXHAUSTED",
                )
            else:
                await self._release(
                    claimed_record,
                    token_hash=token_hash,
                    error_code="AWAITING_FULFILLMENT",
                )
        except InvalidPaymentRecoverySnapshotError as exc:
            logger.warning(
                "Payment operation '{}' requires manual recovery: {}",
                claimed_record.id,
                exc,
            )
            await self._manual(
                claimed_record.id,
                token_hash=token_hash,
                error_code="MANUAL_REQUIRED",
            )
        except HTTPStatusError as exc:
            if 400 <= exc.response.status_code < 500 and exc.response.status_code != 429:
                await self._manual(
                    claimed_record.id,
                    token_hash=token_hash,
                    error_code="PROVIDER_REJECTED",
                )
            elif claimed_record.reconcile_attempt_count >= MAX_RECONCILIATION_ATTEMPTS:
                await self._manual(
                    claimed_record.id,
                    token_hash=token_hash,
                    error_code="PROVIDER_RETRIES_EXHAUSTED",
                )
            else:
                await self._release(
                    claimed_record,
                    token_hash=token_hash,
                    error_code="PROVIDER_TEMPORARY",
                )
        except Exception:
            logger.exception(
                "Transient payment reconciliation failure for operation '{}'",
                claimed_record.id,
            )
            if claimed_record.reconcile_attempt_count >= MAX_RECONCILIATION_ATTEMPTS:
                await self._manual(
                    claimed_record.id,
                    token_hash=token_hash,
                    error_code="RECONCILIATION_RETRIES_EXHAUSTED",
                )
            else:
                await self._release(
                    claimed_record,
                    token_hash=token_hash,
                    error_code="RECONCILIATION_FAILED",
                )
        return await self.lookup(
            user_id=user_id,
            operation=operation,
            idempotency_key=idempotency_key,
        )
