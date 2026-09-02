import asyncio
import hashlib
import uuid
from decimal import Decimal
from typing import Any, Final, Union
from uuid import UUID

import orjson
from aiogram import Bot
from fastapi import Request
from httpx import AsyncClient, ConnectError, HTTPStatusError
from loguru import logger

from src.application.dto import (
    PaymentGatewayDto,
    PaymentResultDto,
)
from src.application.dto.payment_gateway import YooKassaGatewaySettingsDto
from src.core.config import AppConfig
from src.core.enums import TransactionStatus

from .base import BasePaymentGateway


# https://yookassa.ru/developers/
class YookassaGateway(BasePaymentGateway):
    _client: AsyncClient

    API_BASE: Final[str] = "https://api.yookassa.ru"
    PAYMENT_SUBJECT: Final[str] = "service"
    PAYMENT_MODE: Final[str] = "full_payment"

    CONNECT_RETRIES: Final[int] = 3
    CONNECT_RETRY_DELAY: Final[float] = 1.0

    NETWORKS = [
        "77.75.153.0/25",
        "77.75.156.11",
        "77.75.156.35",
        "77.75.154.128/25",
        "185.71.76.0/27",
        "185.71.77.0/27",
        "2a02:5180:0:1509::/64",
        "2a02:5180:0:2655::/64",
        "2a02:5180:0:1533::/64",
        "2a02:5180:0:2669::/64",
    ]

    def __init__(self, gateway: PaymentGatewayDto, bot: Bot, config: AppConfig) -> None:
        super().__init__(gateway, bot, config)

        if not isinstance(self.data.settings, YooKassaGatewaySettingsDto):
            raise TypeError(
                f"Invalid settings type: expected {YooKassaGatewaySettingsDto.__name__}, "
                f"got {type(self.data.settings).__name__}"
            )

        self._client = self._make_client(
            base_url=self.API_BASE,
            auth=(
                self.data.settings.shop_id,
                self.data.settings.api_key.get_secret_value(),  # type: ignore [arg-type, union-attr]
            ),
        )

    async def handle_create_payment(self, amount: Decimal, details: str) -> PaymentResultDto:
        return await self.create_payment(amount, details)

    async def create_payment(
        self,
        amount: Decimal,
        details: str,
        idempotency_key: str | None = None,
    ) -> PaymentResultDto:
        payload = await self.build_payment_request(amount, details)
        return await self.create_payment_from_request(
            payload,
            idempotency_key=idempotency_key or str(uuid.uuid4()),
        )

    async def build_payment_request(
        self,
        amount: Decimal,
        details: str,
        *,
        return_url: str | None = None,
    ) -> dict[str, Any]:
        return await self._create_payment_payload(str(amount), details, return_url=return_url)

    def payment_owner_fingerprint(self) -> str:
        shop_id = self.data.settings.shop_id  # type: ignore[union-attr]
        return hashlib.sha256(f"remnashop:yookassa-owner:v1\0{shop_id}".encode()).hexdigest()

    async def create_payment_from_request(
        self,
        request_snapshot: dict[str, Any],
        *,
        idempotency_key: str | None,
    ) -> PaymentResultDto:
        if not idempotency_key:
            raise ValueError("YooKassa replay requires an idempotency key")
        # Copy through orjson to reject non-JSON values and prevent callers mutating the
        # persisted object while the request is in flight.
        payload = orjson.loads(orjson.dumps(request_snapshot))
        if not isinstance(payload, dict):
            raise ValueError("Invalid persisted YooKassa request")
        headers = {"Idempotence-Key": idempotency_key}
        logger.debug(
            "Creating YooKassa payment with persisted payload (amount={}, currency={}, "
            "has_metadata={})",
            payload.get("amount", {}).get("value")
            if isinstance(payload.get("amount"), dict)
            else None,
            payload.get("amount", {}).get("currency")
            if isinstance(payload.get("amount"), dict)
            else None,
            "metadata" in payload,
        )

        last_connect_error: ConnectError | None = None

        for attempt in range(1, self.CONNECT_RETRIES + 1):
            try:
                response = await self._client.post("v3/payments", json=payload, headers=headers)
                response.raise_for_status()
                data = orjson.loads(response.content)
                return self._get_payment_data(data)

            except ConnectError as e:
                last_connect_error = e
                logger.warning(
                    f"ConnectError on attempt {attempt}/{self.CONNECT_RETRIES} "
                    f"while creating payment: {e}"
                )
                if attempt < self.CONNECT_RETRIES:
                    await asyncio.sleep(self.CONNECT_RETRY_DELAY * attempt)

            except HTTPStatusError as e:
                logger.error(
                    "YooKassa payment creation failed with HTTP status '{}'",
                    e.response.status_code,
                )
                raise
            except (KeyError, orjson.JSONDecodeError) as e:
                logger.error(f"Failed to parse response. Error: {e}")
                raise
            except Exception as e:
                logger.exception(f"An unexpected error occurred while creating payment: {e}")
                raise

        logger.error(
            f"All {self.CONNECT_RETRIES} attempts to connect to YooKassa failed. "
            f"Last error: {last_connect_error}"
        )
        raise last_connect_error  # type: ignore[misc]

    async def verify_payment_result(
        self,
        payment_id: UUID,
        request_snapshot: dict[str, Any],
    ) -> PaymentResultDto:
        response = await self._client.get(f"v3/payments/{payment_id}")
        response.raise_for_status()
        data = orjson.loads(response.content)
        if not isinstance(data, dict) or str(data.get("id")) != str(payment_id):
            raise ValueError("YooKassa returned a mismatched payment")

        expected_amount = request_snapshot.get("amount")
        actual_amount = data.get("amount")
        if not isinstance(expected_amount, dict) or not isinstance(actual_amount, dict):
            raise ValueError("YooKassa payment amount is unavailable")
        try:
            amount_matches = Decimal(str(expected_amount.get("value"))) == Decimal(
                str(actual_amount.get("value"))
            )
        except Exception as exc:
            raise ValueError("YooKassa payment amount is invalid") from exc
        if not amount_matches or expected_amount.get("currency") != actual_amount.get("currency"):
            raise ValueError("YooKassa payment amount or currency mismatch")

        expected_metadata = request_snapshot.get("metadata")
        if expected_metadata is not None and data.get("metadata") != expected_metadata:
            raise ValueError("YooKassa payment metadata mismatch")
        provider_status = data.get("status")
        if provider_status not in {"pending", "waiting_for_capture", "succeeded", "canceled"}:
            raise ValueError("YooKassa payment has an unsupported status")

        confirmation = data.get("confirmation")
        payment_url: str | None = None
        if isinstance(confirmation, dict):
            raw_url = confirmation.get("confirmation_url")
            if raw_url is not None:
                payment_url = str(raw_url)
        return PaymentResultDto(
            id=payment_id,
            url=payment_url,
            provider_status=str(provider_status),
        )

    async def handle_webhook(self, request: Request) -> Union[tuple[UUID, TransactionStatus], None]:
        logger.debug("Received YooKassa webhook request")

        if not self._verify_webhook(request):
            raise PermissionError("Webhook verification failed")

        webhook_data = await self._get_webhook_data(request)
        payment_object: dict = webhook_data.get("object", {})
        payment_id_str = payment_object.get("id")

        if not payment_id_str:
            raise ValueError("Required field 'id' is missing")

        status = payment_object.get("status")
        payment_id = UUID(payment_id_str)

        match status:
            case "succeeded":
                transaction_status = TransactionStatus.COMPLETED
            case "canceled":
                transaction_status = TransactionStatus.CANCELED
            case _:
                raise ValueError(f"Unsupported status: {status}")

        return payment_id, transaction_status

    async def _create_payment_payload(
        self,
        amount: str,
        details: str,
        *,
        return_url: str | None = None,
    ) -> dict[str, Any]:
        return {
            "amount": {"value": amount, "currency": self.data.currency},
            "confirmation": {
                "type": "redirect",
                "return_url": return_url or await self._get_bot_redirect_url(),
            },
            "capture": True,
            "description": details,
            "receipt": {
                "customer": {"email": self.data.settings.customer},  # type: ignore[union-attr]
                "items": [
                    {
                        "description": details,
                        "quantity": "1.00",
                        "amount": {"value": amount, "currency": self.data.currency},
                        "vat_code": self.data.settings.vat_code,  # type: ignore[union-attr]
                        "payment_subject": self.PAYMENT_SUBJECT,
                        "payment_mode": self.PAYMENT_MODE,
                    }
                ],
            },
        }

    def _get_payment_data(self, data: dict[str, Any]) -> PaymentResultDto:
        payment_id_str = data.get("id")

        if not payment_id_str:
            raise KeyError("Invalid response from YooKassa API: missing 'id'")

        provider_status = data.get("status")
        if provider_status not in {"pending", "waiting_for_capture", "succeeded", "canceled"}:
            raise KeyError("Invalid response from YooKassa API: unsupported status")

        confirmation: dict = data.get("confirmation", {})
        payment_url = confirmation.get("confirmation_url")

        if provider_status in {"pending", "waiting_for_capture"} and not payment_url:
            raise KeyError("Invalid response from YooKassa API: missing 'confirmation_url'")

        return PaymentResultDto(
            id=UUID(payment_id_str),
            url=str(payment_url) if payment_url else None,
            provider_status=str(provider_status),
        )

    def _verify_webhook(self, request: Request) -> bool:
        ip = self._get_ip(request.headers)

        if not self._is_ip_trusted(ip):
            logger.critical(f"Webhook received from untrusted IP: '{ip}'")
            return False

        return True
