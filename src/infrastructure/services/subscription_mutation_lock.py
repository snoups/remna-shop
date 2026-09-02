import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any
from weakref import WeakKeyDictionary

from redis.asyncio import Redis
from redis.exceptions import LockError

from src.application.common import (
    SubscriptionMutationLock,
    SubscriptionMutationLockLostError,
)


class RedisSubscriptionMutationLock(SubscriptionMutationLock):
    LEASE_SECONDS = 300
    HEARTBEAT_INTERVAL_SECONDS = 60

    def __init__(self, redis: Redis) -> None:
        self.redis = redis
        self._held_by_task: WeakKeyDictionary[
            asyncio.Task[Any],
            dict[int, int],
        ] = WeakKeyDictionary()

    @asynccontextmanager
    async def hold(self, user_id: int) -> AsyncIterator[None]:  # noqa: C901
        owner_task = asyncio.current_task()
        if owner_task is None:
            raise RuntimeError("Subscription mutation lock requires an asyncio task")

        held = self._held_by_task.setdefault(owner_task, {})
        if user_id in held:
            held[user_id] += 1
            try:
                yield
            finally:
                held[user_id] -= 1
            return

        lock = self.redis.lock(
            f"remnashop:subscription-mutation:v1:{user_id}",
            timeout=self.LEASE_SECONDS,
            blocking_timeout=60,
        )
        acquired = await lock.acquire()
        if not acquired:
            raise TimeoutError(f"Subscription mutation lock timed out for user '{user_id}'")
        held[user_id] = 1

        lease_error: Exception | None = None

        async def renew_lease() -> None:
            nonlocal lease_error
            while True:
                await asyncio.sleep(self.HEARTBEAT_INTERVAL_SECONDS)
                try:
                    extended = await lock.extend(
                        self.LEASE_SECONDS,
                        replace_ttl=True,
                    )
                    if not extended:
                        raise RuntimeError("Subscription mutation lease is no longer owned")
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    lease_error = exc
                    # Stop the protected operation before another owner can mutate
                    # the same full Remnawave user snapshot.
                    owner_task.cancel()
                    return

        heartbeat = asyncio.create_task(
            renew_lease(),
            name=f"subscription-mutation-lock-heartbeat:{user_id}",
        )
        body_completed = False
        try:
            try:
                yield
            except asyncio.CancelledError:
                if lease_error is not None:
                    raise SubscriptionMutationLockLostError(
                        f"Subscription mutation lease lost for user '{user_id}'"
                    ) from lease_error
                raise
            if lease_error is not None:
                raise SubscriptionMutationLockLostError(
                    f"Subscription mutation lease lost for user '{user_id}'"
                ) from lease_error
            if not await lock.owned():
                raise SubscriptionMutationLockLostError(
                    f"Subscription mutation lease lost for user '{user_id}'"
                )
            body_completed = True
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
            try:
                # Redis Lock.release clears its local token before the Lua check.
                # Check ownership first so an expired lease can never release a
                # successor's lock.
                if await lock.owned():
                    await lock.release()
                elif body_completed:
                    raise SubscriptionMutationLockLostError(
                        f"Subscription mutation lease lost for user '{user_id}'"
                    )
            except LockError:
                # The heartbeat already fails the protected operation on ownership
                # loss. Never report success if expiry races the final release.
                raise SubscriptionMutationLockLostError(
                    f"Subscription mutation lease lost for user '{user_id}'"
                )
            finally:
                held.pop(user_id, None)
                if not held:
                    self._held_by_task.pop(owner_task, None)
