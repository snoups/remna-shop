import hashlib
import json
import re
from typing import Optional
from urllib.parse import urlsplit
from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Header, HTTPException, Query, Response, status
from loguru import logger
from pydantic import ValidationError
from remnapy.models.hwid import HwidDeviceDto

from src.application.common import Remnawave
from src.application.common.dao import (
    PaymentGatewayDao,
    SettingsDao,
    SubscriptionDao,
    TransactionDao,
)
from src.application.common.dao.payment_operation import PaymentOperationOwnerMergedError
from src.application.dto import PlanDto, PlanSnapshotDto, TransactionDto, UserDto
from src.application.services import PaymentIdempotencyService, PricingService
from src.application.services.payment_cursor import (
    InvalidPaymentCursorError,
    PaymentCursorCodec,
)
from src.application.services.payment_idempotency import (
    PaymentOperationConflictError,
    PaymentOperationInProgressError,
    PaymentOperationOutcomeUnknownError,
    PaymentOperationStart,
)
from src.application.services.payment_reconciliation import (
    PaymentOperationNotFoundError,
    PaymentOperationPublicState,
    PaymentOperationView,
    PaymentReconciliationService,
)
from src.application.use_cases.gateways.commands.payment import (
    CreatePayment,
    CreatePaymentDto,
    ProcessPayment,
    ProcessPaymentDto,
)
from src.application.use_cases.plan.queries.match import (
    MatchPlan,
    MatchPlanDto,
    resolve_renew_plan,
)
from src.application.use_cases.plan.queries.renewal import GetRenewalPlanContext
from src.application.use_cases.promocode.commands.activate import (
    ActivatePromocode,
    ActivatePromocodeDto,
)
from src.application.use_cases.remnawave.commands.management import (
    DeleteUserAllDevices,
    DeleteUserDevice,
    DeleteUserDeviceDto,
    ReissueSubscription,
)
from src.application.use_cases.subscription.commands.purchase import (
    ActivateTrialSubscription,
    ActivateTrialSubscriptionDto,
)
from src.application.use_cases.user.queries.plans import GetAvailablePlans, GetAvailableTrial
from src.core.config import AppConfig
from src.core.enums import (
    PaymentGatewayType,
    PurchaseType,
    TransactionStatus,
)
from src.core.exceptions import (
    CooldownError,
    PromocodeAlreadyActivatedError,
    PromocodeExpiredError,
    PromocodeNotAvailableError,
    PromocodeNotFoundError,
    TrialNotAvailableError,
)
from src.web.schemas import (
    DeviceDeleteResponse,
    DeviceResponse,
    DevicesDeleteAllResponse,
    DevicesResponse,
    DurationGatewayPriceResponse,
    DurationOfferResponse,
    ExtendRequest,
    GatewayOfferResponse,
    PaymentInitResponse,
    PaymentOperationResponse,
    PaymentTransactionResponse,
    PaymentTransactionsPageResponse,
    PlanOfferResponse,
    PromocodeActivateRequest,
    PromocodeActivateResponse,
    PurchaseRequest,
    ReissueResponse,
    SubscriptionCapabilitiesResponse,
    SubscriptionInfoResponse,
    SubscriptionOffersResponse,
    TrialActivateResponse,
    TrialPurchaseRequest,
)

from ._common import CurrentUser

router = APIRouter(prefix="/subscription", tags=["Public - Subscription"])

_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:~-]{15,127}$")
_PURCHASE_OPERATION = "PURCHASE"
_EXTEND_OPERATION = "EXTEND"
_PAYMENT_OUTCOME_UNKNOWN_DETAIL = (
    "The payment outcome is unknown; do not create another payment "
    "until this operation is reconciled"
)


def _validate_idempotency_key(idempotency_key: Optional[str]) -> Optional[str]:
    if idempotency_key is None:
        return None
    if not _IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Idempotency-Key must be 16-128 characters and contain only "
                "letters, digits, '.', '_', ':', '~', or '-'"
            ),
        )
    return idempotency_key


def _required_idempotency_key(idempotency_key: Optional[str]) -> str:
    key = _validate_idempotency_key(idempotency_key)
    if key is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key header is required",
        )
    return key


