import asyncio
from collections import deque
from typing import Callable, Deque, Optional

from dishka import AsyncContainer
from loguru import logger

from src.application.dto import NotificationTaskDto
from src.core.constants import BATCH_DELAY, BATCH_SIZE_10
from src.core.utils.iterables import chunked


class NotificationQueue:
    def __init__(self) -> None:
        self._interval = 1.0
        self._queue: Deque[NotificationTaskDto] = deque()
        self._lock = asyncio.Lock()
        self._task: Optional[asyncio.Task] = None
        self._sender: Optional[Callable] = None

    def start(self, sender: Callable) -> None:
        if self._task is None:
            self._sender = sender
            self._task = asyncio.create_task(self._worker())
            logger.info("Notification worker started")

    async def enqueue(self, task: NotificationTaskDto) -> None:
        async with self._lock:
            self._queue.append(task)

    async def drain(self) -> None:
        if not self._sender:
            return

        async with self._lock:
            if not self._queue:
                return
            batch = list(self._queue)
            self._queue.clear()

        logger.debug(f"Draining '{len(batch)}' queued notifications on shutdown")
        for task in batch:
            try:
                await self._sender(task)
            except Exception as e:
                logger.error(
                    f"Notification drain failed: {type(e).__name__}: {e}",
                    exc_info=e,
                )

    async def _worker(self) -> None:
        sender = self._sender
        if sender is None:
            raise RuntimeError("Notification worker started without a sender")
        while True:
            await asyncio.sleep(self._interval)

            async with self._lock:
                if not self._queue:
                    continue

                batch = list(self._queue)
                self._queue.clear()

            logger.debug(f"Processing '{len(batch)}' queued notifications")

            for i, chunk in enumerate(chunked(batch, BATCH_SIZE_10), start=1):
                chunk_start = asyncio.get_running_loop().time()

                results = []
                for task in chunk:
                    try:
                        result = await sender(task)
                        results.append(result)
                    except Exception as e:
                        results.append(e)
                        logger.error(
                            f"Notification task failed: {type(e).__name__}: {e}",
                            exc_info=e,
                        )

                elapsed = asyncio.get_running_loop().time() - chunk_start
                errors = sum(1 for r in results if isinstance(r, Exception))
                logger.debug(
                    f"Chunk '{i}': {len(results) - errors} success, "
                    f"{errors} errors in {elapsed:.2f}s"
                )

                wait_time = BATCH_DELAY - elapsed
                if wait_time > 0:
                    await asyncio.sleep(wait_time)


class NotificationWorker:
    def __init__(self, queue: NotificationQueue) -> None:
        self._queue = queue
        self._container_factory: Optional[Callable[[], AsyncContainer]] = None

    def set_container_factory(self, factory: Callable[[], AsyncContainer]) -> None:
        self._container_factory = factory
        self._queue.start(self._process_task)
        logger.info("NotificationWorker container factory set, worker started")

    async def enqueue(self, task: NotificationTaskDto) -> None:
        await self._queue.enqueue(task)

    async def shutdown(self) -> None:
        await self._queue.drain()

    async def _process_task(self, task: NotificationTaskDto) -> None:
        if not self._container_factory:
            raise RuntimeError("NotificationWorker container factory not set")

        from src.infrastructure.services.notification import NotificationService  # noqa: PLC0415

        async with self._container_factory()() as request_container:
            service: NotificationService = await request_container.get(NotificationService)
            await service._process_task(task)
