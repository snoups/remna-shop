from abc import ABC, abstractmethod
from decimal import Decimal
from ipaddress import ip_address, ip_network
from typing import Any, Optional, Protocol, Union
from uuid import UUID

import orjson
from aiogram import Bot
from fastapi import Request, Response
from httpx import AsyncClient, Timeout
from loguru import logger
from starlette.datastructures import Headers

from src.application.dto import PaymentGatewayDto, PaymentResultDto
from src.core.config import AppConfig
from src.core.constants import T_ME
from src.core.enums import TransactionStatus


class PaymentGatewayFactory(Protocol):
    def __call__(self, gateway: "PaymentGatewayDto") -> "BasePaymentGateway": ...


class BasePaymentGateway(ABC):
    data: PaymentGatewayDto
    bot: Bot

    _bot_username: Optional[str]

    NETWORKS: list[str] = []

    def __init__(self, gateway: PaymentGatewayDto, bot: Bot, config: AppConfig) -> None:
        self.data = gateway
        self.bot = bot
        self.config = config
        self._bot_username: Optional[str] = None

        logger.debug(f"{self.__class__.__name__} Initialized")

    @abstractmethod
    async def handle_create_payment(self, amount: Decimal, details: str) -> PaymentResultDto: ...

    async def create_payment(
        self,
        amount: Decimal,
        details: str,
        idempotency_key: Optional[str] = None,
    ) -> PaymentResultDto:
        # Most providers do not expose an idempotency primitive. Keeping this
        # adapter-level wrapper preserves their existing implementations while
        # allowing capable providers to bind a durable operation to a stable key.
        return await self.handle_create_payment(amount, details)

    async def build_payment_request(
        self,
        amount: Decimal,
        details: str,
        *,
        return_url: Optional[str] = None,
    ) -> dict[str, Any]:
        """Build the exact, JSON-serializable request persisted before provider I/O."""
        return {
            "version": 1,
            "amount": str(amount),
            "details": details,
            "return_url": return_url,
        }

    async def create_payment_from_request(
        self,
        request_snapshot: dict[str, Any],
        *,
        idempotency_key: Optional[str],
    ) -> PaymentResultDto:
        try:
            amount = Decimal(str(request_snapshot["amount"]))
            details = str(request_snapshot["details"])
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError("Invalid persisted provider request") from exc
        return await self.create_payment(amount, details, idempotency_key=idempotency_key)

    def payment_owner_fingerprint(self) -> Optional[str]:
        """Return a non-secret stable fingerprint for replay-owner validation."""
        return None

    async def verify_payment_result(
        self,
        payment_id: UUID,
        request_snapshot: dict[str, Any],
    ) -> PaymentResultDto:
        raise NotImplementedError("This gateway does not support exact payment inspection")

    @abstractmethod
    async def handle_webhook(
        self,
        request: Request,
    ) -> Union[tuple[UUID, TransactionStatus], None]: ...

    async def build_webhook_response(self, request: Request) -> Response:
        return Response(status_code=200)

    async def _get_bot_redirect_url(self) -> str:
        if self._bot_username is None:
            self._bot_username = (await self.bot.get_me()).username
        return f"{T_ME}{self._bot_username}"

    async def _get_webhook_data(self, request: Request) -> dict:
        try:
            data = orjson.loads(await request.body())

            if not isinstance(data, dict):
                raise ValueError("Payload is not a dictionary")

            logger.debug("Webhook payload parsed (fields={fields})", fields=sorted(data))
            return data
        except (orjson.JSONDecodeError, ValueError) as e:
            logger.error(
                "Failed to parse webhook payload (error_type={error_type})",
                error_type=type(e).__name__,
            )
            raise ValueError("Invalid webhook payload") from e

    def _make_client(
        self,
        base_url: str,
        auth: Optional[tuple[str, str]] = None,
        headers: Optional[dict[str, str]] = None,
        timeout: float = 30.0,
    ) -> AsyncClient:
        return AsyncClient(base_url=base_url, auth=auth, headers=headers, timeout=Timeout(timeout))

    def _is_test_payment(self, payment_id: str) -> bool:
        return payment_id.startswith("test:")

    def _is_ip_in_network(self, ip: str, network: str) -> bool:
        try:
            return ip_address(ip) in ip_network(network, strict=False)
        except Exception as e:
            logger.error(f"Failed to check IP '{ip}' in network '{network}': {e}")
            return False

    def _is_ip_trusted(self, ip: str) -> bool:
        return any(self._is_ip_in_network(ip, net) for net in self.NETWORKS)

    def _get_ip(self, headers: Headers) -> str:
        ip = (
            headers.get("CF-Connecting-IP")
            or headers.get("X-Real-IP")
            or headers.get("X-Forwarded-For")
        )

        if not ip:
            raise PermissionError("Client IP not found in request headers")

        return ip
