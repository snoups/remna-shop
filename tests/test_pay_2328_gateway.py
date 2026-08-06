import base64
import hashlib
import hmac
from typing import Any
from uuid import UUID, uuid4

import orjson
import pytest
from pydantic import SecretStr
from starlette.requests import Request

from src.application.dto.payment_gateway import (
    Pay2328GatewaySettingsDto,
    PaymentGatewayDto,
)
from src.application.use_cases.gateways.commands.payment import CreateDefaultPaymentGateway
from src.core.enums import Currency, PaymentGatewayType, TransactionStatus
from src.infrastructure.payment_gateways.pay_2328 import Pay2328Gateway


API_KEY = "test-api-key"


def make_gateway() -> Pay2328Gateway:
    gateway = object.__new__(Pay2328Gateway)
    gateway.data = PaymentGatewayDto(
        type=PaymentGatewayType.PAY_2328,
        currency=Currency.RUB,
        settings=Pay2328GatewaySettingsDto(
            project_uuid="00000000-0000-0000-0000-000000000001",
            api_key=SecretStr(API_KEY),
        ),
    )
    return gateway


def make_request(payload: dict[str, Any]) -> Request:
    body = orjson.dumps(payload)
    sent = False

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "query_string": b"",
            "headers": [],
        },
        receive,
    )


def sign(payload: dict[str, Any]) -> str:
    encoded = base64.b64encode(orjson.dumps(payload))
    return hmac.new(API_KEY.encode(), encoded, hashlib.sha256).hexdigest()


def test_sign_uses_base64_encoded_compact_json() -> None:
    gateway = make_gateway()
    body = orjson.dumps({"amount": "100", "currency": "RUB"})

    expected = hmac.new(
        API_KEY.encode(),
        base64.b64encode(body),
        hashlib.sha256,
    ).hexdigest()

    assert gateway._sign(body) == expected


@pytest.mark.parametrize("status", ["paid", "overpaid"])
async def test_success_webhook_statuses(status: str) -> None:
    gateway = make_gateway()
    payment_id = uuid4()
    unsigned = {"uuid": str(payment_id), "payment_status": status}
    request = make_request({**unsigned, "sign": sign(unsigned)})

    result = await gateway.handle_webhook(request)

    assert result == (payment_id, TransactionStatus.COMPLETED)


@pytest.mark.parametrize("status", ["pending", "check", "underpaid_check"])
async def test_pending_webhook_statuses_are_ignored(status: str) -> None:
    gateway = make_gateway()
    unsigned = {"uuid": str(uuid4()), "payment_status": status}
    request = make_request({**unsigned, "sign": sign(unsigned)})

    assert await gateway.handle_webhook(request) is None


@pytest.mark.parametrize("status", ["underpaid", "cancel", "aml_lock"])
async def test_unsuccessful_webhook_statuses_are_canceled(status: str) -> None:
    gateway = make_gateway()
    payment_id = uuid4()
    unsigned = {"uuid": str(payment_id), "payment_status": status}
    request = make_request({**unsigned, "sign": sign(unsigned)})

    result = await gateway.handle_webhook(request)

    assert result == (payment_id, TransactionStatus.CANCELED)


async def test_invalid_webhook_signature_is_rejected() -> None:
    gateway = make_gateway()
    request = make_request(
        {
            "uuid": str(UUID(int=1)),
            "payment_status": "paid",
            "sign": "invalid",
        }
    )

    with pytest.raises(PermissionError, match="verification failed"):
        await gateway.handle_webhook(request)


class FakeUnitOfWork:
    async def __aenter__(self) -> "FakeUnitOfWork":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def commit(self) -> None:
        return None


class FakePaymentGatewayDao:
    def __init__(self) -> None:
        self.created: list[PaymentGatewayDto] = []

    async def get_by_type(self, gateway_type: PaymentGatewayType) -> object | None:
        if gateway_type == PaymentGatewayType.PAY_2328:
            return None
        return object()

    async def create(self, gateway: PaymentGatewayDto) -> PaymentGatewayDto:
        self.created.append(gateway)
        return gateway

    async def get_all(self) -> list[PaymentGatewayDto]:
        return self.created

    async def update(self, gateway: PaymentGatewayDto) -> PaymentGatewayDto:
        return gateway


async def test_default_gateway_bootstrap_creates_typed_2328_settings() -> None:
    dao = FakePaymentGatewayDao()
    interactor = CreateDefaultPaymentGateway(FakeUnitOfWork(), dao)  # type: ignore[arg-type]

    await interactor._execute(None, None)  # type: ignore[arg-type]

    assert len(dao.created) == 1
    gateway = dao.created[0]
    assert gateway.type == PaymentGatewayType.PAY_2328
    assert isinstance(gateway.settings, Pay2328GatewaySettingsDto)
    assert gateway.settings.ttl_seconds == 3600
    assert gateway.settings.is_configured is False
