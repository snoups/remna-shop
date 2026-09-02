from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import orjson
import pytest

from src.core.enums import Currency
from src.infrastructure.payment_gateways.yookassa import YookassaGateway


class FakeResponse:
    def __init__(self, payment_id: str) -> None:
        self.content = orjson.dumps(
            {
                "id": payment_id,
                "status": "pending",
                "confirmation": {"confirmation_url": "https://payment.example/confirm"},
            }
        )

    def raise_for_status(self) -> None:
        return None


class FakeClient:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.headers: list[dict[str, str]] = []

    async def post(self, *args: Any, **kwargs: Any) -> FakeResponse:
        self.headers.append(kwargs["headers"])
        return self.response


@pytest.mark.asyncio
async def test_yookassa_uses_durable_provider_key() -> None:
    gateway = object.__new__(YookassaGateway)
    client = FakeClient(FakeResponse(str(uuid4())))
    gateway._client = client
    gateway._create_payment_payload = AsyncMock(return_value={})  # type: ignore[method-assign]

    await gateway.create_payment(
        Decimal("100"),
        "Subscription",
        idempotency_key="durable-provider-key",
    )
    await gateway.create_payment(
        Decimal("100"),
        "Subscription",
        idempotency_key="durable-provider-key",
    )

    assert client.headers == [
        {"Idempotence-Key": "durable-provider-key"},
        {"Idempotence-Key": "durable-provider-key"},
    ]


@pytest.mark.asyncio
async def test_yookassa_uses_explicit_web_return_url() -> None:
    gateway = object.__new__(YookassaGateway)
    gateway.data = SimpleNamespace(
        currency=Currency.RUB,
        settings=SimpleNamespace(customer="buyer@example.com", vat_code=1),
    )
    gateway._get_bot_redirect_url = AsyncMock(  # type: ignore[method-assign]
        return_value="https://t.me/remnashop_bot"
    )

    payload = await gateway._create_payment_payload(
        "100.00",
        "Subscription",
        return_url="https://cabinet.example/payment/pending?operation_id=op-1",
    )

    assert payload["confirmation"] == {
        "type": "redirect",
        "return_url": "https://cabinet.example/payment/pending?operation_id=op-1",
    }
    gateway._get_bot_redirect_url.assert_not_awaited()