def _payment_operation_name(operation: str) -> str:
    normalized = operation.upper()
    if normalized not in {_PURCHASE_OPERATION, _EXTEND_OPERATION}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported payment operation",
        )
    return normalized


def _payment_request_hash(
    operation: str,
    body: PurchaseRequest | ExtendRequest,
) -> str:
    canonical = json.dumps(
        {"operation": operation, "request": body.model_dump(mode="json")},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


async def _start_payment_operation(
    *,
    idempotency_key: Optional[str],
    operation: str,
    body: PurchaseRequest | ExtendRequest,
    user: UserDto,
    idempotency: PaymentIdempotencyService,
) -> tuple[Optional[PaymentOperationStart], Optional[PaymentInitResponse]]:
    key = _validate_idempotency_key(idempotency_key)
    if key is None:
        return None, None

    try:
        payment_operation = await idempotency.start(
            user_id=user.id,
            operation=operation,
            idempotency_key=key,
            request_hash=_payment_request_hash(operation, body),
        )
    except PaymentOperationConflictError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency-Key was already used with a different request",
        ) from e
    except PaymentOperationInProgressError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A request with this Idempotency-Key is already in progress",
            headers={"Retry-After": "2"},
        ) from e
    except PaymentOperationOutcomeUnknownError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_PAYMENT_OUTCOME_UNKNOWN_DETAIL,
        ) from e
    except PaymentOperationOwnerMergedError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User account was merged; sign in again before creating a payment",
        ) from e

    if payment_operation.replay_response is None:
        return payment_operation, None

    try:
        replay = PaymentInitResponse.model_validate(payment_operation.replay_response)
    except ValidationError as e:
        logger.exception(
            "Stored idempotency response is invalid for operation '{}'",
            payment_operation.operation_id,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The stored payment result cannot be replayed safely",
        ) from e
    return payment_operation, replay


async def _record_payment_operation_failure(
    *,
    idempotency: PaymentIdempotencyService,
    payment_operation: Optional[PaymentOperationStart],
    side_effect_started: bool,
) -> None:
    if payment_operation is None:
        return
    try:
        if side_effect_started:
            await idempotency.mark_unknown(payment_operation.operation_id)
        else:
            await idempotency.abandon(payment_operation.operation_id)
    except Exception:
        # Never replace the original payment exception. A CLAIMED/PROCESSING row
        # remains fail-closed and prevents a duplicate external side effect.
        logger.exception(
            "Failed to record terminal state for payment operation '{}'",
            payment_operation.operation_id,
        )


def _raise_unknown_outcome_if_needed(
    payment_operation: Optional[PaymentOperationStart],
    side_effect_started: bool,
    error: BaseException,
) -> None:
    if payment_operation is not None and side_effect_started and isinstance(error, Exception):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_PAYMENT_OUTCOME_UNKNOWN_DETAIL,
        ) from error


def _to_device_response(device: HwidDeviceDto) -> DeviceResponse:
    return DeviceResponse(
        hwid=device.hwid,
        platform=device.platform,
        device_model=device.device_model,
        os_version=device.os_version,
        user_agent=device.user_agent,
    )


def _assert_web_gateway(gateway_type: PaymentGatewayType) -> None:
    if gateway_type == PaymentGatewayType.TELEGRAM_STARS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="TELEGRAM_STARS gateway is not available for web purchase",
        )


def _assert_web_purchase_email_verified(user: UserDto) -> None:
    if user.is_email_verified:
        return

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Email must be verified before purchasing or extending a subscription",
    )


def _validated_payment_return_url(value: object, config: AppConfig) -> Optional[str]:
    if value is None:
        return None

    return_url = str(value)
    cabinet_url = config.web_cabinet_url
    if not cabinet_url:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="WEB_CABINET_URL is required for a web payment return URL",
        )

    parsed = urlsplit(return_url)
    cabinet = urlsplit(cabinet_url)
    if (
        (parsed.scheme, parsed.netloc) != (cabinet.scheme, cabinet.netloc)
        or parsed.path not in {"/payment/success", "/payment/fail", "/payment/pending"}
        or parsed.fragment
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Payment return URL must use the configured web cabinet origin and payment path",
        )

    return return_url


