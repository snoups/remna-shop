from typing import Any, Optional

from dishka import AsyncContainer
from loguru import logger
from taskiq import TaskiqMessage, TaskiqResult
from taskiq.abc.middleware import TaskiqMiddleware

from src.application.common import EventPublisher
from src.application.events import ErrorEvent
from src.core.config import AppConfig


class ErrorMiddleware(TaskiqMiddleware):
    async def on_error(
        self,
        message: TaskiqMessage,
        result: TaskiqResult[Any],
        exception: BaseException,
    ) -> None:
        logger.error(f"Task '{message.task_name}' error: {exception}")

        # For retryable tasks, notify admins only after the final attempt
        # (SmartRetryMiddleware increments '_retries' the same way before comparing).
        if str(message.labels.get("retry_on_error", "")).lower() in ("true", "1"):
            retries = int(message.labels.get("_retries", 0)) + 1
            max_retries = int(message.labels.get("max_retries", 5))
            if retries < max_retries:
                logger.warning(
                    f"Task '{message.task_name}' will be retried ({retries}/{max_retries})"
                )
                return

        container: Optional[AsyncContainer] = self.broker.custom_dependency_context.get(
            AsyncContainer
        )

        if not container:
            logger.error("Dishka container not found in taskiq broker context")
            return

        try:
            config = await container.get(AppConfig)
            event_publisher = await container.get(EventPublisher)
            error_event = ErrorEvent(**config.build.data, exception=exception)
            await event_publisher.publish(error_event)
        except Exception as e:
            logger.error(f"Failed to publish error event: {e}")
