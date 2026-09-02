import hmac
from decimal import Decimal
from typing import Any, Final, Optional, Union, cast
from uuid import UUID

import orjson
from aiogram import Bot
from fastapi import Request
from httpx import AsyncClient, HTTPStatusError
from loguru import logger

from src.application.dto import PaymentGatewayDto, PaymentResultDto
from src.application.dto.payment_gateway import PlategaGatewaySettingsDto
from src.core.config import AppConfig
from src.core.enums import TransactionStatus
from src.core.utils.payment_methods import normalize_platega_payment_method

from .base import BasePaymentGateway


# https://docs.platega.io/
class PlategaGateway(BasePaymentGateway):
    _client: AsyncClient

    API_BASE: Final[str] = "https://app.platega.io"
    DEFAULT_MULTI_METHOD_ENDPOINT: Final[str] = "v2/transaction/process"
    DEFAULT_SINGLE_METHOD_ENDPOINT: Final[str] = "transaction/process"

    def __init__(self, gateway: PaymentGatewayDto, bot: Bot, config: AppConfig) -> None:
        super().__init__(gateway, bot, config)

        if not isinstance(self.data.settings, PlategaGatewaySettingsDto):
            raise TypeError(
                f"Invalid settings type: expected {PlategaGatewaySettingsDto.__name__}, "
                f"got {type(self.data.settings).__name__}"
            )

        self.settings = cast(PlategaGatewaySettingsDto, self.data.settings)
        if self.settings.merchant_id is None or self.settings.api_key is None:
            raise ValueError("Platega gateway is not configured")

        self.merchant_id = self.settings.merchant_id
        self.api_key = self.settings.api_key.get_secret_value()

        self._client = self._make_client(
            base_url=self.API_BASE,
            headers={
                "X-MerchantId": self.merchant_id,
                "X-Secret": self.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        self.selected_payment_method: Optional[str] = None

    async def handle_create_payment(self, amount: Decimal, details: str) -> PaymentResultDto:
        payload = await self._create_payment_payload(amount, details)
        logger.debug(f"Creating payment payload: {payload}")
        endpoint = (
            self.DEFAULT_SINGLE_METHOD_ENDPOINT
            if self.settings.payment_method is not None
            else self.DEFAULT_MULTI_METHOD_ENDPOINT
        )

        try:
            response = await self._client.post(endpoint, json=payload)
            response.raise_for_status()
            data = orjson.loads(response.content)
            return self._get_payment_data(data)

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

        if not self._verify_webhook(request):
            raise PermissionError("Webhook verification failed")

        raw_body = await request.body()
        webhook_data = orjson.loads(raw_body)

        payment_id_str = webhook_data.get("id")
        if not payment_id_str:
            raise ValueError("Required field 'id' is missing")

        status = webhook_data.get("status")
        payment_id = UUID(payment_id_str)

        match status:
            case "CONFIRMED":
                transaction_status = TransactionStatus.COMPLETED
            case "CANCELED":
                transaction_status = TransactionStatus.CANCELED
            case "CHARGEBACKED":
                transaction_status = TransactionStatus.REFUNDED
            case _:
                raise ValueError(f"Unsupported status: {status}")

        try:
            self.selected_payment_method = self._normalize_payment_method(
                webhook_data.get("paymentMethod")
            )
        except ValueError:
            # paymentMethod is descriptive provider metadata. A valid signed
            # terminal event must not be blocked if its optional representation
            # changes or is malformed.
            self.selected_payment_method = None
            logger.warning(
                "Ignoring invalid optional Platega paymentMethod for '{}'",
                payment_id,
            )

        return payment_id, transaction_status

    async def _create_payment_payload(self, amount: Decimal, details: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "paymentDetails": {
                "amount": float(amount),
                "currency": self.data.currency.value,
            },
            "description": details,
            "return": await self._get_bot_redirect_url(),
            "failedUrl": await self._get_bot_redirect_url(),
        }
        if self.settings.payment_method is not None:
            payload["paymentMethod"] = self.settings.payment_method

        return payload

    def _get_payment_data(self, data: dict[str, Any]) -> PaymentResultDto:
        transaction_id_str = data.get("transactionId")
        if not transaction_id_str:
            raise KeyError("Invalid response from API: missing 'transactionId'")

        payment_url = data.get("redirect") or data.get("url")
        if not payment_url:
            raise KeyError("Invalid response from API: missing 'redirect' or 'url'")

        return PaymentResultDto(id=UUID(transaction_id_str), url=str(payment_url))

    @staticmethod
    def _normalize_payment_method(value: Any) -> str | None:
        return normalize_platega_payment_method(value)

    def _verify_webhook(self, request: Request) -> bool:
        merchant_id = request.headers.get("X-MerchantId")
        secret = request.headers.get("X-Secret")

        if not merchant_id or not secret:
            logger.warning("Webhook is missing X-MerchantId or X-Secret headers")
            return False

        merchant_id_ok = hmac.compare_digest(merchant_id, self.merchant_id)
        secret_ok = hmac.compare_digest(secret, self.api_key)

        if not merchant_id_ok or not secret_ok:
            logger.warning("Invalid Platega webhook credentials")
            return False

        return True
