import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from redis.exceptions import LockError

from src.application.common import SubscriptionMutationLockLostError
from src.infrastructure.services.subscription_mutation_lock import (
    RedisSubscriptionMutationLock,
)


class _FakeRedisLock:
    def __init__(self, *, extend_result: bool = True) -> None:
        self.acquire = AsyncMock(return_value=True)
        self.extend = AsyncMock(return_value=extend_result)
        self.owned = AsyncMock(return_value=extend_result)
        self.release = AsyncMock()


@pytest.mark.asyncio
async def test_subscription_lock_renews_and_releases_only_while_owned() -> None:
    lock = _FakeRedisLock()
    redis = SimpleNamespace(lock=Mock(return_value=lock))
    service = RedisSubscriptionMutationLock(redis)  # type: ignore[arg-type]
    service.HEARTBEAT_INTERVAL_SECONDS = 0.001

    async with service.hold(42):
        # Windows' event-loop timer resolution can coalesce 1 ms and 10 ms
        # deadlines; leave enough distance for the heartbeat task to run.
        await asyncio.sleep(0.05)

    redis.lock.assert_called_once_with(
        "remnashop:subscription-mutation:v1:42",
        timeout=300,
        blocking_timeout=60,
    )
    lock.extend.assert_awaited()
    assert lock.extend.await_args.kwargs == {"replace_ttl": True}
    assert lock.extend.await_args.args == (300,)
    assert lock.owned.await_count == 2
    lock.release.assert_awaited_once()


@pytest.mark.asyncio
async def test_subscription_lock_lease_loss_cancels_writer_and_never_releases_successor() -> None:
    lock = _FakeRedisLock(extend_result=False)
    redis = SimpleNamespace(lock=Mock(return_value=lock))
    service = RedisSubscriptionMutationLock(redis)  # type: ignore[arg-type]
    service.HEARTBEAT_INTERVAL_SECONDS = 0.001

    with pytest.raises(
        SubscriptionMutationLockLostError,
        match="lease lost for user '42'",
    ):
        async with service.hold(42):
            await asyncio.sleep(0.1)

    lock.owned.assert_awaited_once()
    lock.release.assert_not_awaited()


@pytest.mark.asyncio
async def test_subscription_lock_is_reentrant_for_lower_level_update_fence() -> None:
    lock = _FakeRedisLock()
    redis = SimpleNamespace(lock=Mock(return_value=lock))
    service = RedisSubscriptionMutationLock(redis)  # type: ignore[arg-type]

    async with service.hold(42):
        async with service.hold(42):
            pass

    redis.lock.assert_called_once()
    lock.acquire.assert_awaited_once()
    lock.release.assert_awaited_once()


@pytest.mark.asyncio
async def test_subscription_lock_never_returns_success_when_final_release_loses_owner() -> None:
    lock = _FakeRedisLock()
    lock.release.side_effect = LockError("expired")
    redis = SimpleNamespace(lock=Mock(return_value=lock))
    service = RedisSubscriptionMutationLock(redis)  # type: ignore[arg-type]

    with pytest.raises(SubscriptionMutationLockLostError):
        async with service.hold(42):
            pass
