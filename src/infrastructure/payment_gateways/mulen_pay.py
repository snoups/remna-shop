import hashlib
import uuid
from decimal import Decimal
from hmac import compare_digest
from typing import Any, Final, Union
from uuid import UUID

import orjson
from aiogram import Bot
from fastapi import Request
from httpx import AsyncClient, HTTPStatusError
from loguru import logger

from src.application.dto import PaymentGatewayDto, PaymentResultDto
from src.application.dto.payment_gateway import MulenPayGatewaySettingsDto
from src.core.config import AppConfig
from src.core.enums import TransactionStatus

from .base import BasePaymentGateway


# https://docs.mulenpay.com/
class MulenPayGateway(BasePaymentGateway):
    _client: AsyncClient

    API_BASE: Final[str] = "https://api.mulenpay.com/api"

    DEFAULT_PAYMENT_SUBJECT: Final[int] = 4
    DEFAULT_PAYMENT_MODE: Final[int] = 4

    def __init__(self, gateway: PaymentGatewayDto, bot: Bot, config: AppConfig) -> None:
        super().__init__(gateway, bot, config)

        if not isinstance(self.data.settings, MulenPayGatewaySettingsDto):
            raise TypeError(
                f"Invalid settings type: expected {MulenPayGatewaySettingsDto.__name__}, "
                f"got {type(self.data.settings).__name__}"
            )

        self._client = self._make_client(
            base_url=self.API_BASE,
            headers={
                "Authorization": f"Bearer {self.data.settings.api_key.get_secret_value()}"  # type: ignore[union-attr]
            },
        )

    async def handle_create_payment(self, amount: Decimal, details: str) -> PaymentResultDto:
        order_uuid = str(uuid.uuid4())
        payload = self._create_payment_payload(amount, details, order_uuid)
        logger.debug(f"Creating payment payload: {payload}")

        try:
            response = await self._client.post("v2/payments", json=payload)
            response.raise_for_status()
            data = orjson.loads(response.content)

            if not data.get("success"):
                raise ValueError(f"MulenPay API error: {data}")

            return self._get_payment_data(data, order_uuid)

        except HTTPStatusError as e:
            logger.error(
                f"HTTP error creating payment. "
                f"Status: '{e.response.status_code}', Body: {e.response.text}"
            )
            raise
        except (KeyError, orjson.JSONDecodeError) as e:
            logger.error(f"Failed to parse response. Error: {e}")
            raise
        except Exception as e:
            logger.exception(f"An unexpected error occurred while creating payment: {e}")
            raise

    async def handle_webhook(self, request: Request) -> Union[tuple[UUID, TransactionStatus], None]:
        logger.debug(f"Received {self.__class__.__name__} webhook request")

        webhook_data = await self._get_webhook_data(request)

        # MulenPay does not provide webhook signature verification
        # if not self._verify_webhook(webhook_data):
        #     raise PermissionError("Webhook verification failed")

        order_uuid = webhook_data.get("uuid")
        if not order_uuid:
            raise ValueError("Required field 'uuid' is missing")

        payment_status = webhook_data.get("payment_status")
        payment_id = UUID(order_uuid)

        match payment_status:
            case "success":
                transaction_status = TransactionStatus.COMPLETED
            case "cancel":
                transaction_status = TransactionStatus.CANCELED
            case _:
                raise ValueError(f"Unsupported payment_status: {payment_status}")

        return payment_id, transaction_status

    def _create_payment_payload(
        self,
        amount: Decimal,
        details: str,
        order_uuid: str,
    ) -> dict[str, Any]:
        price = str(amount.quantize(Decimal("0.01")))
        return {
            "currency": self.data.currency.value.lower(),
            "amount": price,
            "uuid": order_uuid,
            "shopId": self.data.settings.shop_id,  # type: ignore[union-attr]
            "description": details,
            "sign": self._generate_signature(
                self.data.currency.value.lower(),
                price,
                self.data.settings.shop_id,  # type: ignore[union-attr, arg-type]
            ),
            "items": [
                {
                    "description": details,
                    "quantity": 1,
                    "price": price,
                    "vat_code": self.data.settings.vat_code,  # type: ignore[union-attr]
                    "payment_subject": self.DEFAULT_PAYMENT_SUBJECT,
                    "payment_mode": self.DEFAULT_PAYMENT_MODE,
                }
            ],
        }

    def _generate_signature(self, currency: str, amount: str, shop_id: int) -> str:
        raw = f"{currency}{amount}{shop_id}{self.data.settings.secret_key.get_secret_value()}"  # type: ignore[union-attr]
        return hashlib.sha1(raw.encode()).hexdigest()

    def _get_payment_data(self, data: dict[str, Any], order_uuid: str) -> PaymentResultDto:
        payment_url = data.get("paymentUrl")
        if not payment_url:
            raise KeyError("Invalid response from MulenPay API: missing 'paymentUrl'")

        return PaymentResultDto(id=UUID(order_uuid), url=str(payment_url))

    def _verify_webhook(self, data: dict) -> bool:
        sign = data.get("sign")
        if not sign:
            logger.warning("Webhook is missing 'sign' field")
            return False

        shop_id = self.data.settings.shop_id  # type: ignore[union-attr]
        raw_amount = data.get("amount", "")
        currency = data.get("currency", "rub").lower()

        try:
            amount = f"{Decimal(str(raw_amount)):.2f}"
        except Exception:
            logger.warning(f"Failed to parse webhook amount: {raw_amount!r}")
            return False

        expected = self._generate_signature(currency, amount, shop_id)  # type: ignore[arg-type]

        if not compare_digest(expected, sign):
            logger.warning("Invalid MulenPay webhook signature")
            return False

        return True
