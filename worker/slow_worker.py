"""
Slow worker: NORMAL + LOW priority queues.
Задачи: analytics, growth_alert, reminders и другие несрочные.
"""
import asyncio
from typing import Any

import redis.asyncio as aioredis
import structlog

from core.queue import QueuePriority, RedisQueue, TaskMessage

logger = structlog.get_logger()

TASK_HANDLERS: dict[str, Any] = {}


def register(task_type: str) -> Any:
    def decorator(fn: Any) -> Any:
        TASK_HANDLERS[task_type] = fn
        return fn
    return decorator


_BACKOFF = [1, 4, 16]


class SlowWorker:
    QUEUES = [QueuePriority.NORMAL, QueuePriority.LOW]
    MAX_RETRIES = 3
    HEARTBEAT_TTL = 120

    def __init__(self, queue: RedisQueue, redis_client: aioredis.Redis) -> None:
        self._queue = queue
        self._redis = redis_client
        self._worker_id = "slow_worker"

        # Ленивый импорт
        from worker.tasks import (  # noqa: F401
            growth_alert, gap_analysis, declutter,
            capsule_season, birthday_alert, subscription_expiry,
            reminders, analytics_report, unknown_items_report,
            taxonomy_review,
        )

    async def run(self, shutdown: asyncio.Event) -> None:
        logger.info("slow_worker.started")
        while not shutdown.is_set():
            try:
                msg = await self._queue.pop(self.QUEUES, timeout=5)
                if msg:
                    await self._process(msg)
                await self._heartbeat()
            except Exception as e:
                logger.error("slow_worker.loop_error", error=str(e))
        logger.info("slow_worker.stopped")

    async def _process(self, msg: TaskMessage) -> None:
        handler = TASK_HANDLERS.get(msg.task_type)
        if not handler:
            logger.warning("slow_worker.unknown_task", task_type=msg.task_type)
            await self._queue.ack(msg)
            return

        try:
            result = await handler(msg.payload)
            await self._queue.ack(msg)
            await self._queue.store_result(msg.task_id, result or {})
            logger.info("slow_worker.task_done", task_id=msg.task_id, task_type=msg.task_type)
        except Exception as e:
            logger.error(
                "slow_worker.task_error",
                task_id=msg.task_id,
                task_type=msg.task_type,
                retry=msg.retry_count,
                error=str(e),
            )
            if msg.retry_count >= self.MAX_RETRIES:
                await self._queue.move_to_dead(msg, str(e))
            else:
                delay = _BACKOFF[min(msg.retry_count, len(_BACKOFF) - 1)]
                await asyncio.sleep(delay)
                await self._queue.requeue(msg, QueuePriority.NORMAL)

    async def _heartbeat(self) -> None:
        key = f"worker:heartbeat:{self._worker_id}"
        await self._redis.set(key, "1", ex=self.HEARTBEAT_TTL)