def _to_payment_transaction_response(transaction: TransactionDto) -> PaymentTransactionResponse:
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


def _to_payment_operation_response(view: PaymentOperationView) -> PaymentOperationResponse:
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
        transaction=(
            _to_payment_transaction_response(view.transaction) if view.transaction else None
        ),
        retry_after_seconds=view.retry_after_seconds,
    )


def _set_operation_http_status(response: Response, view: PaymentOperationView) -> None:
    if view.state == PaymentOperationPublicState.SUCCEEDED:
        return
    response.status_code = status.HTTP_202_ACCEPTED
    if view.retry_after_seconds is not None:
        response.headers["Retry-After"] = str(view.retry_after_seconds)


async def _get_available_plan_by_code(
    user: UserDto,
    plan_code: str,
    get_available_plans: GetAvailablePlans,
) -> Optional[PlanDto]:
    plans = await get_available_plans.system(user)
    return next((plan for plan in plans if plan.public_code == plan_code), None)


async def _validate_gateway_for_web(
    gateway_type: PaymentGatewayType,
    payment_gateway_dao: PaymentGatewayDao,
) -> None:
    _assert_web_gateway(gateway_type)
    gateway = await payment_gateway_dao.get_by_type(gateway_type)
    if not gateway or not gateway.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Gateway '{gateway_type}' not found or inactive",
        )

    if not gateway.settings or not gateway.settings.is_configured:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Gateway '{gateway_type}' is not configured",
        )


@router.get("/current", response_model=Optional[SubscriptionInfoResponse])
@inject
async def get_current_subscription(
    user: CurrentUser,
    subscription_dao: FromDishka[SubscriptionDao],
    remnawave: FromDishka[Remnawave],
) -> Optional[SubscriptionInfoResponse]:
    current_subscription = await subscription_dao.get_current(user.id)

    if not current_subscription:
        return None

    remna_user = await remnawave.get_user_by_uuid(current_subscription.user_remna_id)

    return SubscriptionInfoResponse(
        user_remna_id=str(current_subscription.user_remna_id),
        status=current_subscription.current_status.value,
        is_trial=current_subscription.is_trial,
        traffic_limit=current_subscription.traffic_limit,
        device_limit=current_subscription.device_limit,
        traffic_limit_strategy=current_subscription.traffic_limit_strategy.value,
        expire_at=current_subscription.expire_at,
        url=current_subscription.url,
        plan_name=current_subscription.plan_snapshot.name,
        plan_duration_days=current_subscription.plan_snapshot.duration,
        used_traffic_bytes=remna_user.used_traffic_bytes if remna_user else None,
        lifetime_used_traffic_bytes=remna_user.lifetime_used_traffic_bytes if remna_user else None,
        online_at=remna_user.online_at if remna_user else None,
    )


@router.get("/transactions", response_model=list[PaymentTransactionResponse])
@inject
async def get_payment_transactions(
    user: CurrentUser,
    transaction_dao: FromDishka[TransactionDao],
) -> list[PaymentTransactionResponse]:
    transactions = await transaction_dao.get_by_user(user.id)
    return [_to_payment_transaction_response(transaction) for transaction in transactions[:20]]


@router.get("/capabilities", response_model=SubscriptionCapabilitiesResponse)
async def get_subscription_capabilities() -> SubscriptionCapabilitiesResponse:
    return SubscriptionCapabilitiesResponse()


