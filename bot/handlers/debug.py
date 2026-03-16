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

    user.onboarding_completed = False
    user.onboarding_step = None
    user.segment = None
    user.city = None
    user.timezone = "Europe/Vilnius"
    user.plan = "premium"
    user.daily_requests_used = 0

    logger.info("debug.reset", user_id=str(user.id))
    await update.message.reply_text("✅ Сброшено. План → premium. Лимиты обнулены. /start")
