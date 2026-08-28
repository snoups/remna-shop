from typing import Optional

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, HTTPException, status
from remnapy.models.hwid import HwidDeviceDto

from src.application.common import Remnawave
from src.application.common.dao import (
    PaymentGatewayDao,
    SettingsDao,
    SubscriptionDao,
)
from src.application.dto import PlanDto, PlanSnapshotDto, UserDto
from src.application.services import PricingService
from src.application.use_cases.gateways.commands.payment import (
    CreatePayment,
    CreatePaymentDto,
    ProcessPayment,
    ProcessPaymentDto,
)
from src.application.use_cases.plan.queries.match import MatchPlan, MatchPlanDto
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
    PlanOfferResponse,
    PromocodeActivateRequest,
    PromocodeActivateResponse,
    PurchaseRequest,
    ReissueResponse,
    SubscriptionInfoResponse,
    SubscriptionOffersResponse,
    TrialActivateResponse,
    TrialPurchaseRequest,
)

from ._common import CurrentUser

router = APIRouter(prefix="/subscription", tags=["Public - Subscription"])


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

    remna_user = await remnawave.get_user_by_id(current_subscription.user_remna_id)

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
) -> PaymentInitResponse:
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

    payment = await create_payment(
        user,
        CreatePaymentDto(
            plan_snapshot=plan_snapshot,
            pricing=pricing,
            purchase_type=purchase_type,
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
        purchase_type=purchase_type.value,
        status=tx_status.value,
        is_free=pricing.is_free,
        final_amount=str(pricing.final_amount),
        currency=gateway.currency.symbol,
    )


@router.post("/extend", response_model=PaymentInitResponse)
@inject
async def extend_subscription(
    body: ExtendRequest,
    user: CurrentUser,
    subscription_dao: FromDishka[SubscriptionDao],
    payment_gateway_dao: FromDishka[PaymentGatewayDao],
    pricing_service: FromDishka[PricingService],
    get_available_plans: FromDishka[GetAvailablePlans],
    match_plan: FromDishka[MatchPlan],
    create_payment: FromDishka[CreatePayment],
    process_payment: FromDishka[ProcessPayment],
) -> PaymentInitResponse:
    _assert_web_purchase_email_verified(user)
    await _validate_gateway_for_web(body.gateway_type, payment_gateway_dao)

    current_subscription = await subscription_dao.get_current(user.id)
    if not current_subscription:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found")

    available_plans = await get_available_plans.system(user)
    matched_plan = await match_plan.system(
        MatchPlanDto(plan_snapshot=current_subscription.plan_snapshot, plans=available_plans)
    )
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
    payment = await create_payment(
        user,
        CreatePaymentDto(
            plan_snapshot=plan_snapshot,
            pricing=pricing,
            purchase_type=PurchaseType.RENEW,
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
        purchase_type=PurchaseType.RENEW.value,
        status=tx_status.value,
        is_free=pricing.is_free,
        final_amount=str(pricing.final_amount),
        currency=gateway.currency.symbol,
    )


@router.get("/offers", response_model=SubscriptionOffersResponse)
@inject
async def get_subscription_offers(
    user: CurrentUser,
    subscription_dao: FromDishka[SubscriptionDao],
    payment_gateway_dao: FromDishka[PaymentGatewayDao],
    pricing_service: FromDishka[PricingService],
    get_available_plans: FromDishka[GetAvailablePlans],
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

    available_plans = await get_available_plans.system(user)
    current_subscription = await subscription_dao.get_current(user.id)

    matched_plan: Optional[PlanDto] = None
    if current_subscription:
        matched_plan = await match_plan.system(
            MatchPlanDto(
                plan_snapshot=current_subscription.plan_snapshot,
                plans=available_plans,
            )
        )

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
