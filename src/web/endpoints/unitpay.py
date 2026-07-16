import re
from decimal import Decimal
from typing import Optional
from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Form, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from loguru import logger

from src.application.common import TranslatorHub
from src.application.common.dao import TransactionDao, UserDao
from src.application.common.invoice import build_invoice_description
from src.application.dto import TransactionDto
from src.application.use_cases.gateways.queries.providers import GetPaymentGatewayInstance
from src.core.config import AppConfig
from src.core.constants import API_V1, UNITPAY_PAY_PATH
from src.core.enums import PaymentGatewayType, TransactionStatus
from src.infrastructure.payment_gateways import UnitPayGateway

router = APIRouter(prefix=API_V1 + UNITPAY_PAY_PATH, include_in_schema=False)

# Matches the de-facto email pattern used across src/web/schemas/auth.py.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_STYLE = (
    ":root{color-scheme:light dark}*{box-sizing:border-box}"
    "body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;"
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;"
    "background:#f4f5f7;color:#1c1c1e;padding:16px}"
    ".card{background:#fff;border-radius:16px;padding:28px 24px;max-width:380px;width:100%;"
    "box-shadow:0 10px 40px rgba(0,0,0,.12)}"
    "h1{font-size:19px;margin:0 0 6px}p{margin:0 0 18px;font-size:14px;opacity:.7}"
    "label{display:block;font-size:13px;margin-bottom:6px;opacity:.8}"
    "input{width:100%;padding:12px 14px;font-size:15px;border:1px solid #d0d0d5;border-radius:10px;"
    "margin-bottom:14px}"
    "button{width:100%;padding:13px;font-size:15px;font-weight:600;border:0;border-radius:10px;"
    "background:#2ea44f;color:#fff;cursor:pointer}button:hover{background:#2c974b}"
    ".err{color:#d1242f;font-size:13px;margin:-6px 0 12px}"
    "@media(prefers-color-scheme:dark){body{background:#121214;color:#f2f2f5}"
    ".card{background:#1e1e22}input{background:#0f0f12;color:#f2f2f5;border-color:#3a3a3f}}"
)


def _page(body: str) -> str:
    return (
        '<!doctype html><html lang="ru"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Оплата</title><style>{_STYLE}</style></head>"
        f'<body><div class="card">{body}</div></body></html>'
    )


def _form_page(
    payment_id: UUID, amount: Decimal, symbol: str, error: Optional[str] = None
) -> str:
    err_html = f'<div class="err">{error}</div>' if error else ""
    action = f"{API_V1}{UNITPAY_PAY_PATH}/{payment_id}"
    body = (
        "<h1>Оплата подписки</h1>"
        f"<p>К оплате: <b>{amount} {symbol}</b></p>"
        f'<form method="post" action="{action}">'
        '<label for="email">E-mail для чека</label>'
        '<input id="email" type="email" name="email" required '
        'placeholder="you@example.com" autofocus>'
        f"{err_html}"
        '<button type="submit">Перейти к оплате</button></form>'
    )
    return _page(body)


def _error_page(message: str) -> str:
    return _page(f"<h1>Ошибка</h1><p>{message}</p>")


async def _load_pending_unitpay(
    transaction_dao: TransactionDao, payment_id: UUID
) -> Optional[TransactionDto]:
    transaction = await transaction_dao.get_by_payment_id(payment_id)
    if (
        transaction is None
        or transaction.status != TransactionStatus.PENDING
        or transaction.gateway_type != PaymentGatewayType.UNITPAY
    ):
        return None
    return transaction


@router.get("/{payment_id}")
@inject
async def unitpay_page(
    payment_id: UUID,
    transaction_dao: FromDishka[TransactionDao],
) -> Response:
    transaction = await _load_pending_unitpay(transaction_dao, payment_id)
    if transaction is None:
        return HTMLResponse(
            _error_page("Платёж не найден или уже обработан."),
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return HTMLResponse(
        _form_page(payment_id, transaction.pricing.final_amount, transaction.currency.symbol)
    )


@router.post("/{payment_id}")
@inject
async def unitpay_submit(
    payment_id: UUID,
    transaction_dao: FromDishka[TransactionDao],
    user_dao: FromDishka[UserDao],
    translator_hub: FromDishka[TranslatorHub],
    get_payment_gateway_instance: FromDishka[GetPaymentGatewayInstance],
    config: FromDishka[AppConfig],
    email: str = Form(...),
) -> Response:
    transaction = await _load_pending_unitpay(transaction_dao, payment_id)
    if transaction is None:
        return HTMLResponse(
            _error_page("Платёж не найден или уже обработан."),
            status_code=status.HTTP_404_NOT_FOUND,
        )

    email = email.strip().lower()
    if not _EMAIL_RE.match(email):
        return HTMLResponse(
            _form_page(
                payment_id,
                transaction.pricing.final_amount,
                transaction.currency.symbol,
                error="Введите корректный e-mail.",
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    user = await user_dao.get_by_id(transaction.user_id)
    locale = user.language if user else config.default_locale
    i18n = translator_hub.get_translator_by_locale(locale)
    desc = build_invoice_description(i18n, transaction.purchase_type, transaction.plan_snapshot)

    try:
        gateway = await get_payment_gateway_instance.system(PaymentGatewayType.UNITPAY)
    except Exception as e:
        logger.warning(f"UnitPay gateway unavailable for '{payment_id}': {e}")
        return HTMLResponse(
            _error_page("Платёжный шлюз недоступен."),
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    if not isinstance(gateway, UnitPayGateway):
        logger.error(f"Expected UnitPayGateway, got '{type(gateway).__name__}'")
        return HTMLResponse(
            _error_page("Платёжный шлюз недоступен."),
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    try:
        redirect_url = await gateway.create_hosted_payment(
            payment_id, transaction.pricing.final_amount, desc, email
        )
    except Exception as e:
        logger.exception(f"UnitPay payment creation failed for '{payment_id}': {e}")
        return HTMLResponse(
            _error_page("Не удалось создать платёж. Попробуйте позже."),
            status_code=status.HTTP_502_BAD_GATEWAY,
        )

    return RedirectResponse(redirect_url, status_code=status.HTTP_303_SEE_OTHER)
