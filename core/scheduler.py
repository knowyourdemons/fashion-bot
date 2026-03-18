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

    def _setup_jobs(self) -> None:
        from worker.tasks import morning_brief, gap_analysis
        from worker.tasks import subscription_expiry, reminders, analytics_report
        from worker.tasks import evening_push
        from worker.tasks import daily_reset, cleanup_r2

        # daily_reset — каждый час, фильтрует юзеров у кого сейчас 00:xx по local timezone
        self._scheduler.add_job(
            daily_reset.reset_daily_limits,
            CronTrigger(hour="*", minute=0),
            id="daily_reset",
            replace_existing=True,
        )

        # morning_brief — 07:00 по timezone юзера (запускается каждый час, фильтрует внутри)
        self._scheduler.add_job(
            morning_brief.schedule_all,
            CronTrigger(hour="*", minute=0),
            id="morning_brief",
            replace_existing=True,
        )

        # gap_analysis — 1-е число 09:00 UTC
        self._scheduler.add_job(
            gap_analysis.run,
            CronTrigger(day=1, hour=9, minute=0),
            id="gap_analysis",
            replace_existing=True,
        )

        # subscription_expiry — ежедневно 09:00 UTC
        self._scheduler.add_job(
            subscription_expiry.run,
            CronTrigger(hour=9, minute=0),
            id="subscription_expiry",
            replace_existing=True,
        )

        # evening_push — ежедневно 20:00 UTC
        self._scheduler.add_job(
            evening_push.run,
            CronTrigger(hour=20, minute=0),
            id="evening_push",
            replace_existing=True,
        )

        # reminders — ежедневно 10:00 UTC
        self._scheduler.add_job(
            reminders.run,
            CronTrigger(hour=10, minute=0),
            id="reminders",
            replace_existing=True,
        )

        # analytics_report — ежедневно 08:00 UTC
        self._scheduler.add_job(
            analytics_report.run,
            CronTrigger(hour=8, minute=0),
            id="analytics_report",
            replace_existing=True,
        )

        # cleanup_r2 — ежедневно 03:00 UTC
        self._scheduler.add_job(
            cleanup_r2.run,
            CronTrigger(hour=3, minute=0),
            id="cleanup_r2",
            replace_existing=True,
        )
