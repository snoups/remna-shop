from unittest.mock import AsyncMock, MagicMock

import pytest

from src.infrastructure.redis.auth import (
    INCREMENT_WITH_TTL_SCRIPT,
    RELEASE_LOCK_SCRIPT,
    RedisAuthRepository,
)


@pytest.mark.asyncio
async def test_password_reset_request_reservation_is_atomic_and_expiring() -> None:
    redis = MagicMock()
    redis.set = AsyncMock(return_value=True)
    repository = RedisAuthRepository(redis)

    reserved = await repository.reserve_password_reset_request("identity-hash", 60)

    assert reserved is True
    redis.set.assert_awaited_once_with(
        "password_reset_request:identity-hash", "1", ex=60, nx=True
    )


@pytest.mark.asyncio
async def test_password_reset_attempt_increment_uses_atomic_ttl_script() -> None:
    redis = MagicMock()
    redis.eval = AsyncMock(return_value=3)
    repository = RedisAuthRepository(redis)

    attempts = await repository.increment_password_reset_attempts("identity-hash", 900)

    assert attempts == 3
    redis.eval.assert_awaited_once_with(
        INCREMENT_WITH_TTL_SCRIPT, 1, "password_reset_attempts:identity-hash", 900
    )


@pytest.mark.asyncio
async def test_password_reset_lock_is_owned_and_expiring() -> None:
    redis = MagicMock()
    redis.set = AsyncMock(return_value=True)
    repository = RedisAuthRepository(redis)

    acquired = await repository.acquire_password_reset_lock("identity-hash", "token", 15)

    assert acquired is True
    redis.set.assert_awaited_once_with(
        "password_reset_lock:identity-hash", "token", ex=15, nx=True
    )


@pytest.mark.asyncio
async def test_password_reset_lock_release_only_deletes_owned_lock() -> None:
    redis = MagicMock()
    redis.eval = AsyncMock(return_value=1)
    repository = RedisAuthRepository(redis)

    await repository.release_password_reset_lock("identity-hash", "token")

    redis.eval.assert_awaited_once_with(
        RELEASE_LOCK_SCRIPT, 1, "password_reset_lock:identity-hash", "token"
    )
