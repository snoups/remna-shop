# Контракт: приём webhook-событий от Remnashop

Remnashop (Telegram-бот продажи VPN-подписок) отправляет HTTP-уведомления о доменных
событиях на ваш endpoint. Этот документ — всё, что нужно для реализации обработчика.

## 1. Транспорт

- **Метод:** `POST` на один URL (путь любой, задаётся на стороне бота).
- **Content-Type:** `application/json`, тело в UTF-8, компактный JSON (без пробелов).
- **Таймаут отправителя:** 15 секунд (настраиваемо). Отвечайте быстро; тяжёлую
  обработку выполняйте асинхронно после ответа.
- **Подтверждение доставки:** любой ответ `2xx`. Тело ответа игнорируется.
- **Ретраи:** при не-2xx, таймауте или сетевой ошибке отправитель повторит запрос.
  По умолчанию всего 5 попыток с экспоненциальной задержкой (база 15 сек × номер
  попытки + джиттер, потолок 120 сек). Число попыток и база настраиваемы.

## 2. Заголовки запроса

| Заголовок | Пример | Описание |
|---|---|---|
| `X-Webhook-Signature` | `3f2a…` (64 hex) | HMAC-SHA256 от сырых байтов тела, hex lowercase |
| `X-Webhook-Event` | `UserPurchaseEvent` | Тип события (имя класса) |
| `X-Webhook-Event-Id` | UUID | Уникальный ID события — **ключ идемпотентности** |
| `X-Webhook-Timestamp` | `1783108730` | Unix-время отправки (секунды, UTC) |
| `Content-Type` | `application/json` | |

## 3. Проверка подписи (обязательно)

Общий секрет (строка) передаётся вам по защищённому каналу отдельно.

```python
import hashlib, hmac

def verify(raw_body: bytes, signature_header: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)
```

Критично:

1. **Считайте HMAC от сырых байтов тела запроса** — до какого-либо JSON-парсинга.
   Никогда не пересериализуйте распарсенный JSON для проверки: порядок ключей,
   пробелы и экранирование не совпадут, и подпись «сломается».
2. Сравнивайте через constant-time функцию (`hmac.compare_digest` и аналоги).
3. Невалидная подпись → ответ `401`, тело не обрабатывать.
4. (Рекомендуется) отклоняйте запросы с `|now - X-Webhook-Timestamp| > 300` сек —
   защита от replay. Учтите: ретрай приходит с новым timestamp и той же подписью тела.

## 4. Идемпотентность

Из-за ретраев одно событие может быть доставлено **более одного раза**
(например, если вы ответили 200, но ответ не дошёл). Храните обработанные
`X-Webhook-Event-Id` (он же `event_id` в теле) и повторную доставку
подтверждайте `200` без повторной обработки.

## 5. Тело запроса

Конверт одинаков для всех типов событий:

```json
{
  "event_id": "uuid",
  "event_type": "ИмяКлассаСобытия",
  "occurred_at": "ISO-8601 с таймзоной (UTC)",
  "data": { "...поля события..." }
}
```

`data` дублирует `event_id`/`occurred_at` — это нормально, игнорируйте.

**Неизвестные типы событий отвечайте `200` и пропускайте**: набор событий будет
расширяться, обработчик не должен падать на новом `event_type`. Аналогично —
не делайте strict-валидацию на «лишние» поля внутри `data`.

## 6. Событие `UserPurchaseEvent` (успешная оплата)

Отправляется после успешного проведения платежа и выдачи подписки.

```json
{
  "event_id": "0f80a4ba-c979-47d2-afb4-e88996960465",
  "event_type": "UserPurchaseEvent",
  "occurred_at": "2026-07-03T18:38:50.339656+00:00",
  "data": {
    "event_id": "0f80a4ba-c979-47d2-afb4-e88996960465",
    "occurred_at": "2026-07-03T18:38:50.339656+00:00",
    "notification_type": "SUBSCRIPTION",

    "user_id": 42,
    "telegram_id": 123456789,
    "username": "testuser",
    "email": null,
    "name": "Test User",

    "purchase_type": "NEW",
    "is_trial_plan": false,

    "payment_id": "dcf883b6-0ba6-48c5-822b-a06c534cac8c",
    "gateway_type": "TELEGRAM_STARS",
    "final_amount": "99.90",
    "original_amount": "111.00",
    "discount_percent": 10,
    "currency": "₽",

    "plan_name": ["Premium", {}],
    "plan_type": "TRAFFIC",
    "plan_traffic_limit": "100 GB",
    "plan_device_limit": "3",
    "plan_duration": "30 days",

    "previous_plan_name": "N/A",
    "previous_plan_type": {"key": "plan-type", "plan_type": "N/A"},
    "previous_plan_traffic_limit": "N/A",
    "previous_plan_device_limit": "N/A",
    "previous_plan_duration": "N/A"
  }
}
```

