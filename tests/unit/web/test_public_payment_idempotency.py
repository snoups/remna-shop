from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response, status

from src.application.common.dao.payment_operation import PaymentOperationOwnerMergedError
from src.application.dto import PaymentResultDto, PriceDetailsDto
from src.application.services.payment_idempotency import PaymentOperationStart
from src.application.services.payment_reconciliation import (
    PaymentOperationPublicState,
    PaymentOperationView,
)
from src.application.use_cases.plan.queries.renewal import GetRenewalPlanContext
from src.application.use_cases.user.queries.plans import GetAvailablePlans
from src.core.enums import Currency, PaymentGatewayType, PlanAvailability
from src.core.utils.time import datetime_now
from src.web.endpoints.admin.payment_operations import (
    reconcile_payment_operation_admin,
)
from src.web.endpoints.public.subscription import (
    _set_operation_http_status,
    extend_subscription,
    get_subscription_offers,
    purchase_subscription,
    reconcile_payment_operation,
    router,
)
from src.web.schemas import (
    ExtendRequest,
    PaymentInitResponse,
    PaymentOperationResponse,
    PaymentTransactionResponse,
    PurchaseRequest,
    SubscriptionCapabilitiesResponse,
)


class FakePaymentIdempotency:
    def __init__(self) -> None:
        self.response: Optional[dict[str, Any]] = None
        self.started = PaymentOperationStart(operation_id=1, provider_key="provider-key-1")
        self.unknown_calls = 0
        self.abandon_calls = 0
        self.complete_calls = 0

    async def start(self, **kwargs: Any) -> PaymentOperationStart:
        if self.response is None:
            return self.started
        return PaymentOperationStart(
            operation_id=self.started.operation_id,
            provider_key=self.started.provider_key,
            replay_response=self.response,
        )

    async def mark_processing(self, operation_id: int) -> None:
        return None

    async def complete(self, operation_id: int, response: dict[str, Any]) -> None:
        self.complete_calls += 1
        self.response = response

    async def mark_unknown(self, operation_id: int) -> None:
        self.unknown_calls += 1

    async def abandon(self, operation_id: int) -> None:
        self.abandon_calls += 1


def build_purchase_call(
    monkeypatch: Any,
    create_payment: AsyncMock,
    idempotency_key: Optional[str],
    *,
    is_free: bool = True,
) -> tuple[Any, dict[str, Any], Any, FakePaymentIdempotency]:
    amount = Decimal(0) if is_free else Decimal(100)
    duration = SimpleNamespace(days=30, get_price=lambda currency: amount)
    plan = SimpleNamespace(
        public_code="basic",
        get_duration=lambda days: duration if days == 30 else None,
    )
    gateway = SimpleNamespace(
        type=PaymentGatewayType.YOOKASSA,
        currency=Currency.RUB,
        is_active=True,
        settings=SimpleNamespace(is_configured=True),
    )
    process_payment = SimpleNamespace(system=AsyncMock())
    idempotency = FakePaymentIdempotency()
    monkeypatch.setattr(
        "src.web.endpoints.public.subscription.PlanSnapshotDto.from_plan",
        lambda plan, days: SimpleNamespace(id=1, duration=days),
    )
    handler = purchase_subscription.__dishka_orig_func__  # type: ignore[attr-defined]
    kwargs = {
        "body": PurchaseRequest(
            plan_code="basic",
            duration_days=30,
            gateway_type=PaymentGatewayType.YOOKASSA,
        ),
        "user": SimpleNamespace(id=7, is_email_verified=True),
        "subscription_dao": SimpleNamespace(get_current=AsyncMock(return_value=None)),
        "payment_gateway_dao": SimpleNamespace(get_by_type=AsyncMock(return_value=gateway)),
        "pricing_service": SimpleNamespace(
            calculate=lambda *args, **kwargs: PriceDetailsDto(
                original_amount=amount,
                discount_percent=0,
                final_amount=amount,
            )
        ),
        "get_available_plans": SimpleNamespace(system=AsyncMock(return_value=[plan])),
        "create_payment": create_payment,
        "process_payment": process_payment,
        "idempotency": idempotency,
        "config": SimpleNamespace(web_cabinet_url="https://cabinet.example/auth/telegram/webapp"),
        "idempotency_key": idempotency_key,
    }
    return handler, kwargs, process_payment, idempotency