@router.get("/transactions/page", response_model=PaymentTransactionsPageResponse)
@inject
async def get_payment_transactions_page(
    user: CurrentUser,
    transaction_dao: FromDishka[TransactionDao],
    cursor_codec: FromDishka[PaymentCursorCodec],
    limit: int = Query(default=50, ge=1, le=100),
    cursor: Optional[str] = Query(default=None, min_length=1, max_length=2048),
) -> PaymentTransactionsPageResponse:
    before_created_at = None
    before_id = None
    if cursor is not None:
        try:
            decoded = cursor_codec.decode(cursor, expected_user_id=user.id)
        except InvalidPaymentCursorError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        before_created_at = decoded.created_at
        before_id = decoded.transaction_id

    transactions = await transaction_dao.get_page_by_user(
        user.id,
        limit=limit + 1,
        before_created_at=before_created_at,
        before_id=before_id,
    )
    has_more = len(transactions) > limit
    page = transactions[:limit]
    next_cursor = None
    if has_more and page:
        last = page[-1]
        if last.created_at is None or last.id <= 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Transaction cursor data is unavailable",
            )
        next_cursor = cursor_codec.encode(
            user_id=user.id,
            created_at=last.created_at,
            transaction_id=last.id,
        )
    return PaymentTransactionsPageResponse(
        items=[_to_payment_transaction_response(item) for item in page],
        next_cursor=next_cursor,
    )


@router.get(
    "/transactions/by-id/{payment_id}",
    response_model=PaymentTransactionResponse,
)
@inject
async def get_payment_transaction_by_id(
    payment_id: UUID,
    user: CurrentUser,
    transaction_dao: FromDishka[TransactionDao],
) -> PaymentTransactionResponse:
    transaction = await transaction_dao.get_by_payment_id_for_user(user.id, payment_id)
    if transaction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment transaction not found",
        )
    return _to_payment_transaction_response(transaction)


@router.get(
    "/payment-operations/{operation}",
    response_model=PaymentOperationResponse,
)
@inject
async def get_payment_operation(
    operation: str,
    response: Response,
    user: CurrentUser,
    reconciliation: FromDishka[PaymentReconciliationService],
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
) -> PaymentOperationResponse:
    try:
        view = await reconciliation.lookup(
            user_id=user.id,
            operation=_payment_operation_name(operation),
            idempotency_key=_required_idempotency_key(idempotency_key),
        )
    except PaymentOperationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment operation not found",
        ) from exc
    except PaymentOperationOwnerMergedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Payment operation owner changed; retry with a fresh session",
        ) from exc
    _set_operation_http_status(response, view)
    return _to_payment_operation_response(view)


@router.post(
    "/payment-operations/{operation}",
    response_model=PaymentOperationResponse,
)
@inject
async def reconcile_payment_operation(
    operation: str,
    response: Response,
    user: CurrentUser,
    reconciliation: FromDishka[PaymentReconciliationService],
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
) -> PaymentOperationResponse:
    try:
        view = await reconciliation.reconcile(
            user_id=user.id,
            operation=_payment_operation_name(operation),
            idempotency_key=_required_idempotency_key(idempotency_key),
        )
    except PaymentOperationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment operation not found",
        ) from exc
    except PaymentOperationOwnerMergedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Payment operation owner changed; retry with a fresh session",
        ) from exc
    _set_operation_http_status(response, view)
    return _to_payment_operation_response(view)


@router.get("/devices", response_model=DevicesResponse)
@inject
async def get_subscription_devices(
    user: CurrentUser,
    subscription_dao: FromDishka[SubscriptionDao],
    remnawave: FromDishka[Remnawave],
) -> DevicesResponse:
    current_subscription = await subscription_dao.get_current(user.id)
    if not current_subscription:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found")

    devices = await remnawave.get_devices(current_subscription.user_remna_id)
    return DevicesResponse(
        devices=[_to_device_response(device) for device in devices],
        current_count=len(devices),
        max_count=current_subscription.device_limit,
    )


@router.delete("/devices/{hwid}", response_model=DeviceDeleteResponse)
@inject
async def delete_subscription_device(
    hwid: str,
    user: CurrentUser,
    delete_user_device: FromDishka[DeleteUserDevice],
) -> DeviceDeleteResponse:
    deleted = await delete_user_device(
        user,
        DeleteUserDeviceDto(user_id=user.id, hwid=hwid),
    )
    return DeviceDeleteResponse(deleted=deleted)


@router.delete("/devices", response_model=DevicesDeleteAllResponse)
@inject
async def delete_all_subscription_devices(
    user: CurrentUser,
    delete_all_devices: FromDishka[DeleteUserAllDevices],
) -> DevicesDeleteAllResponse:
    try:
        await delete_all_devices(user)
    except CooldownError as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    return DevicesDeleteAllResponse(success=True)


