"""
Token bucket rate limiter в Redis.
Поддерживает: per-user daily лимиты + per-API-key RPM лимиты.
"""
import time

import redis.asyncio as aioredis
import structlog

from exceptions import RateLimitError

logger = structlog.get_logger()

RPM_LIMIT = 50  # запросов в минуту на API ключ


class RateLimiter:
    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client

    async def check_user_daily(self, user_id: str, limit: int) -> None:
        """Проверяет и инкрементирует дневной лимит пользователя.
        Raises RateLimitError если лимит исчерпан.
        -1 = unlimited.
        """
        if limit == -1:
            return

        key = f"rate:user:{user_id}:daily"
        current = await self._redis.get(key)

        if current is not None and int(current) >= limit:
            raise RateLimitError(
                f"Использовано {current}/{limit} запросов на сегодня."
            )

        pipe = self._redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, 86400)
        await pipe.execute()

    async def check_api_key_rpm(self, api_key_id: str) -> None:
        """Token bucket для API ключа: 50 RPM.
        Raises RateLimitError если превышен лимит.
        """
        key = f"rate:api:{api_key_id}:minute"
        current = await self._redis.get(key)

        if current is not None and int(current) >= RPM_LIMIT:
            raise RateLimitError(f"Превышен лимит API ключа {api_key_id}: {RPM_LIMIT} RPM.")

        pipe = self._redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, 60)
        await pipe.execute()

    async def get_user_usage(self, user_id: str) -> int:
        key = f"rate:user:{user_id}:daily"
        value = await self._redis.get(key)
        return int(value) if value else 0

    async def reset_user_daily(self, user_id: str) -> None:
        key = f"rate:user:{user_id}:daily"
        await self._redis.delete(key)
