"""
Redis queue consumer — точка входа воркера.
Запускает fast и slow worker в параллельных корутинах.
"""
import asyncio
import signal
import structlog
import redis.asyncio as aioredis

from config import settings
from core.queue import RedisQueue, QueuePriority
from worker.fast_worker import FastWorker
from worker.slow_worker import SlowWorker

logger = structlog.get_logger()

_shutdown = asyncio.Event()


def _handle_signal(sig: signal.Signals) -> None:
    logger.info("worker.shutdown_signal", signal=sig.name)
    _shutdown.set()


async def main() -> None:
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=False)
    queue = RedisQueue(redis_client)

    fast_worker = FastWorker(queue, redis_client)
    slow_worker = SlowWorker(queue, redis_client)

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: _handle_signal(s))

    logger.info("worker.started")

    try:
        await asyncio.gather(
            fast_worker.run(_shutdown),
            slow_worker.run(_shutdown),
        )
    finally:
        await redis_client.aclose()
        logger.info("worker.stopped")


if __name__ == "__main__":
    asyncio.run(main())
