from src.infrastructure.taskiq.tasks.subscription_email_reminders import (
    deliver_subscription_email_reminders_task,
    generate_subscription_email_reminders_task,
)


def test_subscription_email_jobs_have_bounded_scheduler_cadence() -> None:
    assert generate_subscription_email_reminders_task.labels == {
        "schedule": [{"cron": "17 * * * *"}],
        "retry_on_error": False,
    }
    assert deliver_subscription_email_reminders_task.labels == {
        "schedule": [{"cron": "* * * * *"}],
        "retry_on_error": False,
    }
