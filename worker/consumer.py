"""
Redis queue consumer — точка входа воркера.
Запускает fast и slow worker в параллельных корутинах.
"""
import asyncio
import signal
import structlog
import sentry_sdk

from config import settings
from core.queue import RedisQueue
from core.anthropic_client import init_anthropic_pool
from core.redis import init_redis, close_redis
from worker.fast_worker import FastWorker
from worker.slow_worker import SlowWorker

logger = structlog.get_logger()

_shutdown = asyncio.Event()


def _handle_signal(sig: signal.Signals) -> None:
    logger.info("worker.shutdown_signal", signal=sig.name)
    _shutdown.set()


async def main() -> None:
    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.environment,
            send_default_pii=True,
        )

    redis_client = await init_redis()
    queue = RedisQueue(redis_client)

    init_anthropic_pool(redis_client)

    fast_worker = FastWorker(queue, redis_client)
    slow_worker = SlowWorker(queue, redis_client)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: _handle_signal(s))

    logger.info("worker.started")

    try:
        await asyncio.gather(
            fast_worker.run(_shutdown),
            slow_worker.run(_shutdown),
        )
    finally:
        await close_redis()
        logger.info("worker.stopped")


if __name__ == "__main__":
    asyncio.run(main())
