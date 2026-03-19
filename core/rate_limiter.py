"""
Atomic rate limiter via Redis Lua scripts.
Supports: per-user daily limits + per-API-key RPM limits.
All check+increment operations are atomic (no race conditions).
"""
import redis.asyncio as aioredis
import structlog

from exceptions import RateLimitError

logger = structlog.get_logger()

RPM_LIMIT = 50  # запросов в минуту на API ключ

# Lua: atomic check-and-increment with TTL.
# Returns current count AFTER increment, or -1 if limit already reached.
_LUA_CHECK_INCR = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local current = tonumber(redis.call('GET', key) or '0')
if current >= limit then
    return -1
end
local new = redis.call('INCR', key)
if new == 1 then
    redis.call('EXPIRE', key, ttl)
end
return new
"""


class RateLimiter:
    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client
        self._script = self._redis.register_script(_LUA_CHECK_INCR)

    async def check_user_daily(self, user_id: str, limit: int) -> None:
        """Atomic check+increment daily limit. Raises RateLimitError if exceeded."""
        if limit == -1:
            return

        key = f"rate:user:{user_id}:daily"
        result = await self._script(keys=[key], args=[limit, 86400])

        if result == -1:
            raise RateLimitError(
                f"Использовано {limit}/{limit} запросов на сегодня."
            )

    async def check_api_key_rpm(self, api_key_id: str) -> None:
        """Atomic check+increment RPM limit. Raises RateLimitError if exceeded."""
        key = f"rate:api:{api_key_id}:minute"
        result = await self._script(keys=[key], args=[RPM_LIMIT, 60])

        if result == -1:
            raise RateLimitError(f"Превышен лимит API ключа {api_key_id}: {RPM_LIMIT} RPM.")

    async def get_user_usage(self, user_id: str) -> int:
        key = f"rate:user:{user_id}:daily"
        value = await self._redis.get(key)
        return int(value) if value else 0

    async def reset_user_daily(self, user_id: str) -> None:
        key = f"rate:user:{user_id}:daily"
        await self._redis.delete(key)