def build_extend_call(
    monkeypatch: Any,
    create_payment: AsyncMock,
    idempotency_key: str,
) -> tuple[Any, dict[str, Any], Any, FakePaymentIdempotency]:
    amount = Decimal(100)
    duration = SimpleNamespace(days=30, get_price=lambda currency: amount)
    plan = SimpleNamespace(id=1, get_duration=lambda days: duration if days == 30 else None)
    gateway = SimpleNamespace(
        type=PaymentGatewayType.YOOKASSA,
        currency=Currency.RUB,
        is_active=True,
        settings=SimpleNamespace(is_configured=True),
    )
    process_payment = SimpleNamespace(system=AsyncMock())
    idempotency = FakePaymentIdempotency()
    monkeypatch.setattr(
        "src.web.endpoints.public.subscription.PlanSnapshotDto.from_plan",
        lambda plan, days: SimpleNamespace(id=1, duration=days),
    )
    handler = extend_subscription.__dishka_orig_func__  # type: ignore[attr-defined]
    kwargs = {
        "body": ExtendRequest(
            duration_days=30,
            gateway_type=PaymentGatewayType.YOOKASSA,
        ),
        "user": SimpleNamespace(id=7, is_email_verified=True),
        "get_renewal_plan_context": SimpleNamespace(
            system=AsyncMock(
                return_value=SimpleNamespace(
                    current_subscription=SimpleNamespace(plan_snapshot=SimpleNamespace(id=1)),
                    available_plans=[plan],
                    renewal_plans=[plan],
                )
            )
        ),
        "payment_gateway_dao": SimpleNamespace(get_by_type=AsyncMock(return_value=gateway)),
        "pricing_service": SimpleNamespace(
            calculate=lambda *args, **kwargs: PriceDetailsDto(
                original_amount=amount,
                discount_percent=0,
                final_amount=amount,
            )
        ),
        "match_plan": SimpleNamespace(system=AsyncMock(return_value=plan)),
        "create_payment": create_payment,
        "process_payment": process_payment,
        "idempotency": idempotency,
        "config": SimpleNamespace(web_cabinet_url="https://cabinet.example/auth/telegram/webapp"),
        "idempotency_key": idempotency_key,
    }
    return handler, kwargs, process_payment, idempotency


@pytest.mark.asyncio
async def test_extend_uses_updated_plan_terms_when_snapshot_id_still_exists(
    monkeypatch: Any,
) -> None:
    create_payment = AsyncMock(
        return_value=PaymentResultDto(
            id=uuid4(),
            url="https://payments.example/confirmation",
        )
    )
    handler, kwargs, _, _ = build_extend_call(
        monkeypatch,
        create_payment,
        "request-key-modified-plan-0001",
    )
    kwargs["match_plan"].system.return_value = None

    response = await handler(**kwargs)

    assert response.status == "PENDING"
    create_payment.assert_awaited_once()


@pytest.mark.asyncio
async def test_extend_rejects_snapshot_when_plan_id_is_no_longer_available(
    monkeypatch: Any,
) -> None:
    create_payment = AsyncMock()
    handler, kwargs, _, _ = build_extend_call(
        monkeypatch,
        create_payment,
        "request-key-removed-plan-0001",
    )
    renewal_context = kwargs["get_renewal_plan_context"].system.return_value
    renewal_context.current_subscription.plan_snapshot.id = 2
    kwargs["match_plan"].system.return_value = None

    with pytest.raises(HTTPException) as raised:
        await handler(**kwargs)

    assert raised.value.status_code == status.HTTP_409_CONFLICT
    create_payment.assert_not_awaited()


@pytest.mark.asyncio
async def test_offers_mark_same_id_modified_plan_as_renewal_with_warning() -> None:
    amount = Decimal(100)
    duration = SimpleNamespace(days=30, get_price=lambda currency: amount)
    plan = SimpleNamespace(
        id=1,
        public_code="basic",
        name="Basic",
        description=None,
        traffic_limit=100,
        device_limit=5,
        type=SimpleNamespace(value="BOTH"),
        durations=[duration],
    )
    gateway = SimpleNamespace(
        type=PaymentGatewayType.YOOKASSA,
        currency=Currency.RUB,
        settings=SimpleNamespace(is_configured=True),
    )
    current = SimpleNamespace(
        plan_snapshot=SimpleNamespace(id=1),
        current_status=SimpleNamespace(value="ACTIVE"),
        is_unlimited=False,
    )
    handler = get_subscription_offers.__dishka_orig_func__  # type: ignore[attr-defined]

    response = await handler(
        user=SimpleNamespace(id=7),
        payment_gateway_dao=SimpleNamespace(get_active=AsyncMock(return_value=[gateway])),
        pricing_service=SimpleNamespace(
            calculate=lambda *args, **kwargs: PriceDetailsDto(
                original_amount=amount,
                discount_percent=0,
                final_amount=amount,
            )
        ),
        get_renewal_plan_context=SimpleNamespace(
            system=AsyncMock(
                return_value=SimpleNamespace(
                    current_subscription=current,
                    available_plans=[plan],
                    renewal_plans=[plan],
                )
            )
        ),
        match_plan=SimpleNamespace(system=AsyncMock(return_value=None)),
    )

    assert response.plans[0].recommended_purchase_type == "RENEW"
    assert response.plans[0].renewal_terms_changed is True


