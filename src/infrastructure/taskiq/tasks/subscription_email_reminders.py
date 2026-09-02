from dishka.integrations.taskiq import FromDishka, inject

from src.application.use_cases.notification import (
    DeliverSubscriptionExpirationEmailReminders,
    GenerateSubscriptionExpirationEmailReminders,
)
from src.infrastructure.taskiq.broker import broker


@broker.task(schedule=[{"cron": "17 * * * *"}], retry_on_error=False)
@inject(patch_module=True)
async def generate_subscription_email_reminders_task(
    generate_reminders: FromDishka[GenerateSubscriptionExpirationEmailReminders],
) -> None:
    await generate_reminders.system()


@broker.task(schedule=[{"cron": "* * * * *"}], retry_on_error=False)
@inject(patch_module=True)
async def deliver_subscription_email_reminders_task(
    deliver_reminders: FromDishka[DeliverSubscriptionExpirationEmailReminders],
) -> None:
    await deliver_reminders.system()
