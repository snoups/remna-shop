from dishka.integrations.taskiq import FromDishka, inject

from src.application.use_cases.referral.commands.rewards import RetryPendingReferralRewards
from src.infrastructure.taskiq.broker import broker


@broker.task(schedule=[{"cron": "* * * * *"}], retry_on_error=False)
@inject(patch_module=True)
async def retry_pending_referral_rewards_task(
    retry_pending_referral_rewards: FromDishka[RetryPendingReferralRewards],
) -> None:
    await retry_pending_referral_rewards.system()