@pytest.mark.asyncio
async def test_offers_do_not_expose_grandfathered_or_unrelated_new_plans() -> None:
    amount = Decimal(100)
    duration = SimpleNamespace(days=30, get_price=lambda currency: amount)

    def plan(plan_id: int, availability: PlanAvailability) -> SimpleNamespace:
        return SimpleNamespace(
            id=plan_id,
            public_code=f"plan-{plan_id}",
            name=f"Plan {plan_id}",
            description=None,
            traffic_limit=100,
            device_limit=5,
            type=SimpleNamespace(value="BOTH"),
            durations=[duration],
            availability=availability,
            is_active=True,
            allowed_telegram_ids=[],
            allowed_emails=[],
        )

    current_new_plan = plan(3, PlanAvailability.NEW)
    unrelated_new_plan = plan(4, PlanAvailability.NEW)
    regular_plan = plan(8, PlanAvailability.ALL)
    user = SimpleNamespace(
        id=7,
        telegram_id=7,
        email=None,
        log="[USER:7]",
    )
    current = SimpleNamespace(
        user_id=user.id,
        is_active=True,
        plan_snapshot=SimpleNamespace(id=current_new_plan.id),
        current_status=SimpleNamespace(value="ACTIVE"),
        is_unlimited=False,
    )
    user_dao = SimpleNamespace(
        has_any_subscription=AsyncMock(return_value=True),
        is_invited_user=AsyncMock(return_value=False),
    )
    plan_dao = SimpleNamespace(
        get_active_plans=AsyncMock(
            return_value=[current_new_plan, unrelated_new_plan, regular_plan]
        ),
        get_by_id=AsyncMock(return_value=current_new_plan),
    )
    get_available_plans = GetAvailablePlans(user_dao, plan_dao)  # type: ignore[arg-type]
    get_renewal_plan_context = GetRenewalPlanContext(  # type: ignore[arg-type]
        SimpleNamespace(get_current=AsyncMock(return_value=current)),
        plan_dao,
        get_available_plans,
    )
    match_plan = SimpleNamespace(system=AsyncMock(return_value=current_new_plan))
    gateway = SimpleNamespace(
        type=PaymentGatewayType.YOOKASSA,
        currency=Currency.RUB,
        settings=SimpleNamespace(is_configured=True),
    )
    handler = get_subscription_offers.__dishka_orig_func__  # type: ignore[attr-defined]

    response = await handler(
        user=user,
        payment_gateway_dao=SimpleNamespace(get_active=AsyncMock(return_value=[gateway])),
        pricing_service=SimpleNamespace(
            calculate=lambda *args, **kwargs: PriceDetailsDto(
                original_amount=amount,
                discount_percent=0,
                final_amount=amount,
            )
        ),
        get_renewal_plan_context=get_renewal_plan_context,
        match_plan=match_plan,
    )

    match_request = match_plan.system.await_args.args[0]
    assert [candidate.id for candidate in match_request.plans] == [
        regular_plan.id,
        current_new_plan.id,
    ]
    assert [offer.id for offer in response.plans] == [regular_plan.id]
    assert current_new_plan.id not in [offer.id for offer in response.plans]
    assert unrelated_new_plan.id not in [offer.id for offer in response.plans]


@pytest.mark.asyncio
async def test_free_purchase_is_fulfilled_once_and_then_replayed(monkeypatch: Any) -> None:
    payment = PaymentResultDto(id=uuid4(), url=None)
    create_payment = AsyncMock(return_value=payment)
    handler, kwargs, process_payment, _ = build_purchase_call(
        monkeypatch,
        create_payment,
        "request-key-free-0001",
    )

    first = await handler(**kwargs)
    second = await handler(**kwargs)

    assert isinstance(first, PaymentInitResponse)
    assert second == first
    assert first.is_free is True
    assert first.status == "COMPLETED"
    assert create_payment.await_count == 1
    assert process_payment.system.await_count == 1


