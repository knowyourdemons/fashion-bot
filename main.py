"""
Fashion Bot — точка входа.
Запускает FastAPI + Telegram Bot (webhook mode) + Scheduler.
"""
import asyncio
import structlog
from fastapi import FastAPI

from config import settings
from api.app import create_app
from bot.app import create_application
from core.anthropic_client import init_anthropic_pool
from core.queue import RedisQueue
from core.redis import init_redis, close_redis, get_redis
from core.scheduler import Scheduler

# Настройка structlog
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer() if settings.environment == "dev"
        else structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(20),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger()

# FastAPI приложение
app: FastAPI = create_app()

# .webp не зарегистрирован в системном mimetypes → StaticFiles отдаёт text/plain.
# Из-за этого Cloudflare не считает ресурс картинкой (нет image-оптимизации).
import mimetypes
mimetypes.add_type("image/webp", ".webp")


@app.middleware("http")
async def _static_image_cache(request, call_next):
    """Длинный кэш для статичных фото рецептов (Cloudflare honors origin Cache-Control)."""
    response = await call_next(request)
    if request.url.path.startswith("/img/"):
        response.headers["Cache-Control"] = "public, max-age=2592000"  # 30 дней
    return response


from fastapi.staticfiles import StaticFiles
app.mount("/", StaticFiles(directory="landing", html=True), name="landing")


@app.on_event("startup")
async def startup() -> None:
    from db.seeds.scoring_matrices import seed_scoring_matrices
    await seed_scoring_matrices()

    # Миграция: добавить столбец role в wardrobe_items если не существует
    try:
        from sqlalchemy import text as _text
        from db.base import AsyncWriteSession as _AWS
        async with _AWS() as _sess:
            await _sess.execute(_text(
                "ALTER TABLE wardrobe_items ADD COLUMN IF NOT EXISTS role VARCHAR(16)"
            ))
            await _sess.commit()
    except Exception as _e:
        import structlog as _sl
        _sl.get_logger().warning("startup.migration.role_column_failed", error=str(_e))

    from db.seeds.translate_items import run_if_needed as translate_items
    await translate_items()

    redis_client = await init_redis()

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

    # Wait for tracked background tasks (max 10s)
    from bot.handlers.wardrobe import _background_tasks
    if _background_tasks:
        logger.info("shutdown.waiting_tasks", count=len(_background_tasks))
        _, pending = await asyncio.wait(_background_tasks, timeout=10)
        for t in pending:
            t.cancel()

    if hasattr(app.state, "tg_app"):
        await app.state.tg_app.shutdown()
    await close_redis()
    logger.info("app.stopped")
