"""
APScheduler + Redis для cron задач.
Предотвращает дублирование через Redis lock.
"""
import asyncio
from datetime import datetime, timedelta
from typing import Callable, Awaitable

import redis.asyncio as aioredis
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import structlog

logger = structlog.get_logger()


class Scheduler:
    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client
        self._scheduler = AsyncIOScheduler(timezone="UTC")

    def start(self) -> None:
        self._setup_jobs()
        self._scheduler.start()
        logger.info("scheduler.started")

    def stop(self) -> None:
        self._scheduler.shutdown()

    async def acquire_lock(self, task: str, user_id: str = "global", ttl: int = 300) -> bool:
        """Redis lock для предотвращения дублей. Возвращает True если лок получен."""
        key = f"lock:cron:{task}:{user_id}"
        result = await self._redis.set(key, "1", ex=ttl, nx=True)
        return result is True

    async def release_lock(self, task: str, user_id: str = "global") -> None:
        key = f"lock:cron:{task}:{user_id}"
        await self._redis.delete(key)

    def _add_job_safe(self, job_id: str, func, trigger, **kwargs) -> None:
        """Add a scheduler job, logging errors instead of crashing startup."""
        try:
            self._scheduler.add_job(func, trigger, id=job_id, replace_existing=True, **kwargs)
        except Exception as e:
            logger.error("scheduler.job_setup_failed", job_id=job_id, error=str(e))

    def _setup_jobs(self) -> None:
        try:
            from worker.tasks import daily_reset, cleanup_r2
            from worker.tasks import cookbook_push
        except Exception as e:
            logger.error("scheduler.core_imports_failed", error=str(e))
            return

        self._add_job_safe("daily_reset", daily_reset.reset_daily_limits,
            CronTrigger(hour="*", minute=0))

        # Кукбук: ежедневный пуш «что на ужин» в 17:00 МСК (=14:00 UTC).
        # Заменил фешн morning/evening brief (фешн-ботом не пользуемся).
        self._add_job_safe("cookbook_dinner", cookbook_push.run,
            CronTrigger(hour=14, minute=0),
            misfire_grace_time=1800)

        self._add_job_safe("cleanup_r2", cleanup_r2.run,
            CronTrigger(hour=3, minute=0))
        # Все фешн-cron-рассылки удалены (фешн-ботом не пользуемся). Код тасков остаётся
        # в worker/tasks/ (используется тестами), просто не планируется. Оставлены только
        # daily_reset + cleanup_r2 (инфра) + cookbook_dinner (кукбук).
