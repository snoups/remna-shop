import hashlib
import hmac
import time
import uuid
from decimal import Decimal
from typing import Any, Final, Union
from uuid import UUID

import orjson
from aiogram import Bot
from fastapi import Request
from fastapi.responses import PlainTextResponse
from httpx import AsyncClient, HTTPStatusError
from loguru import logger

from src.application.dto import PaymentGatewayDto, PaymentResultDto
from src.application.dto.payment_gateway import FreeKassaGatewaySettingsDto
from src.core.config import AppConfig
from src.core.enums import TransactionStatus

from .base import BasePaymentGateway


# https://docs.freekassa.net/
class FreeKassaGateway(BasePaymentGateway):
    _client: AsyncClient

    API_BASE: Final[str] = "https://api.fk.life/v1"

    NETWORKS = [
        "168.119.157.136",
        "168.119.60.227",
        "178.154.197.79",
        "51.250.54.238",
    ]

    def __init__(self, gateway: PaymentGatewayDto, bot: Bot, config: AppConfig) -> None:
        super().__init__(gateway, bot, config)

        if not isinstance(self.data.settings, FreeKassaGatewaySettingsDto):
            raise TypeError(
                f"Invalid settings type: expected {FreeKassaGatewaySettingsDto.__name__}, "
                f"got {type(self.data.settings).__name__}"
            )

        self._client = self._make_client(base_url=self.API_BASE)

    async def handle_create_payment(self, amount: Decimal, details: str) -> PaymentResultDto:
        order_id = str(uuid.uuid4())
        payload = await self._create_payment_payload(str(amount), order_id)
        logger.debug(f"Creating payment payload: {payload}")

        try:
            response = await self._client.post("orders/create", json=payload)
            response.raise_for_status()
            data = orjson.loads(response.content)

            if data.get("type") != "success":
                raise ValueError(f"FreeKassa API error: {data}")

            return self._get_payment_data(data, order_id)

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

        form = await request.form()
        webhook_data = dict(form)

        if not self._verify_webhook(request, webhook_data):
            raise PermissionError("Webhook verification failed")

        payment_id_str = webhook_data.get("MERCHANT_ORDER_ID")

        if not isinstance(payment_id_str, str):
            raise ValueError("Required field 'MERCHANT_ORDER_ID' is missing or has unexpected type")

        payment_id = UUID(payment_id_str)
        return payment_id, TransactionStatus.COMPLETED

    async def build_webhook_response(self, request: Request) -> PlainTextResponse:
        return PlainTextResponse(content="YES")

    async def _create_payment_payload(self, amount: str, order_id: str) -> dict[str, Any]:
        data: dict[str, Any] = {
            "shopId": self.data.settings.shop_id,  # type: ignore[union-attr]
            "nonce": time.time_ns(),  # must be strictly increasing
            "paymentId": order_id,
            "i": self.data.settings.payment_system_id,  # type: ignore[union-attr]
            "email": self.data.settings.customer_email,  # type: ignore[union-attr]
            "ip": self.data.settings.customer_ip,  # type: ignore[union-attr]
            "amount": str(amount),
            "currency": self.data.currency.upper(),
            "success_url": await self._get_bot_redirect_url(),
            "failure_url": await self._get_bot_redirect_url(),
            "notification_url": self.config.get_webhook(self.data.type),
        }

        # Sort by key and join values with '|'
        sorted_values = "|".join(str(v) for _, v in sorted(data.items()))
        signature = hmac.new(
            self.data.settings.api_key.get_secret_value().encode(),  # type: ignore[union-attr]
            sorted_values.encode(),
            hashlib.sha256,
        ).hexdigest()

        data["signature"] = signature
        return data

    def _get_payment_data(self, data: dict[str, Any], order_id: str) -> PaymentResultDto:
        payment_url = data.get("location")
        if not payment_url:
            raise KeyError("Invalid response from FreeKassa API: missing 'location'")

        return PaymentResultDto(id=UUID(order_id), url=str(payment_url))

    def _verify_webhook(self, request: Request, data: dict) -> bool:
        ip = self._get_ip(request.headers)
        if not self._is_ip_trusted(ip):
            logger.critical(f"Webhook received from untrusted IP: '{ip}'")
            return False

        sign = data.get("SIGN")
        if not sign:
            logger.warning("Webhook is missing 'SIGN' field")
            return False

        merchant_id = data.get("MERCHANT_ID")
        if not merchant_id:
            logger.warning("Webhook is missing 'MERCHANT_ID' field")
            return False

        if str(merchant_id) != str(self.data.settings.shop_id):  # type: ignore[union-attr]
            logger.warning(f"Webhook MERCHANT_ID '{merchant_id}' does not match configured shop_id")
            return False

        raw = (
            f"{merchant_id}"
            f":{data.get('AMOUNT')}"
            f":{self.data.settings.secret_word_2.get_secret_value()}"  # type: ignore[union-attr]
            f":{data.get('MERCHANT_ORDER_ID')}"
        )
        # FreeKassa mandates MD5 for its protocol signature.
        expected = hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()

        if not hmac.compare_digest(expected, sign):
            logger.warning("Invalid webhook signature")
            return False

        return True
