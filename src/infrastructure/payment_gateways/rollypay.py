import hashlib
import hmac
import time
import uuid
from decimal import Decimal
from typing import Any, Final, Union, cast
from uuid import UUID

import orjson
from aiogram import Bot
from fastapi import Request
from httpx import AsyncClient, HTTPStatusError
from loguru import logger

from src.application.dto import PaymentGatewayDto, PaymentResultDto
from src.application.dto.payment_gateway import RollyPaySettingsDto
from src.core.config import AppConfig
from src.core.enums import TransactionStatus

from .base import BasePaymentGateway


# https://docs.rollypay.io/
class RollyPayGateway(BasePaymentGateway):
    _client: AsyncClient

    API_BASE: Final[str] = "https://rollypay.io"
    CREATE_ENDPOINT: Final[str] = "api/v1/payments"

    # Reject webhooks with a timestamp skew larger than this window (replay protection).
    TIMESTAMP_TOLERANCE_SECONDS: Final[int] = 300

    def __init__(self, gateway: PaymentGatewayDto, bot: Bot, config: AppConfig) -> None:
        super().__init__(gateway, bot, config)

        if not isinstance(self.data.settings, RollyPaySettingsDto):
            raise TypeError(
                f"Invalid settings type: expected {RollyPaySettingsDto.__name__}, "
                f"got {type(self.data.settings).__name__}"
            )

        self.settings = cast(RollyPaySettingsDto, self.data.settings)

        self._client = self._make_client(
            base_url=self.API_BASE,
            headers={
                "X-API-Key": self.settings.api_key.get_secret_value(),  # type: ignore[union-attr]
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

    async def handle_create_payment(self, amount: Decimal, details: str) -> PaymentResultDto:
        order_id = str(uuid.uuid4())
        payload = await self._create_payment_payload(amount, details, order_id)
        logger.debug(f"Creating RollyPay payment payload: {payload}")

        try:
            response = await self._client.post(
                self.CREATE_ENDPOINT,
                json=payload,
                headers={"X-Nonce": str(uuid.uuid4())},
            )
            response.raise_for_status()
            data = orjson.loads(response.content)
            return self._get_payment_data(data, order_id)

        except HTTPStatusError as e:
            logger.error(
                f"HTTP error creating RollyPay payment. "
                f"Status: '{e.response.status_code}', Body: {e.response.text}"
            )
            raise
        except (KeyError, orjson.JSONDecodeError) as e:
            logger.error(f"Failed to parse RollyPay response. Error: {e}")
            raise
        except Exception as e:
            logger.exception(f"Unexpected error creating RollyPay payment: {e}")
            raise

    async def handle_webhook(self, request: Request) -> Union[tuple[UUID, TransactionStatus], None]:
        logger.debug(f"Received {self.__class__.__name__} webhook request")

        raw_body = await request.body()

        if not self._verify_webhook(request, raw_body):
            raise PermissionError("Webhook verification failed")

        webhook_data = orjson.loads(raw_body)
        logger.debug(f"RollyPay webhook data: {webhook_data}")

        order_id_str = webhook_data.get("order_id")
        if not order_id_str:
            # payout.* and other non-payment events do not carry order_id
            logger.debug("RollyPay webhook missing 'order_id' — skipping non-payment event")
            return None

        status = webhook_data.get("status")

        try:
            payment_id = UUID(order_id_str)
        except (ValueError, AttributeError, TypeError):
            # order_id was not issued by us (foreign integration on the same account)
            logger.warning(f"RollyPay webhook has a non-UUID 'order_id': '{order_id_str}'")
            return None

        match status:
            case "paid":
                transaction_status = TransactionStatus.COMPLETED
            case "canceled" | "expired":
                transaction_status = TransactionStatus.CANCELED
            case "chargeback" | "refunded":
                transaction_status = TransactionStatus.REFUNDED
            case "created" | "processing":
                logger.debug(f"RollyPay webhook status '{status}' — skipping")
                return None
            case _:
                raise ValueError(f"Unsupported RollyPay status: {status}")

        return payment_id, transaction_status

    async def _create_payment_payload(
        self,
        amount: Decimal,
        details: str,
        order_id: str,
    ) -> dict[str, Any]:
        redirect_url = await self._get_bot_redirect_url()
        payload: dict[str, Any] = {
            "amount": str(amount),
            "payment_currency": self.data.currency.value,
            "order_id": order_id,
            "description": details[:255],
            "success_redirect_url": redirect_url,
            "fail_redirect_url": redirect_url,
        }

        if self.settings.payment_method:
            payload["payment_method"] = self.settings.payment_method

        return payload

    def _get_payment_data(self, data: dict[str, Any], order_id: str) -> PaymentResultDto:
        pay_url = data.get("pay_url")
        if not pay_url:
            raise KeyError("Invalid RollyPay response: missing 'pay_url'")

        return PaymentResultDto(id=UUID(order_id), url=str(pay_url))

    def _verify_webhook(self, request: Request, raw_body: bytes) -> bool:
        signature = request.headers.get("X-Signature")
        timestamp = request.headers.get("X-Timestamp")

        if not signature or not timestamp:
            logger.warning("RollyPay webhook missing 'X-Signature' or 'X-Timestamp' header")
            return False

        if not self._is_timestamp_valid(timestamp):
            logger.warning(f"RollyPay webhook timestamp '{timestamp}' out of tolerance")
            return False

        signing_secret = self.settings.signing_secret.get_secret_value()  # type: ignore[union-attr]
        signed_payload = f"{timestamp}.".encode() + raw_body
        expected_signature = hmac.new(
            signing_secret.encode(),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected_signature, signature):
            logger.warning("RollyPay webhook HMAC signature verification failed")
            return False

        return True

    def _is_timestamp_valid(self, timestamp: str) -> bool:
        try:
            ts = int(timestamp)
        except ValueError:
            return False

        skew = abs(int(time.time()) - ts)
        return skew <= self.TIMESTAMP_TOLERANCE_SECONDS
