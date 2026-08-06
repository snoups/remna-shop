import base64
import hashlib
import hmac
from decimal import Decimal
from typing import Any, Final, Union
from uuid import UUID, uuid4

import orjson
from aiogram import Bot
from fastapi import Request
from httpx import AsyncClient, HTTPStatusError
from loguru import logger

from src.__version__ import __version__
from src.application.dto import PaymentGatewayDto, PaymentResultDto
from src.application.dto.payment_gateway import Pay2328GatewaySettingsDto
from src.core.config import AppConfig
from src.core.enums import TransactionStatus

from .base import BasePaymentGateway


# https://doc.2328.io/en/docs/payments
class Pay2328Gateway(BasePaymentGateway):
    _client: AsyncClient

    API_BASE: Final[str] = "https://api.2328.io/api"

    def __init__(self, gateway: PaymentGatewayDto, bot: Bot, config: AppConfig) -> None:
        super().__init__(gateway, bot, config)

        settings = self._get_settings()
        if not settings.project_uuid or not settings.api_key:
            raise ValueError("2328.io gateway is not configured")

        self._client = self._make_client(
            base_url=self.API_BASE,
            headers={
                "Content-Type": "application/json",
                "User-Agent": (
                    f"Remnashop/{__version__} (+https://github.com/snoups/remnashop)"
                ),
                "project": settings.project_uuid,
            },
        )

    async def handle_create_payment(self, amount: Decimal, details: str) -> PaymentResultDto:
        settings = self._get_settings()
        redirect_url = await self._get_bot_redirect_url()
        payload = {
            "amount": str(amount),
            "currency": self.data.currency.value,
            "order_id": str(uuid4()),
            "url_return": redirect_url,
            "url_success": redirect_url,
            "url_callback": self.config.get_webhook(self.data.type),
            "description": details[:200],
            "ttl_seconds": settings.ttl_seconds,
        }
        body = orjson.dumps(payload)
        logger.debug(f"Creating 2328.io payment payload: {payload}")

        try:
            response = await self._client.post(
                "/v1/payment",
                content=body,
                headers={"sign": self._sign(body)},
            )
            response.raise_for_status()
            data = orjson.loads(response.content)
            return self._get_payment_data(data)
        except HTTPStatusError as e:
            logger.error(
                "HTTP error creating 2328.io payment. "
                f"Status: '{e.response.status_code}', Body: {e.response.text}"
            )
            raise
        except (KeyError, ValueError, orjson.JSONDecodeError) as e:
            logger.error(f"Failed to parse 2328.io response. Error: {e}")
            raise
        except Exception as e:
            logger.exception(f"Unexpected error creating 2328.io payment: {e}")
            raise

    async def handle_webhook(self, request: Request) -> Union[tuple[UUID, TransactionStatus], None]:
        payload = await self._get_webhook_data(request)
        self._verify_webhook(payload)

        payment_id_raw = payload.get("uuid")
        if not payment_id_raw:
            raise ValueError("Required field 'uuid' is missing")

        payment_id = UUID(str(payment_id_raw))
        status = payload.get("payment_status")

        match status:
            case "paid" | "overpaid":
                return payment_id, TransactionStatus.COMPLETED
            case "underpaid" | "cancel" | "aml_lock":
                return payment_id, TransactionStatus.CANCELED
            case "pending" | "check" | "underpaid_check":
                logger.debug(f"2328.io webhook status '{status}' — skipping")
                return None
            case _:
                raise ValueError(f"Unsupported 2328.io payment status: {status}")

    def _get_payment_data(self, data: dict[str, Any]) -> PaymentResultDto:
        if data.get("state") != 0:
            raise ValueError(f"2328.io returned unsuccessful state: {data.get('state')}")

        result = data.get("result")
        if not isinstance(result, dict):
            raise KeyError("Invalid 2328.io response: missing 'result'")

        payment_id = result.get("uuid")
        payment_url = result.get("url")
        if not payment_id or not payment_url:
            raise KeyError("Invalid 2328.io response: missing payment uuid or url")

        return PaymentResultDto(id=UUID(str(payment_id)), url=str(payment_url))

    def _get_settings(self) -> Pay2328GatewaySettingsDto:
        settings = self.data.settings
        if not isinstance(settings, Pay2328GatewaySettingsDto):
            raise TypeError(
                f"Invalid settings type: expected {Pay2328GatewaySettingsDto.__name__}, "
                f"got {type(settings).__name__}"
            )
        return settings

    def _sign(self, body: bytes) -> str:
        settings = self._get_settings()
        if not settings.api_key:
            raise ValueError("2328.io API key is not configured")

        encoded = base64.b64encode(body)
        api_key = settings.api_key.get_secret_value()
        return hmac.new(api_key.encode(), encoded, hashlib.sha256).hexdigest()

    def _verify_webhook(self, payload: dict[str, Any]) -> None:
        received_signature = payload.pop("sign", None)
        if not isinstance(received_signature, str) or not received_signature:
            raise PermissionError("2328.io webhook signature is missing")

        expected_signature = self._sign(orjson.dumps(payload))
        if not hmac.compare_digest(received_signature.lower(), expected_signature.lower()):
            logger.warning("2328.io webhook HMAC signature verification failed")
            raise PermissionError("2328.io webhook verification failed")
