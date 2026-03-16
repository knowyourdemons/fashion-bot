"""
Fashion Bot — точка входа.
Запускает FastAPI + Telegram Bot (webhook mode) + Scheduler.
"""
import asyncio
import structlog
import redis.asyncio as aioredis
from fastapi import FastAPI

from config import settings
from api.app import create_app
from bot.app import create_application
from core.anthropic_client import init_anthropic_pool
from core.queue import RedisQueue
from core.scheduler import Scheduler

logger = structlog.get_logger()

# Настройка structlog
import structlog
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer() if settings.environment == "dev"
        else structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(20),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

# FastAPI приложение
app: FastAPI = create_app()


@app.on_event("startup")
async def startup() -> None:
    from db.seeds.scoring_matrices import seed_scoring_matrices
    await seed_scoring_matrices()

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=False)

    # Инициализируем пул Anthropic
    init_anthropic_pool(redis_client)

    # Запускаем Telegram Bot в webhook режиме
    tg_app = create_application()
    tg_app.bot_data["redis"] = redis_client
    await tg_app.initialize()

    if settings.telegram_webhook_url:
        await tg_app.bot.set_webhook(
            url=f"{settings.telegram_webhook_url}/api/v1/webhooks/telegram",
            secret_token=settings.telegram_webhook_secret,
        )

    # APScheduler
    scheduler = Scheduler(redis_client)
    scheduler.start()

    app.state.redis = redis_client
    app.state.tg_app = tg_app
    app.state.scheduler = scheduler
    logger.info("app.started", environment=settings.environment)


@app.on_event("shutdown")
async def shutdown() -> None:
    if hasattr(app.state, "scheduler"):
        app.state.scheduler.stop()
    if hasattr(app.state, "tg_app"):
        await app.state.tg_app.shutdown()
    if hasattr(app.state, "redis"):
        await app.state.redis.aclose()
    logger.info("app.stopped")
