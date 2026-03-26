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
            from worker.tasks import morning_brief, gap_analysis
            from worker.tasks import subscription_expiry, reminders, analytics_report
            from worker.tasks import evening_push, weekly_plan
            from worker.tasks import daily_reset, cleanup_r2
        except Exception as e:
            logger.error("scheduler.core_imports_failed", error=str(e))
            return

        self._add_job_safe("daily_reset", daily_reset.reset_daily_limits,
            CronTrigger(hour="*", minute=0))

        self._add_job_safe("morning_brief", morning_brief.schedule_all,
            CronTrigger(hour="*", minute=0),
            misfire_grace_time=300, max_instances=2)

        self._add_job_safe("evening_brief", morning_brief.schedule_evening,
            CronTrigger(hour="*", minute=30))

        self._add_job_safe("gap_analysis", gap_analysis.run,
            CronTrigger(day=1, hour=9, minute=0))

        self._add_job_safe("subscription_expiry", subscription_expiry.run,
            CronTrigger(hour=9, minute=0))

        self._add_job_safe("evening_push", evening_push.run,
            CronTrigger(hour="*", minute=45))

        self._add_job_safe("weekly_plan", weekly_plan.schedule_weekly,
            CronTrigger(hour="*", minute=15))

        self._add_job_safe("reminders", reminders.run,
            CronTrigger(hour=10, minute=0))

        self._add_job_safe("analytics_report", analytics_report.run,
            CronTrigger(hour=8, minute=0))

        self._add_job_safe("cleanup_r2", cleanup_r2.run,
            CronTrigger(hour=3, minute=0))

        # Warm thumbnail cache — ensures collage rendering is fast
        try:
            from worker.tasks import thumb_cache
            self._add_job_safe("warm_thumb_cache", thumb_cache.run,
                CronTrigger(hour=4, minute=0))
        except Exception as e:
            logger.error("scheduler.import_failed", task="warm_thumb_cache", error=str(e))

        # Optional tasks — each import wrapped individually
        try:
            from worker.tasks import growth_alert
            self._add_job_safe("growth_alert", growth_alert.run,
                CronTrigger(day=1, hour=8, minute=30))
        except Exception as e:
            logger.error("scheduler.import_failed", task="growth_alert", error=str(e))

        try:
            from worker.tasks import capsule_season
            self._add_job_safe("capsule_season", capsule_season.run,
                CronTrigger(day=1, hour=9, minute=30))
        except Exception as e:
            logger.error("scheduler.import_failed", task="capsule_season", error=str(e))

        try:
            from worker.tasks import wardrobe_analysis
            self._add_job_safe("wardrobe_analysis", wardrobe_analysis.run,
                CronTrigger(day_of_week="mon", hour=6, minute=0))
        except Exception as e:
            logger.error("scheduler.import_failed", task="wardrobe_analysis", error=str(e))

        try:
            from worker.tasks import declutter
            self._add_job_safe("declutter", declutter.run,
                CronTrigger(day=15, hour=10, minute=0))
        except Exception as e:
            logger.error("scheduler.import_failed", task="declutter", error=str(e))

        try:
            from worker.tasks import taxonomy_review
            self._add_job_safe("taxonomy_review", taxonomy_review.run,
                CronTrigger(hour=4, minute=0))
        except Exception as e:
            logger.error("scheduler.import_failed", task="taxonomy_review", error=str(e))

        try:
            from worker.tasks import unknown_items_report
            self._add_job_safe("unknown_items_report", unknown_items_report.run,
                CronTrigger(day=1, hour=7, minute=0))
        except Exception as e:
            logger.error("scheduler.import_failed", task="unknown_items_report", error=str(e))

        try:
            from worker.tasks import pre_generate_brief
            self._add_job_safe("pre_generate_brief", pre_generate_brief.run,
                CronTrigger(hour="*", minute=45))
        except Exception as e:
            logger.error("scheduler.import_failed", task="pre_generate_brief", error=str(e))
