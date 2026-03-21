"""Debug команды — только для ADMIN_TELEGRAM_IDS."""
import structlog
from datetime import datetime, timezone

import sqlalchemy as sa
from telegram import Update
from telegram.ext import ContextTypes

from config import settings
from db.base import AsyncWriteSession
from db.models.user import User
from db.models.child import Child

logger = structlog.get_logger()


async def handle_debug_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = context.user_data.get("db_user")
    if not user:
        return

    if user.telegram_id not in settings.admin_ids_list:
        await update.message.reply_text("⛔ Нет доступа.")
        return

    async with AsyncWriteSession() as session:
        await session.execute(
            sa.update(Child)
            .where(Child.user_id == user.id, Child.deleted_at == None)
            .values(deleted_at=datetime.now(timezone.utc))
        )
        await session.execute(
            sa.update(User)
            .where(User.id == user.id)
            .values(
                onboarding_completed=False,
                onboarding_step=None,
                segment=None,
                city=None,
                timezone="Europe/Vilnius",
                plan="premium",
                daily_requests_used=0,
                daily_requests_reset_at=None,
            )
        )
        await session.commit()

    # Очистить кэш owner из bot_data
    cache_key = f"owner:{user.id}"
    context.application.bot_data.pop(cache_key, None)

    # Reload user from DB to ensure context has fresh data
    from db.base import AsyncReadSession
    from db.crud.users import get_by_id
    async with AsyncReadSession() as rsession:
        refreshed = await get_by_id(rsession, user.id)
        if refreshed:
            user = refreshed
    context.user_data["db_user"] = user

    logger.info("debug.reset", user_id=str(user.id))
    await update.message.reply_text("✅ Сброшено. План → premium. Лимиты обнулены. /start")


async def handle_debug_free(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Сбросить юзера в free для тестирования free-flow. Только для admin."""
    user = context.user_data.get("db_user")
    if not user:
        return

    if user.telegram_id not in settings.admin_ids_list:
        await update.message.reply_text("⛔ Нет доступа.")
        return

    async with AsyncWriteSession() as session:
        await session.execute(
            sa.update(User)
            .where(User.id == user.id)
            .values(
                plan="free",
                plan_expires_at=None,
                trial_ends_at=None,
                trial_started_at=None,
                daily_requests_used=0,
            )
        )
        await session.commit()

    # Reload user from DB to ensure context has fresh data
    from db.base import AsyncReadSession
    from db.crud.users import get_by_id
    async with AsyncReadSession() as rsession:
        refreshed = await get_by_id(rsession, user.id)
        if refreshed:
            user = refreshed
    context.user_data["db_user"] = user

    logger.info("debug.free", user_id=str(user.id))
    await update.message.reply_text("✅ План → free. Подписки и trial сброшены.")


async def handle_debug_brief(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Триггер Morning Brief по запросу. Только для admin."""
    user = context.user_data.get("db_user")
    if not user:
        return

    if user.telegram_id not in settings.admin_ids_list:
        await update.message.reply_text("⛔ Нет доступа.")
        return

    redis = context.bot_data.get("redis")
    if not redis:
        await update.message.reply_text("❌ Redis недоступен.")
        return

    try:
        # Clear brief lock for debug
        from datetime import date as _d
        _lock = f"lock:brief:{user.id}:{_d.today().isoformat()}"
        await redis.delete(_lock)

        from core.queue import RedisQueue, QueuePriority
        queue = RedisQueue(redis)
        await queue.push(
            "generate_brief",
            {"user_id": str(user.id)},
            priority=QueuePriority.HIGH,
        )
        logger.info("debug.brief_triggered", user_id=str(user.id))
        await update.message.reply_text("🌅 Бриф в очереди — придёт через несколько секунд.")
    except Exception as e:
        logger.error("debug.brief_failed", error=str(e))
        await update.message.reply_text(f"❌ Ошибка: {e}")
