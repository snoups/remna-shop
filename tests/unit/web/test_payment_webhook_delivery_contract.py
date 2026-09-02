from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import Response
from starlette.requests import Request

from src.core.enums import PaymentGatewayType, TransactionStatus
from src.infrastructure.taskiq.tasks.payments import handle_payment_transaction_task
from src.web.endpoints.payments import _process_payment_webhook

HTTP_WEBHOOK_GATEWAYS = tuple(
    gateway for gateway in PaymentGatewayType if gateway != PaymentGatewayType.TELEGRAM_STARS
)
PAYMENT_ID = UUID("00000000-0000-0000-0000-000000000999")


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
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def store_webhook_event(self, **kwargs: Any) -> None:
        self.events.append(kwargs)


def request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/payments/test"})


@pytest.mark.parametrize("gateway_type", HTTP_WEBHOOK_GATEWAYS)
@pytest.mark.asyncio
async def test_terminal_callbacks_are_persisted_before_ack_for_every_gateway(
    gateway_type: PaymentGatewayType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dao = FakeTransactionDao()
    enqueue = AsyncMock()
    monkeypatch.setattr(handle_payment_transaction_task, "kiq", enqueue)
    gateway = SimpleNamespace(
        handle_webhook=AsyncMock(
            return_value=(PAYMENT_ID, TransactionStatus.COMPLETED)
        ),
        build_webhook_response=AsyncMock(return_value=Response(status_code=200)),
    )

    response = await _process_payment_webhook(
        gateway_type=gateway_type.value.lower(),
        request=request(),
        config=SimpleNamespace(build=SimpleNamespace(data={})),  # type: ignore[arg-type]
        event_publisher=SimpleNamespace(publish=AsyncMock()),  # type: ignore[arg-type]
        get_payment_gateway_instance=SimpleNamespace(  # type: ignore[arg-type]
            system=AsyncMock(return_value=gateway)
        ),
        transaction_dao=dao,  # type: ignore[arg-type]
        uow=FakeUnitOfWork(),  # type: ignore[arg-type]
    )

    assert response.status_code == 200
    assert dao.events == [
        {
            "payment_id": PAYMENT_ID,
            "gateway_type": gateway_type,
            "status": TransactionStatus.COMPLETED,
            "selected_payment_method": None,
            "error_code": None,
        }
    ]
    enqueue.assert_awaited_once_with(
        PAYMENT_ID,
        TransactionStatus.COMPLETED,
        gateway_type,
    )


@pytest.mark.parametrize("gateway_type", HTTP_WEBHOOK_GATEWAYS)
@pytest.mark.asyncio
async def test_unparsed_callbacks_are_never_acknowledged_for_every_gateway(
    gateway_type: PaymentGatewayType,
) -> None:
    gateway = SimpleNamespace(
        handle_webhook=AsyncMock(side_effect=ValueError("new provider callback format")),
        build_webhook_response=AsyncMock(return_value=Response(status_code=200)),
    )
    publisher = SimpleNamespace(publish=AsyncMock())

    response = await _process_payment_webhook(
        gateway_type=gateway_type.value.lower(),
        request=request(),
        config=SimpleNamespace(build=SimpleNamespace(data={})),  # type: ignore[arg-type]
        event_publisher=publisher,  # type: ignore[arg-type]
        get_payment_gateway_instance=SimpleNamespace(  # type: ignore[arg-type]
            system=AsyncMock(return_value=gateway)
        ),
        transaction_dao=FakeTransactionDao(),  # type: ignore[arg-type]
        uow=FakeUnitOfWork(),  # type: ignore[arg-type]
    )

    assert response.status_code == 503
    gateway.build_webhook_response.assert_not_awaited()
    publisher.publish.assert_awaited_once()
