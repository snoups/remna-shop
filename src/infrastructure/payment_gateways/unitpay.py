import base64
import hashlib
import re
import uuid
from decimal import Decimal
from hmac import compare_digest
from typing import Any, Final, Optional, Union, cast
from uuid import UUID

import orjson
from aiogram import Bot
from fastapi import Request
from fastapi.responses import JSONResponse
from httpx import AsyncClient, HTTPStatusError
from loguru import logger

from src.application.dto import PaymentGatewayDto, PaymentResultDto
from src.application.dto.payment_gateway import UnitPayGatewaySettingsDto
from src.core.config import AppConfig
from src.core.constants import API_V1, UNITPAY_PAY_PATH
from src.core.enums import TransactionStatus

from .base import BasePaymentGateway


# https://help.unitpay.ru/
class UnitPayGateway(BasePaymentGateway):
    _client: AsyncClient

    API_BASE: Final[str] = "https://unitpay.ru"
    # UnitPay concatenates signed values with this literal separator before hashing.
    SEPARATOR: Final[str] = "{up}"

    # The `/pay/{publicKey}` form is disabled for API-driven projects; payments are
    # created via the initPayment API, which returns a ready-to-open redirectUrl.
    INIT_METHOD: Final[str] = "initPayment"
    # UnitPay requires an explicit payment method; the bare method-chooser form 404s.
    # Used as the default when the gateway's `payment_type` setting is unset.
    PAYMENT_TYPE: Final[str] = "card"
    METHOD_PAY: Final[str] = "pay"

    _PARAM_RE: Final[re.Pattern[str]] = re.compile(r"params\[(?P<key>.+)]")

    def __init__(self, gateway: PaymentGatewayDto, bot: Bot, config: AppConfig) -> None:
        super().__init__(gateway, bot, config)

        if not isinstance(self.data.settings, UnitPayGatewaySettingsDto):
            raise TypeError(
                f"Invalid settings type: expected {UnitPayGatewaySettingsDto.__name__}, "
                f"got {type(self.data.settings).__name__}"
            )

        settings = cast(UnitPayGatewaySettingsDto, self.data.settings)
        if settings.public_key is None or settings.secret_key is None:
            raise ValueError("UnitPay gateway is not configured")

        self._public_key = settings.public_key
        # Public key is "<projectId>-<hash>"; the API authenticates by projectId.
        self._project_id = settings.public_key.split("-", 1)[0]
        self._secret_key = settings.secret_key.get_secret_value()
        self._test_mode = settings.test_mode
        # A fiscal receipt is attached only when a real VAT rate is set; `None` and
        # the literal "none" both mean "no receipt" (and thus no email to collect).
        vat = settings.vat
        self._vat = vat if vat and vat.strip().lower() != "none" else None
        self._payment_type = settings.payment_type or self.PAYMENT_TYPE

        self._client = self._make_client(base_url=self.API_BASE)

    async def handle_create_payment(self, amount: Decimal, details: str) -> PaymentResultDto:
        order_id = uuid.uuid4()
        # A fiscal receipt needs the buyer's email, which is collected on the hosted
        # page before the payment is created (create_hosted_payment). Without a
        # receipt there is nothing to collect, so create the payment now and point
        # the Pay button straight at UnitPay. Contract (amount/details) is untouched.
        if self._vat is not None:
            return PaymentResultDto(id=order_id, url=self._hosted_page_url(order_id))

        url = await self._init_payment(order_id, amount, details, customer_email=None)
        return PaymentResultDto(id=order_id, url=url)

    async def create_hosted_payment(
        self, account: UUID, amount: Decimal, desc: str, customer_email: str
    ) -> str:
        return await self._init_payment(account, amount, desc, customer_email)

    async def _init_payment(
        self, account: UUID, amount: Decimal, desc: str, customer_email: Optional[str]
    ) -> str:
        # `test` and `secretKey` are NOT part of the signature; everything else is.
        signed = {
            "account": str(account),
            "desc": desc[:128],
            "paymentType": self._payment_type,
            "projectId": self._project_id,
            "sum": self._format_amount(amount),
        }

        query: dict[str, str] = {"method": self.INIT_METHOD}
        for key, value in signed.items():
            query[f"params[{key}]"] = value
        # cashItems / customerEmail are extra params — UnitPay does not sign them.
        if self._vat is not None and customer_email is not None:
            query["params[cashItems]"] = self._build_cash_items(signed["desc"], amount)
            query["params[customerEmail]"] = customer_email
        if self._test_mode:
            query["params[test]"] = "1"
        query["params[secretKey]"] = self._secret_key
        query["params[signature]"] = self._sign(signed, method=self.INIT_METHOD)

        logger.debug(f"Creating UnitPay payment '{account}' (test={self._test_mode})")

        try:
            response = await self._client.get("api", params=query)
            response.raise_for_status()
            data = orjson.loads(response.content)
            return self._extract_redirect_url(data)

        except HTTPStatusError as e:
            logger.error(
                f"HTTP error creating UnitPay payment. "
                f"Status: '{e.response.status_code}', Body: {e.response.text}"
            )
            raise
        except (KeyError, orjson.JSONDecodeError) as e:
            logger.error(f"Failed to parse UnitPay response. Error: {e}")
            raise

    def _hosted_page_url(self, order_id: UUID) -> str:
        domain = self.config.domain.get_secret_value()
        return f"https://{domain}{API_V1}{UNITPAY_PAY_PATH}/{order_id}"

    async def handle_webhook(self, request: Request) -> Union[tuple[UUID, TransactionStatus], None]:
        logger.debug(f"Received {self.__class__.__name__} webhook request")

        method, params = self._parse_request(request)
        logger.debug(f"UnitPay webhook data: method='{method}', params={params}")

        if not self._verify_webhook(method, params):
            raise PermissionError("Webhook verification failed")

        # UnitPay probes with `check` before charging and reports `error` on failure;
        # only `pay` confirms a completed payment. Other methods are acknowledged
        # without a status change.
        if method != self.METHOD_PAY:
            logger.debug(f"UnitPay '{method}' notification acknowledged without status change")
            return None

        account = params.get("account")
        if not account:
            raise ValueError("Required field 'params[account]' is missing")

        return UUID(account), TransactionStatus.COMPLETED

    async def build_webhook_response(self, request: Request) -> JSONResponse:
        # UnitPay treats any {"result": {"message": ...}} body as an acknowledgement.
        return JSONResponse({"result": {"message": "OK"}})

    def _extract_redirect_url(self, data: dict[str, Any]) -> str:
        if "error" in data:
            message = data["error"].get("message", "unknown error")
            raise ValueError(f"UnitPay refused payment creation: {message}")

        redirect_url = data.get("result", {}).get("redirectUrl")
        if not redirect_url:
            raise KeyError("Invalid UnitPay response: missing 'result.redirectUrl'")

        return str(redirect_url)

    def _parse_request(self, request: Request) -> tuple[str, dict[str, str]]:
        method = request.query_params.get("method", "")
        params: dict[str, str] = {}
        for key, value in request.query_params.items():
            match = self._PARAM_RE.fullmatch(key)
            if match:
                params[match.group("key")] = value
        return method, params

    def _verify_webhook(self, method: str, params: dict[str, str]) -> bool:
        received = params.get("signature")
        if not received:
            logger.warning("UnitPay webhook is missing 'params[signature]'")
            return False

        expected = self._sign(params, method=method)
        if not compare_digest(expected, received):
            logger.warning("Invalid UnitPay webhook signature")
            return False

        return True

    def _sign(self, params: dict[str, str], method: Optional[str] = None) -> str:
        # sha256 of `[method] + <values sorted by key> + secretKey`, joined by `{up}`.
        parts = [params[key] for key in sorted(params) if key not in ("sign", "signature")]
        if method is not None:
            parts.insert(0, method)
        parts.append(self._secret_key)
        raw = self.SEPARATOR.join(parts)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _build_cash_items(self, name: str, amount: Decimal) -> str:
        # UnitPay expects a base64-encoded JSON array of receipt positions.
        item = {
            "name": name,
            "count": 1,
            "price": float(amount),
            "nds": self._vat,
        }
        return base64.b64encode(orjson.dumps([item])).decode()

    @staticmethod
    def _format_amount(amount: Decimal) -> str:
        return format(amount.quantize(Decimal("0.01")), "f")