@router.post("/reissue", response_model=ReissueResponse)
@inject
async def reissue_current_subscription(
    user: CurrentUser,
    reissue_subscription: FromDishka[ReissueSubscription],
) -> ReissueResponse:
    try:
        await reissue_subscription(user)
    except CooldownError as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    return ReissueResponse(success=True)


@router.post("/promocode", response_model=PromocodeActivateResponse)
@inject
async def activate_promocode_web(
    body: PromocodeActivateRequest,
    user: CurrentUser,
    activate_promocode: FromDishka[ActivatePromocode],
) -> PromocodeActivateResponse:
    _assert_web_purchase_email_verified(user)
    try:
        promo = await activate_promocode(user, ActivatePromocodeDto(code=body.code, user=user))
    except PromocodeNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except (
        PromocodeExpiredError,
        PromocodeAlreadyActivatedError,
        PromocodeNotAvailableError,
    ) as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    return PromocodeActivateResponse(success=True, reward_type=promo.reward_type.value)


@router.post("/trial", response_model=TrialActivateResponse)
@inject
async def activate_trial_web(
    user: CurrentUser,
    settings_dao: FromDishka[SettingsDao],
    payment_gateway_dao: FromDishka[PaymentGatewayDao],
    pricing_service: FromDishka[PricingService],
    get_available_trial: FromDishka[GetAvailableTrial],
    activate_trial: FromDishka[ActivateTrialSubscription],
) -> TrialActivateResponse:
    _assert_web_purchase_email_verified(user)

    plan = await get_available_trial.system(user)
    if not plan or not plan.durations:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Trial is not available")

    duration = plan.durations[0]
    settings = await settings_dao.get()

    # Free trial: activate immediately, no payment required.
    if duration.get_price(settings.default_currency) == 0:
        plan_snapshot = PlanSnapshotDto.from_plan(plan, duration.days)
        try:
            await activate_trial.system(ActivateTrialSubscriptionDto(user=user, plan=plan_snapshot))
        except TrialNotAvailableError as e:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
        return TrialActivateResponse(
            is_free=True,
            activated=True,
            duration_days=duration.days,
        )

    # Paid trial: report the available gateways and their prices. The actual
    # payment is created via POST /trial/purchase once the user picks a gateway.
    active_gateways = await payment_gateway_dao.get_active()
    gateways: list[DurationGatewayPriceResponse] = []
    for gateway in active_gateways:
        if (
            gateway.type == PaymentGatewayType.TELEGRAM_STARS
            or not gateway.settings
            or not gateway.settings.is_configured
        ):
            continue

        pricing = pricing_service.calculate_for_duration(
            user,
            duration,
            gateway.currency,
            apply_discount=False,
        )
        gateways.append(
            DurationGatewayPriceResponse(
                gateway_type=gateway.type,
                currency=gateway.currency.value,
                currency_symbol=gateway.currency.symbol,
                original_amount=str(pricing.original_amount),
                discount_percent=pricing.discount_percent,
                final_amount=str(pricing.final_amount),
                is_free=pricing.is_free,
            )
        )

    return TrialActivateResponse(
        is_free=False,
        activated=False,
        duration_days=duration.days,
        gateways=gateways,
    )


