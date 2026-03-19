"""
Singleton Redis client.

Usage:
    from core.redis import get_redis, init_redis, close_redis

    # At startup (main.py / worker consumer):
    await init_redis()

    # Anywhere:
    redis = get_redis()
    await redis.get("key")

    # At shutdown:
    await close_redis()
"""
import redis.asyncio as aioredis

from config import settings

_client: aioredis.Redis | None = None


async def init_redis() -> aioredis.Redis:
    """Create the shared Redis connection pool. Call once at startup."""
    global _client
    if _client is None:
        _client = aioredis.from_url(
            settings.redis_url,
            decode_responses=False,
            max_connections=32,
        )
    return _client


def get_redis() -> aioredis.Redis:
    """Return the shared Redis client. Raises if init_redis() was not called."""
    if _client is None:
        raise RuntimeError("Redis not initialized. Call init_redis() first.")
    return _client


async def close_redis() -> None:
    """Gracefully close the Redis connection pool."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
