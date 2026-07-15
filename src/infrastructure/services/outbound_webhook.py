import hashlib
import hmac
import time
from dataclasses import asdict

import aiohttp
from loguru import logger

from src.application.events import BaseEvent, UserPurchaseEvent
from src.core.config import AppConfig
from src.infrastructure.common import json
from src.infrastructure.services.event_bus import on_event

# Extension point: add an event type here to start delivering it.
OUTBOUND_WEBHOOK_EVENTS: tuple[type[BaseEvent], ...] = (UserPurchaseEvent,)

SIGNATURE_HEADER = "X-Webhook-Signature"
EVENT_HEADER = "X-Webhook-Event"
EVENT_ID_HEADER = "X-Webhook-Event-Id"
TIMESTAMP_HEADER = "X-Webhook-Timestamp"


class OutboundWebhookService:
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    @on_event(*OUTBOUND_WEBHOOK_EVENTS)
    async def enqueue_delivery(self, event: BaseEvent) -> None:
        if not self._config.webhook.enabled:
            return

        # Local import breaks the module cycle (tasks/webhooks.py imports the sender
        # from this package).
        from src.infrastructure.taskiq.tasks.webhooks import (  # noqa: PLC0415
            send_outbound_webhook_task,
        )

        payload = json.encode(
            {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "occurred_at": event.occurred_at,
                "data": asdict(event),
            }
        ).decode()

        webhook = self._config.webhook
        await (
            send_outbound_webhook_task.kicker()
            .with_labels(max_retries=webhook.retries, delay=webhook.retry_delay)
            .kiq(payload, event.event_type, str(event.event_id))  # type: ignore[call-overload]
        )
        logger.info(f"Outbound webhook enqueued for event '{event.event_type}'")


class OutboundWebhookSender:
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    async def deliver(self, payload: str, event_type: str, event_id: str) -> None:
        settings = self._config.webhook
        body = payload.encode("utf-8")
        secret = settings.secret.get_secret_value().encode("utf-8")
        signature = hmac.new(secret, body, hashlib.sha256).hexdigest()

        headers = {
            "Content-Type": "application/json",
            SIGNATURE_HEADER: signature,
            EVENT_HEADER: event_type,
            EVENT_ID_HEADER: event_id,
            TIMESTAMP_HEADER: str(int(time.time())),
        }

        timeout = aiohttp.ClientTimeout(total=settings.timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(settings.url, data=body, headers=headers) as response:
                if response.status >= 300:
                    text = (await response.text())[:200]
                    raise RuntimeError(
                        f"Outbound webhook to '{settings.url}' failed: "
                        f"HTTP {response.status} {text}"
                    )

        logger.info(f"Outbound webhook delivered: '{event_type}' ({event_id})")