@router.post("/trial/purchase", response_model=PaymentInitResponse)
@inject
async def purchase_trial_web(
    body: TrialPurchaseRequest,
    user: CurrentUser,
    settings_dao: FromDishka[SettingsDao],
    payment_gateway_dao: FromDishka[PaymentGatewayDao],
    pricing_service: FromDishka[PricingService],
    get_available_trial: FromDishka[GetAvailableTrial],
    create_payment: FromDishka[CreatePayment],
    process_payment: FromDishka[ProcessPayment],
) -> PaymentInitResponse:
    _assert_web_purchase_email_verified(user)
    await _validate_gateway_for_web(body.gateway_type, payment_gateway_dao)

    plan = await get_available_trial.system(user)
    if not plan or not plan.durations:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Trial is not available")

    duration = plan.durations[0]
    settings = await settings_dao.get()
    if duration.get_price(settings.default_currency) == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Trial is free, use POST /subscription/trial to activate it",
        )

    gateway = await payment_gateway_dao.get_by_type(body.gateway_type)
    if not gateway:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gateway not found")

    pricing = pricing_service.calculate_for_duration(
        user,
        duration,
        gateway.currency,
        apply_discount=False,
    )
    plan_snapshot = PlanSnapshotDto.from_plan(plan, duration.days)
    payment = await create_payment(
        user,
        CreatePaymentDto(
            plan_snapshot=plan_snapshot,
            pricing=pricing,
            purchase_type=PurchaseType.NEW,
            gateway_type=body.gateway_type,
        ),
    )

    tx_status = TransactionStatus.PENDING
    if pricing.is_free:
        await process_payment.system(
            ProcessPaymentDto(
                payment_id=payment.id,
                new_transaction_status=TransactionStatus.COMPLETED,
                gateway_type=body.gateway_type,
            ),
        )
        tx_status = TransactionStatus.COMPLETED

    return PaymentInitResponse(
        payment_id=str(payment.id),
        payment_url=payment.url,
        purchase_type=PurchaseType.NEW.value,
        status=tx_status.value,
        is_free=pricing.is_free,
        final_amount=str(pricing.final_amount),
        currency=gateway.currency.symbol,
    )


@router.post("/purchase", response_model=PaymentInitResponse)
@inject
async def purchase_subscription(
    body: PurchaseRequest,
    user: CurrentUser,
    subscription_dao: FromDishka[SubscriptionDao],
    payment_gateway_dao: FromDishka[PaymentGatewayDao],
    pricing_service: FromDishka[PricingService],
    get_available_plans: FromDishka[GetAvailablePlans],
    create_payment: FromDishka[CreatePayment],
    process_payment: FromDishka[ProcessPayment],
    idempotency: FromDishka[PaymentIdempotencyService],
    config: FromDishka[AppConfig],
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
) -> PaymentInitResponse:
    return_url = _validated_payment_return_url(body.return_url, config)
    payment_operation, replay = await _start_payment_operation(
        idempotency_key=idempotency_key,
        operation=_PURCHASE_OPERATION,
        body=body,
        user=user,
        idempotency=idempotency,
    )
    if replay is not None:
        return replay

    side_effect_started = False
    try:
        _assert_web_purchase_email_verified(user)
        await _validate_gateway_for_web(body.gateway_type, payment_gateway_dao)

        plan = await _get_available_plan_by_code(user, body.plan_code, get_available_plans)
        if not plan:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found")

        duration = plan.get_duration(body.duration_days)
        if not duration:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Plan duration not found",
            )

        gateway = await payment_gateway_dao.get_by_type(body.gateway_type)
        if not gateway:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gateway not found")

        current_subscription = await subscription_dao.get_current(user.id)
        purchase_type = PurchaseType.CHANGE if current_subscription else PurchaseType.NEW
        plan_snapshot = PlanSnapshotDto.from_plan(plan, duration.days)
        pricing = pricing_service.calculate(
            user,
            duration.get_price(gateway.currency),
            gateway.currency,
        )

        if payment_operation is not None:
            # CreatePayment persists all recovery snapshots and crosses the provider
            # boundary. From this point failures are reported fail-closed.
            side_effect_started = True

        payment = await create_payment(
            user,
            CreatePaymentDto(
                plan_snapshot=plan_snapshot,
                pricing=pricing,
                purchase_type=purchase_type,
                gateway_type=body.gateway_type,
                provider_idempotency_key=(
                    payment_operation.provider_key if payment_operation is not None else None
                ),
                payment_operation_id=(
                    payment_operation.operation_id if payment_operation is not None else None
                ),
                return_url=return_url,
            ),
        )

        tx_status = TransactionStatus.PENDING
        if pricing.is_free:
            await process_payment.system(
                ProcessPaymentDto(
                    payment_id=payment.id,
                    new_transaction_status=TransactionStatus.COMPLETED,
                    gateway_type=body.gateway_type,
                ),
            )
            tx_status = TransactionStatus.COMPLETED

        response = PaymentInitResponse(
            payment_id=str(payment.id),
            payment_url=payment.url,
            purchase_type=purchase_type.value,
            status=tx_status.value,
            is_free=pricing.is_free,
            final_amount=str(pricing.final_amount),
            currency=gateway.currency.symbol,
            return_url=return_url,
        )
        if payment_operation is not None and pricing.is_free:
            await idempotency.complete(
                payment_operation.operation_id,
                response.model_dump(mode="json"),
            )
        return response
    except BaseException as e:
        await _record_payment_operation_failure(
            idempotency=idempotency,
            payment_operation=payment_operation,
            side_effect_started=side_effect_started,
        )
        _raise_unknown_outcome_if_needed(payment_operation, side_effect_started, e)
        raise