@pytest.mark.asyncio
async def test_web_purchase_forwards_and_echoes_validated_return_url(monkeypatch: Any) -> None:
    payment = PaymentResultDto(id=uuid4(), url="https://payments.example/confirmation")
    create_payment = AsyncMock(return_value=payment)
    handler, kwargs, _, _ = build_purchase_call(
        monkeypatch,
        create_payment,
        "request-key-return-0001",
        is_free=False,
    )
    return_url = "https://cabinet.example/payment/pending?operation_id=clean-op-1"
    kwargs["body"] = PurchaseRequest(
        plan_code="basic",
        duration_days=30,
        gateway_type=PaymentGatewayType.YOOKASSA,
        return_url=return_url,
    )

    response = await handler(**kwargs)

    assert response.return_url == return_url
    payment_dto = create_payment.await_args.args[1]
    assert payment_dto.return_url == return_url


@pytest.mark.asyncio
async def test_web_purchase_rejects_untrusted_return_url(monkeypatch: Any) -> None:
    create_payment = AsyncMock()
    handler, kwargs, _, _ = build_purchase_call(
        monkeypatch,
        create_payment,
        "request-key-return-0002",
        is_free=False,
    )
    kwargs["body"] = PurchaseRequest(
        plan_code="basic",
        duration_days=30,
        gateway_type=PaymentGatewayType.YOOKASSA,
        return_url="https://attacker.example/payment/success",
    )

    with pytest.raises(HTTPException) as exc:
        await handler(**kwargs)

    assert exc.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    create_payment.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["purchase", "extend"])
async def test_paid_operation_is_not_completed_twice_and_replays_stably(
    monkeypatch: Any,
    operation: str,
) -> None:
    payment = PaymentResultDto(
        id=uuid4(),
        url="https://payments.example/confirmation",
    )
    create_payment = AsyncMock(return_value=payment)
    if operation == "purchase":
        handler, kwargs, process_payment, idempotency = build_purchase_call(
            monkeypatch,
            create_payment,
            f"request-key-paid-{operation}-0001",
            is_free=False,
        )
    else:
        handler, kwargs, process_payment, idempotency = build_extend_call(
            monkeypatch,
            create_payment,
            f"request-key-paid-{operation}-0001",
        )

    first = await handler(**kwargs)
    assert first.status == "PENDING"
    assert first.is_free is False
    assert idempotency.complete_calls == 0
    assert process_payment.system.await_count == 0

    # Real CreatePayment stores this exact response atomically with the transaction.
    idempotency.response = first.model_dump(mode="json")
    second = await handler(**kwargs)

    assert second == first
    assert create_payment.await_count == 1
    assert idempotency.complete_calls == 0


@pytest.mark.asyncio
async def test_error_after_side_effect_boundary_is_stable_unknown_409(monkeypatch: Any) -> None:
    create_payment = AsyncMock(
        side_effect=HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="provider rejected request",
        )
    )
    handler, kwargs, _, idempotency = build_purchase_call(
        monkeypatch,
        create_payment,
        "request-key-error-0001",
    )

    with pytest.raises(HTTPException) as raised:
        await handler(**kwargs)

    assert raised.value.status_code == status.HTTP_409_CONFLICT
    assert "payment outcome is unknown" in raised.value.detail.lower()
    assert idempotency.unknown_calls == 1


@pytest.mark.asyncio
async def test_legacy_request_preserves_original_error(monkeypatch: Any) -> None:
    create_payment = AsyncMock(
        side_effect=HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="provider rejected request",
        )
    )
    handler, kwargs, _, idempotency = build_purchase_call(monkeypatch, create_payment, None)

    with pytest.raises(HTTPException) as raised:
        await handler(**kwargs)

    assert raised.value.status_code == status.HTTP_400_BAD_REQUEST
    assert raised.value.detail == "provider rejected request"
    assert idempotency.unknown_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("admin", [False, True])
