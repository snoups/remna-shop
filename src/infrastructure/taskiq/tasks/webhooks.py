from dishka.integrations.taskiq import FromDishka, inject

from src.infrastructure.services import OutboundWebhookSender
from src.infrastructure.taskiq.broker import broker


@broker.task(retry_on_error=True)
@inject(patch_module=True)
async def send_outbound_webhook_task(
    payload: str,
    event_type: str,
    event_id: str,
    sender: FromDishka[OutboundWebhookSender],
) -> None:
    await sender.deliver(payload, event_type, event_id)