@router.post("/extend", response_model=PaymentInitResponse)
@inject
async def extend_subscription(
    body: ExtendRequest,
    user: CurrentUser,
    payment_gateway_dao: FromDishka[PaymentGatewayDao],
    pricing_service: FromDishka[PricingService],
    get_renewal_plan_context: FromDishka[GetRenewalPlanContext],
    match_plan: FromDishka[MatchPlan],
    create_payment: FromDishka[CreatePayment],
    process_payment: FromDishka[ProcessPayment],
    idempotency: FromDishka[PaymentIdempotencyService],
    config: FromDishka[AppConfig],
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
) -> PaymentInitResponse:
    return_url = _validated_payment_return_url(body.return_url, config)
    payment_operation, replay = await _start_payment_operation(
        idempotency_key=idempotency_key,
        operation=_EXTEND_OPERATION,
        body=body,
        user=user,
        idempotency=idempotency,
    )
    if replay is not None:
        return replay

    side_effect_started = False
    try:
        _assert_web_purchase_email_verified(user)
        await _validate_gateway_for_web(body.gateway_type, payment_gateway_dao)

        renewal_context = await get_renewal_plan_context.system(user)
        current_subscription = renewal_context.current_subscription
        if not current_subscription:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Subscription not found",
            )

        available_plans = renewal_context.renewal_plans
        exact_match = await match_plan.system(
            MatchPlanDto(plan_snapshot=current_subscription.plan_snapshot, plans=available_plans)
        )
        matched_plan = resolve_renew_plan(
            current_subscription.plan_snapshot,
            available_plans,
            exact_match,
        ).plan
        if not matched_plan:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Matching plan for renewal is not available",
            )

        duration = matched_plan.get_duration(body.duration_days)
        if not duration:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Plan duration not found",
            )

        gateway = await payment_gateway_dao.get_by_type(body.gateway_type)
        if not gateway:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gateway not found")

        pricing = pricing_service.calculate(
            user,
            duration.get_price(gateway.currency),
            gateway.currency,
        )
        plan_snapshot = PlanSnapshotDto.from_plan(matched_plan, duration.days)

        if payment_operation is not None:
            side_effect_started = True

        payment = await create_payment(
            user,
            CreatePaymentDto(
                plan_snapshot=plan_snapshot,
                pricing=pricing,
                purchase_type=PurchaseType.RENEW,
                gateway_type=body.gateway_type,
                provider_idempotency_key=(
                    payment_operation.provider_key if payment_operation is not None else None
                ),
                payment_operation_id=(
                    payment_operation.operation_id if payment_operation is not None else None
                ),
                return_url=return_url,
            ),
        )

        tx_status = TransactionStatus.PENDING
        if pricing.is_free:
            await process_payment.system(
                ProcessPaymentDto(
                    payment_id=payment.id,
                    new_transaction_status=TransactionStatus.COMPLETED,
                    gateway_type=body.gateway_type,
                ),
            )
            tx_status = TransactionStatus.COMPLETED

        response = PaymentInitResponse(
            payment_id=str(payment.id),
            payment_url=payment.url,
            purchase_type=PurchaseType.RENEW.value,
            status=tx_status.value,
            is_free=pricing.is_free,
            final_amount=str(pricing.final_amount),
            currency=gateway.currency.symbol,
            return_url=return_url,
        )
        if payment_operation is not None and pricing.is_free:
            await idempotency.complete(
                payment_operation.operation_id,
                response.model_dump(mode="json"),
            )
        return response
    except BaseException as e:
        await _record_payment_operation_failure(
            idempotency=idempotency,
            payment_operation=payment_operation,
            side_effect_started=side_effect_started,
        )
        _raise_unknown_outcome_if_needed(payment_operation, side_effect_started, e)
        raise


