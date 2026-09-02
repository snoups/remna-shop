from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import AsyncMock
from uuid import UUID

import orjson
import pytest
from starlette.requests import Request

from src.core.enums import PaymentGatewayType, TransactionStatus
from src.infrastructure.payment_gateways.platega import PlategaGateway
from src.infrastructure.taskiq.tasks.payments import handle_payment_transaction_task
from src.web.endpoints.payments import _process_payment_webhook


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
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.events: list[dict[str, Any]] = []

    async def store_webhook_event(self, **kwargs: Any) -> None:
        if self.fail:
            raise RuntimeError("database unavailable")
        self.events.append(kwargs)


def signed_request(payment_method: Any) -> Request:
    body = orjson.dumps(
        {
            "id": "00000000-0000-0000-0000-000000000888",
            "status": "CONFIRMED",
            "paymentMethod": payment_method,
        }
    )
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
            "path": "/api/v1/payments/platega",
            "headers": [
                (b"x-merchantid", b"merchant"),
                (b"x-secret", b"secret"),
            ],
        },
        receive,
    )


def gateway() -> PlategaGateway:
    result = object.__new__(PlategaGateway)
    result.merchant_id = "merchant"
    result.api_key = "secret"
    result.selected_payment_method = None
    return result


@pytest.mark.parametrize(
    "value",
    ["X" * 65, "CARD\nINJECT", True, -1, 2**31, ["CARD"], {"method": "CARD"}],
)
def test_platega_rejects_noncanonical_payment_method(value: Any) -> None:
    with pytest.raises(ValueError):
        PlategaGateway._normalize_payment_method(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("  ", None),
        (" CARD-SBP_2 ", "CARD-SBP_2"),
        (" СБП (QR-код) ", "СБП (QR-код)"),
        (2, "2"),
        (14, "14"),
        (123, "123"),
    ],
)
def test_platega_normalizes_safe_payment_method(value: Any, expected: Optional[str]) -> None:
    assert PlategaGateway._normalize_payment_method(value) == expected


@pytest.mark.asyncio
async def test_signed_webhook_accepts_documented_integer_payment_method() -> None:
    platega = gateway()

    result = await platega.handle_webhook(signed_request(2))

    assert result == (
        UUID("00000000-0000-0000-0000-000000000888"),
        TransactionStatus.COMPLETED,
    )
    assert platega.selected_payment_method == "2"


@pytest.mark.asyncio
async def test_signed_terminal_webhook_ignores_invalid_optional_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dao = FakeTransactionDao()
    platega = gateway()
    enqueue = AsyncMock()
    monkeypatch.setattr(handle_payment_transaction_task, "kiq", enqueue)

    response = await _process_payment_webhook(
        gateway_type="platega",
        request=signed_request("CARD\nINJECT"),
        config=SimpleNamespace(build=SimpleNamespace(data={})),  # type: ignore[arg-type]
        event_publisher=SimpleNamespace(publish=AsyncMock()),  # type: ignore[arg-type]
        get_payment_gateway_instance=SimpleNamespace(  # type: ignore[arg-type]
            system=AsyncMock(return_value=platega)
        ),
        transaction_dao=dao,  # type: ignore[arg-type]
        uow=FakeUnitOfWork(),  # type: ignore[arg-type]
    )

    assert response.status_code == 200
    assert dao.events == [
        {
            "payment_id": UUID("00000000-0000-0000-0000-000000000888"),
            "gateway_type": PaymentGatewayType.PLATEGA,
            "status": TransactionStatus.COMPLETED,
            "selected_payment_method": None,
            "error_code": None,
        }
    ]
    enqueue.assert_awaited_once_with(
        UUID("00000000-0000-0000-0000-000000000888"),
        TransactionStatus.COMPLETED,
        PaymentGatewayType.PLATEGA,
    )


@pytest.mark.asyncio
async def test_invalid_method_is_not_acknowledged_when_durable_store_fails() -> None:
    platega = gateway()

    response = await _process_payment_webhook(
        gateway_type="platega",
        request=signed_request("X" * 65),
        config=SimpleNamespace(build=SimpleNamespace(data={})),  # type: ignore[arg-type]
        event_publisher=SimpleNamespace(publish=AsyncMock()),  # type: ignore[arg-type]
        get_payment_gateway_instance=SimpleNamespace(  # type: ignore[arg-type]
            system=AsyncMock(return_value=platega)
        ),
        transaction_dao=FakeTransactionDao(fail=True),  # type: ignore[arg-type]
        uow=FakeUnitOfWork(),  # type: ignore[arg-type]
    )

    assert response.status_code == 503
