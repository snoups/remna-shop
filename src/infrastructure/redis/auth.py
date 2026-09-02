from typing import Any, Awaitable, Optional, cast

from redis.asyncio import Redis

from src.infrastructure.redis.key_builder import serialize_storage_key
from src.infrastructure.redis.keys import (
    EmailAuthAttemptsKey,
    EmailAuthChallengeKey,
    EmailAuthRequestKey,
    PasswordResetAttemptsKey,
    PasswordResetLockKey,
    PasswordResetRequestKey,
    RefreshTokenKey,
    UserTokensKey,
)

INCREMENT_WITH_TTL_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""

RELEASE_LOCK_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""

CONSUME_VALUE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


class RedisAuthRepository:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def store_refresh_token(self, token: str, user_id: int, ttl: int) -> None:
        token_key = serialize_storage_key(RefreshTokenKey(token=token))
        user_set_key = serialize_storage_key(UserTokensKey(user_id=user_id))
        await self.redis.setex(token_key, ttl, str(user_id))
        await self.redis.sadd(user_set_key, token)  # type: ignore[misc]
        await self.redis.expire(user_set_key, ttl)

    async def get_user_id_by_refresh_token(self, token: str) -> Optional[int]:
        key = serialize_storage_key(RefreshTokenKey(token=token))
        value = await self.redis.get(key)
        if value is None:
            return None
        return int(value)

    async def revoke_refresh_token(self, token: str) -> None:
        token_key = serialize_storage_key(RefreshTokenKey(token=token))
        value = await self.redis.getdel(token_key)
        if value is not None:
            user_set_key = serialize_storage_key(UserTokensKey(user_id=int(value)))
            await self.redis.srem(user_set_key, token)  # type: ignore[misc]

    async def get_and_revoke_refresh_token(self, token: str) -> Optional[int]:
        token_key = serialize_storage_key(RefreshTokenKey(token=token))
        value = await self.redis.getdel(token_key)
        if value is None:
            return None
        user_id = int(value)
        user_set_key = serialize_storage_key(UserTokensKey(user_id=user_id))
        await self.redis.srem(user_set_key, token)  # type: ignore[misc]
        return user_id

    async def revoke_all_user_tokens(self, user_id: int) -> None:
        user_set_key = serialize_storage_key(UserTokensKey(user_id=user_id))
        tokens = await self.redis.smembers(user_set_key)  # type: ignore[misc]
        if tokens:
            token_keys = [serialize_storage_key(RefreshTokenKey(token=t)) for t in tokens]
            await self.redis.delete(*token_keys)
        await self.redis.delete(user_set_key)

    async def reserve_password_reset_request(self, identity_hash: str, ttl: int) -> bool:
        key = serialize_storage_key(PasswordResetRequestKey(identity_hash=identity_hash))
        return bool(await self.redis.set(key, "1", ex=ttl, nx=True))

    async def increment_password_reset_attempts(self, identity_hash: str, ttl: int) -> int:
        key = serialize_storage_key(PasswordResetAttemptsKey(identity_hash=identity_hash))
        value = await cast(
            Awaitable[Any], self.redis.eval(INCREMENT_WITH_TTL_SCRIPT, 1, key, ttl)
        )
        return int(value)

    async def clear_password_reset_attempts(self, identity_hash: str) -> None:
        key = serialize_storage_key(PasswordResetAttemptsKey(identity_hash=identity_hash))
        await self.redis.delete(key)

    async def acquire_password_reset_lock(
        self, identity_hash: str, token: str, ttl: int
    ) -> bool:
        key = serialize_storage_key(PasswordResetLockKey(identity_hash=identity_hash))
        return bool(await self.redis.set(key, token, ex=ttl, nx=True))

    async def release_password_reset_lock(self, identity_hash: str, token: str) -> None:
        key = serialize_storage_key(PasswordResetLockKey(identity_hash=identity_hash))
        await cast(
            Awaitable[Any], self.redis.eval(RELEASE_LOCK_SCRIPT, 1, key, token)
        )

    async def reserve_email_auth_request(self, identity_hash: str, ttl: int) -> bool:
        key = serialize_storage_key(EmailAuthRequestKey(identity_hash=identity_hash))
        return bool(await self.redis.set(key, "1", ex=ttl, nx=True))

    async def store_email_auth_challenge(
        self, identity_hash: str, code_hash: str, ttl: int
    ) -> None:
        key = serialize_storage_key(EmailAuthChallengeKey(identity_hash=identity_hash))
        await self.redis.setex(key, ttl, code_hash)

    async def consume_email_auth_challenge(
        self, identity_hash: str, code_hash: str
    ) -> bool:
        key = serialize_storage_key(EmailAuthChallengeKey(identity_hash=identity_hash))
        value = await cast(
            Awaitable[Any], self.redis.eval(CONSUME_VALUE_SCRIPT, 1, key, code_hash)
        )
        return bool(value)

    async def increment_email_auth_attempts(self, identity_hash: str, ttl: int) -> int:
        key = serialize_storage_key(EmailAuthAttemptsKey(identity_hash=identity_hash))
        value = await cast(
            Awaitable[Any], self.redis.eval(INCREMENT_WITH_TTL_SCRIPT, 1, key, ttl)
        )
        return int(value)

    async def clear_email_auth_attempts(self, identity_hash: str) -> None:
        key = serialize_storage_key(EmailAuthAttemptsKey(identity_hash=identity_hash))
        await self.redis.delete(key)