async def test_reconciliation_merge_race_is_deterministic_conflict(admin: bool) -> None:
    reconciliation = SimpleNamespace(
        reconcile=AsyncMock(side_effect=PaymentOperationOwnerMergedError())
    )
    response = Response()

    with pytest.raises(HTTPException) as raised:
        if admin:
            handler = reconcile_payment_operation_admin.__dishka_orig_func__  # type: ignore[attr-defined]
            await handler(
                operation="purchase",
                response=response,
                reconciliation=reconciliation,
                user_id=7,
                idempotency_key="request-key-merge-race-0001",
                _=None,
            )
        else:
            handler = reconcile_payment_operation.__dishka_orig_func__  # type: ignore[attr-defined]
            await handler(
                operation="purchase",
                response=response,
                user=SimpleNamespace(id=7),
                reconciliation=reconciliation,
                idempotency_key="request-key-merge-race-0001",
            )

    assert raised.value.status_code == status.HTTP_409_CONFLICT


def test_payment_operation_contract_uses_same_path_for_lookup_and_reconcile() -> None:
    path = "/subscription/payment-operations/{operation}"
    methods = {
        method
        for route in router.routes
        if getattr(route, "path", None) == path
        for method in getattr(route, "methods", set())
    }

    assert methods == {"GET", "POST"}


def test_payment_operation_contract_preserves_currency_symbol() -> None:
    payment_id = str(uuid4())
    payment = PaymentInitResponse(
        payment_id=payment_id,
        payment_url="https://payments.example/confirmation",
        purchase_type="NEW",
        status="PENDING",
        is_free=False,
        final_amount="100",
        currency=Currency.RUB.symbol,
    )
    now = datetime_now()
    transaction = PaymentTransactionResponse(
        payment_id=payment_id,
        purchase_type="NEW",
        status="PENDING",
        gateway_type=PaymentGatewayType.YOOKASSA,
        final_amount="100",
        currency=Currency.RUB.symbol,
        created_at=now,
        updated_at=now,
    )
    response = PaymentOperationResponse(
        operation="PURCHASE",
        state="SUCCEEDED",
        payment=payment,
        transaction=transaction,
        retry_after_seconds=None,
    )

    assert response.model_dump(mode="json")["payment"]["currency"] == "₽"


@pytest.mark.parametrize(
    ("state", "retry_after", "expected_status", "expected_header"),
    [
        (PaymentOperationPublicState.SUCCEEDED, None, 200, None),
        (PaymentOperationPublicState.IN_PROGRESS, 2, 202, "2"),
        (PaymentOperationPublicState.UNKNOWN, 300, 202, "300"),
        (PaymentOperationPublicState.MANUAL_REQUIRED, None, 202, None),
    ],
)
def test_payment_operation_state_controls_body_and_retry_header(
    state: PaymentOperationPublicState,
    retry_after: Optional[int],
    expected_status: int,
    expected_header: Optional[str],
) -> None:
    payment = (
        PaymentInitResponse(
            payment_id=str(uuid4()),
            payment_url=None,
            purchase_type="NEW",
            status="PENDING",
            is_free=False,
            final_amount="100",
            currency=Currency.RUB.symbol,
        )
        if state == PaymentOperationPublicState.SUCCEEDED
        else None
    )
    now = datetime_now()
    transaction = (
        PaymentTransactionResponse(
            payment_id=payment.payment_id,
            purchase_type="NEW",
            status="PENDING",
            gateway_type=PaymentGatewayType.YOOKASSA,
            final_amount="100",
            currency=Currency.RUB.symbol,
            created_at=now,
            updated_at=now,
        )
        if payment
        else None
    )
    payload = PaymentOperationResponse(
        operation="PURCHASE",
        state=state.value,
        payment=payment,
        transaction=transaction,
        retry_after_seconds=retry_after,
    )
    response = Response()
    view = PaymentOperationView(
        operation="PURCHASE",
        state=state,
        payment=payment.model_dump(mode="json") if payment else None,
        transaction=None,
        retry_after_seconds=retry_after,
    )

    _set_operation_http_status(response, view)

    assert payload.retry_after_seconds == retry_after
    assert response.status_code == expected_status
    assert response.headers.get("Retry-After") == expected_header


def test_capabilities_publish_bounded_reconciliation_contract() -> None:
    capabilities = SubscriptionCapabilitiesResponse().model_dump(mode="json")

    assert capabilities["contract_version"] == 1
    assert capabilities["transactions"] == {
        "keyset_pagination": True,
        "exact_lookup": True,
        "max_page_size": 100,
    }
    assert capabilities["payment_reconciliation"]["states"] == [
        "SUCCEEDED",
        "IN_PROGRESS",
        "UNKNOWN",
        "MANUAL_REQUIRED",
    ]
    assert capabilities["payment_reconciliation"]["auto_replay_gateways"] == ["YOOKASSA"]
