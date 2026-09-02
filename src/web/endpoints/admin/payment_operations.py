import re
from typing import Optional

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Header, HTTPException, Query, Response, Security, status
from loguru import logger
from pydantic import ValidationError

from src.application.common.dao.payment_operation import PaymentOperationOwnerMergedError
from src.application.dto import TransactionDto
from src.application.services.payment_reconciliation import (
    PaymentOperationNotFoundError,
    PaymentOperationPublicState,
    PaymentOperationView,
    PaymentReconciliationService,
)
from src.web.dependencies import require_api_key
from src.web.schemas import (
    PaymentInitResponse,
    PaymentOperationResponse,
    PaymentTransactionResponse,
)

router = APIRouter(prefix="/payment-operations", tags=["Admin - Payment Operations"])

_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:~-]{15,127}$")
_OPERATIONS = {"PURCHASE", "EXTEND"}


def _operation_name(value: str) -> str:
    operation = value.upper()
    if operation not in _OPERATIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported payment operation",
        )
    return operation


def _idempotency_key(value: Optional[str]) -> str:
    if value is None or not _IDEMPOTENCY_KEY_PATTERN.fullmatch(value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A valid Idempotency-Key header is required",
        )
    return value


def _transaction_response(transaction: TransactionDto) -> PaymentTransactionResponse:
    return PaymentTransactionResponse(
        payment_id=str(transaction.payment_id),
        purchase_type=transaction.purchase_type.value,
        status=transaction.status.value,
        gateway_type=transaction.gateway_type,
        final_amount=str(transaction.pricing.final_amount),
        currency=transaction.currency.symbol,
        plan_name=transaction.plan_snapshot.name,
        duration_days=transaction.plan_snapshot.duration,
        device_limit=transaction.plan_snapshot.device_limit,
        traffic_limit=transaction.plan_snapshot.traffic_limit,
        created_at=transaction.created_at,
        updated_at=transaction.updated_at,
    )


def _operation_response(view: PaymentOperationView) -> PaymentOperationResponse:
    try:
        payment = PaymentInitResponse.model_validate(view.payment) if view.payment else None
    except ValidationError as exc:
        logger.error("Stored payment operation response validation failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stored payment state is invalid",
        ) from exc
    return PaymentOperationResponse(
        operation=view.operation,
        state=view.state.value,
        payment=payment,
        transaction=_transaction_response(view.transaction) if view.transaction else None,
        retry_after_seconds=view.retry_after_seconds,
    )


def _set_status(response: Response, view: PaymentOperationView) -> None:
    if view.state == PaymentOperationPublicState.SUCCEEDED:
        return
    response.status_code = status.HTTP_202_ACCEPTED
    if view.retry_after_seconds is not None:
        response.headers["Retry-After"] = str(view.retry_after_seconds)


@router.get("/{operation}", response_model=PaymentOperationResponse)
@inject
async def get_payment_operation_admin(
    operation: str,
    response: Response,
    reconciliation: FromDishka[PaymentReconciliationService],
    user_id: int = Query(ge=1),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    _: None = Security(require_api_key),
) -> PaymentOperationResponse:
    try:
        view = await reconciliation.lookup(
            user_id=user_id,
            operation=_operation_name(operation),
            idempotency_key=_idempotency_key(idempotency_key),
        )
    except PaymentOperationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment operation not found",
        ) from exc
    except PaymentOperationOwnerMergedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Payment operation owner changed; retry with the current owner",
        ) from exc
    _set_status(response, view)
    return _operation_response(view)


@router.post("/{operation}", response_model=PaymentOperationResponse)
@inject
async def reconcile_payment_operation_admin(
    operation: str,
    response: Response,
    reconciliation: FromDishka[PaymentReconciliationService],
    user_id: int = Query(ge=1),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    _: None = Security(require_api_key),
) -> PaymentOperationResponse:
    try:
        view = await reconciliation.reconcile(
            user_id=user_id,
            operation=_operation_name(operation),
            idempotency_key=_idempotency_key(idempotency_key),
        )
    except PaymentOperationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment operation not found",
        ) from exc
    except PaymentOperationOwnerMergedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Payment operation owner changed; retry with the current owner",
        ) from exc
    _set_status(response, view)
    return _operation_response(view)