@router.get("/offers", response_model=SubscriptionOffersResponse)
@inject
async def get_subscription_offers(
    user: CurrentUser,
    payment_gateway_dao: FromDishka[PaymentGatewayDao],
    pricing_service: FromDishka[PricingService],
    get_renewal_plan_context: FromDishka[GetRenewalPlanContext],
    match_plan: FromDishka[MatchPlan],
) -> SubscriptionOffersResponse:
    active_gateways = await payment_gateway_dao.get_active()
    web_gateways = [
        gateway
        for gateway in active_gateways
        if gateway.type != PaymentGatewayType.TELEGRAM_STARS
        and gateway.settings
        and gateway.settings.is_configured
    ]

    renewal_context = await get_renewal_plan_context.system(user)
    available_plans = renewal_context.available_plans
    renewal_plans = renewal_context.renewal_plans
    current_subscription = renewal_context.current_subscription

    matched_plan: Optional[PlanDto] = None
    renewal_terms_changed = False
    if current_subscription:
        exact_match = await match_plan.system(
            MatchPlanDto(
                plan_snapshot=current_subscription.plan_snapshot,
                plans=renewal_plans,
            )
        )
        resolution = resolve_renew_plan(
            current_subscription.plan_snapshot,
            renewal_plans,
            exact_match,
        )
        matched_plan = resolution.plan
        renewal_terms_changed = resolution.terms_changed

    plan_offers: list[PlanOfferResponse] = []
    for plan in available_plans:
        if not plan.public_code:
            continue

        duration_offers: list[DurationOfferResponse] = []
        for duration in plan.durations:
            prices: list[DurationGatewayPriceResponse] = []
            for gateway in web_gateways:
                pricing = pricing_service.calculate(
                    user=user,
                    price=duration.get_price(gateway.currency),
                    currency=gateway.currency,
                )
                prices.append(
                    DurationGatewayPriceResponse(
                        gateway_type=gateway.type,
                        currency=gateway.currency.value,
                        currency_symbol=gateway.currency.symbol,
                        original_amount=str(pricing.original_amount),
                        discount_percent=pricing.discount_percent,
                        final_amount=str(pricing.final_amount),
                        is_free=pricing.is_free,
                    )
                )

            duration_offers.append(DurationOfferResponse(days=duration.days, prices=prices))

        is_renew_candidate = (
            current_subscription is not None
            and matched_plan is not None
            and matched_plan.id == plan.id
            and not current_subscription.is_unlimited
        )
        recommended_purchase_type = (
            PurchaseType.RENEW.value
            if is_renew_candidate
            else (PurchaseType.CHANGE.value if current_subscription else PurchaseType.NEW.value)
        )

        plan_offers.append(
            PlanOfferResponse(
                id=plan.id,
                public_code=plan.public_code,
                name=plan.name,
                description=plan.description,
                traffic_limit=plan.traffic_limit,
                device_limit=plan.device_limit,
                type=plan.type.value,
                recommended_purchase_type=recommended_purchase_type,
                renewal_terms_changed=(
                    renewal_terms_changed
                    if is_renew_candidate
                    else False
                ),
                durations=duration_offers,
            )
        )

    gateway_offers = [
        GatewayOfferResponse(
            gateway_type=gateway.type,
            currency=gateway.currency.value,
            currency_symbol=gateway.currency.symbol,
        )
        for gateway in web_gateways
    ]

    return SubscriptionOffersResponse(
        gateways=gateway_offers,
        plans=plan_offers,
        has_current_subscription=bool(current_subscription),
        current_subscription_status=(
            current_subscription.current_status.value if current_subscription else None
        ),
    )
