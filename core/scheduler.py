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
        from worker.tasks import morning_brief, growth_alert, declutter
        from worker.tasks import gap_analysis, capsule_season, birthday_alert
        from worker.tasks import subscription_expiry, reminders, analytics_report
        from worker.tasks import unknown_items_report, taxonomy_review
        from worker.tasks import daily_reset, cleanup_r2

        # daily_reset — каждый день в полночь UTC
        self._scheduler.add_job(
            daily_reset.reset_daily_limits,
            CronTrigger(hour=0, minute=0),
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

        # growth_alert — вс 11:00 UTC
        self._scheduler.add_job(
            growth_alert.run,
            CronTrigger(day_of_week="sun", hour=11, minute=0),
            id="growth_alert",
            replace_existing=True,
        )

        # declutter — 1-е число 10:00 UTC (Batch API)
        self._scheduler.add_job(
            declutter.run,
            CronTrigger(day=1, hour=10, minute=0),
            id="declutter",
            replace_existing=True,
        )

        # gap_analysis — 15-е число 10:00 UTC (Batch API)
        self._scheduler.add_job(
            gap_analysis.run,
            CronTrigger(day=15, hour=10, minute=0),
            id="gap_analysis",
            replace_existing=True,
        )

        # capsule_season — 1 мар/июн/сен/дек
        self._scheduler.add_job(
            capsule_season.run,
            CronTrigger(month="3,6,9,12", day=1, hour=10, minute=0),
            id="capsule_season",
            replace_existing=True,
        )

        # birthday_alert — ежедневно 08:00 UTC
        self._scheduler.add_job(
            birthday_alert.run,
            CronTrigger(hour=8, minute=0),
            id="birthday_alert",
            replace_existing=True,
        )

        # subscription_expiry — ежедневно 09:00 UTC
        self._scheduler.add_job(
            subscription_expiry.run,
            CronTrigger(hour=9, minute=0),
            id="subscription_expiry",
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

        # unknown_items_report — 1-е число 09:00 UTC
        self._scheduler.add_job(
            unknown_items_report.run,
            CronTrigger(day=1, hour=9, minute=0),
            id="unknown_items_report",
            replace_existing=True,
        )

        # taxonomy_review — 1 мар/июн/сен/дек 09:00
        self._scheduler.add_job(
            taxonomy_review.run,
            CronTrigger(month="3,6,9,12", day=1, hour=9, minute=0),
            id="taxonomy_review",
            replace_existing=True,
        )

        # cleanup_r2 — ежедневно 03:00 UTC
        self._scheduler.add_job(
            cleanup_r2.run,
            CronTrigger(hour=3, minute=0),
            id="cleanup_r2",
            replace_existing=True,
        )