### Поля `data`

| Поле | Тип | Описание |
|---|---|---|
| `user_id` | int | ID пользователя в боте |
| `telegram_id` | int \| null | Telegram ID пользователя |
| `username` | string \| null | Telegram username (без `@`) |
| `email` | string \| null | Email, если известен |
| `name` | string | Отображаемое имя |
| `purchase_type` | `"NEW"` \| `"RENEW"` \| `"CHANGE"` | Новая покупка / продление / смена тарифа |
| `is_trial_plan` | bool | Куплен ли триальный план |
| `payment_id` | string (UUID) | ID транзакции в боте — для сверки с платёжкой |
| `gateway_type` | string | Платёжный шлюз: `TELEGRAM_STARS`, `YOOKASSA`, `CRYPTOMUS`, `CRYPTOPAY`, `ROBOKASSA` и др. |
| `final_amount` | **string** (decimal) | Сумма, реально уплаченная пользователем (после скидки). Строка — парсить как Decimal, не float |
| `original_amount` | **string** (decimal) | Цена до скидки |
| `discount_percent` | int | Применённая скидка, 0–100 |
| `currency` | string | **Символ** валюты (`"₽"`, `"$"`, `"⭐"`), не ISO-код |
| `plan_name` | `[string, object]` | Имя тарифа — брать элемент `[0]` |
| `plan_type` | string | Тип плана (например, `TRAFFIC`) |
| `plan_traffic_limit` | string | Готовая строка («100 GB», «Unlimited») |
| `plan_device_limit` | string | Готовая строка |
| `plan_duration` | string | Готовая строка («30 days») |
| `previous_plan_*` | string \| object | Прежний тариф; осмысленны только при `purchase_type = "CHANGE"`, иначе `"N/A"` |
| `notification_type` | string | Служебное, игнорировать |

Примечания:
- `final_amount == "0"` возможен (100% скидка).
- Для `gateway_type = "TELEGRAM_STARS"` сумма указана в звёздах (`currency = "⭐"`).
- Поля `plan_*` — человекочитаемые строки, не для арифметики. Для сверки денег
  используйте `final_amount` + `payment_id`.

## 7. Матрица ответов обработчика

| Ситуация | Ваш ответ | Что сделает отправитель |
|---|---|---|
| Подпись валидна, событие обработано | `200` | Считает доставленным |
| Подпись валидна, событие-дубликат | `200` | Считает доставленным |
| Подпись валидна, неизвестный `event_type` | `200` | Считает доставленным |
| Невалидная подпись | `401` | Ретрай (подпись не изменится — после исчерпания попыток событие потеряно, алерт админам бота) |
| Временная ошибка на вашей стороне (БД недоступна и т.п.) | `5xx` | Ретрай с backoff |

## 8. Референс-обработчик (FastAPI)

```python
import hashlib
import hmac
import json
import os

from fastapi import FastAPI, Header, HTTPException, Request, Response

app = FastAPI()
SECRET = os.environ["REMNASHOP_WEBHOOK_SECRET"]
processed_ids: set[str] = set()  # в проде — таблица/Redis с TTL


@app.post("/remnashop/webhook")
async def remnashop_webhook(
    request: Request,
    x_webhook_signature: str = Header(...),
    x_webhook_event: str = Header(...),
    x_webhook_event_id: str = Header(...),
) -> Response:
    raw_body = await request.body()  # сырые байты — ДО парсинга

    expected = hmac.new(SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, x_webhook_signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    if x_webhook_event_id in processed_ids:
        return Response(status_code=200)  # дубликат — уже обработано

    payload = json.loads(raw_body)

    if x_webhook_event == "UserPurchaseEvent":
        data = payload["data"]
        # ... ваша логика: data["payment_id"], data["final_amount"], ...
    # неизвестные события — молча подтверждаем

    processed_ids.add(x_webhook_event_id)
    return Response(status_code=200)
```

## 9. Тестовые данные

Для локальной проверки подписи (секрет `test_secret_123`):

```bash
BODY='{"event_id":"test","event_type":"UserPurchaseEvent","occurred_at":"2026-07-03T00:00:00+00:00","data":{}}'
printf '%s' "$BODY" | openssl dgst -sha256 -hmac "test_secret_123" -hex
# → подпись для заголовка X-Webhook-Signature

curl -X POST http://localhost:8000/remnashop/webhook \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Signature: <подпись из команды выше>" \
  -H "X-Webhook-Event: UserPurchaseEvent" \
  -H "X-Webhook-Event-Id: test" \
  -H "X-Webhook-Timestamp: $(date +%s)" \
  -d "$BODY"
```
