from types import SimpleNamespace
from typing import Awaitable, Callable, TypeVar
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.application.dto import PaymentResultDto, PlanSnapshotDto, PriceDetailsDto, UserDto
from src.application.use_cases.gateways.commands.payment import CreatePayment, CreatePaymentDto
from src.core.enums import Currency, PaymentGatewayType, PurchaseType

T = TypeVar("T")


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.committed = False

    async def __aenter__(self) -> "FakeUnitOfWork":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        return None

    async def persist_with_unique_code(
        self,
        generate: Callable[[], Awaitable[str]],
        persist: Callable[[str], Awaitable[T]],
        column: str,
        retries: int = 5,
    ) -> T:
        raise NotImplementedError


@pytest.mark.asyncio
async def test_native_payment_generates_provider_idempotency_key() -> None:
    transaction_id = uuid4()
    generated_provider_key = uuid4()
    provider_payment_id = uuid4()
    gateway = SimpleNamespace(
        data=SimpleNamespace(
            type=PaymentGatewayType.YOOKASSA,
            currency=Currency.RUB,
            settings=None,
        ),
        build_payment_request=AsyncMock(return_value={"amount": {"value": "2"}}),
        payment_owner_fingerprint=MagicMock(return_value="owner-hash"),
        create_payment_from_request=AsyncMock(
            return_value=PaymentResultDto(
                id=provider_payment_id,
                url="https://payment.example/confirm",
                provider_status="pending",
            )
        ),
    )
    get_gateway = MagicMock()
    get_gateway.system = AsyncMock(return_value=gateway)
    translator = MagicMock()
    translator.get.return_value = "Subscription"
    translator_hub = MagicMock()
    translator_hub.get_translator_by_locale.return_value = translator
    transaction_dao = MagicMock()
    transaction_dao.create = AsyncMock(side_effect=lambda transaction: transaction)
    uow = FakeUnitOfWork()
    create_payment = CreatePayment(
        uow=uow,
        payment_gateway_dao=MagicMock(),
        transaction_dao=transaction_dao,
        get_payment_gateway_instance=get_gateway,
        translator_hub=translator_hub,
        payment_idempotency=MagicMock(),
    )

    with patch(
        "src.application.use_cases.gateways.commands.payment.uuid.uuid4",
        side_effect=[transaction_id, generated_provider_key],
    ):
        result = await create_payment._execute(
            UserDto(id=42, telegram_id=123456789, name="Bot User"),
            CreatePaymentDto(
                plan_snapshot=PlanSnapshotDto.test(),
                pricing=PriceDetailsDto.test(),
                purchase_type=PurchaseType.NEW,
                gateway_type=PaymentGatewayType.YOOKASSA,
            ),
        )

    assert result.id == provider_payment_id
    gateway.create_payment_from_request.assert_awaited_once_with(
        {"amount": {"value": "2"}},
        idempotency_key=str(generated_provider_key),
    )
    assert uow.committed is True
