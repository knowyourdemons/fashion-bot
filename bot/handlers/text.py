"""Text handler — stylist consultant."""
import time
import sentry_sdk
import structlog
import sqlalchemy as sa
from telegram import Update
from telegram.ext import ContextTypes

from config import settings
from core.anthropic_client import get_anthropic_pool
from db.base import AsyncWriteSession
from db.models.user import User
from exceptions import FashionBotError, RateLimitError
from services.i18n.ru import t

logger = structlog.get_logger()

STYLIST_SYSTEM_PROMPT = """Ты AI-стилист Fashion Bot. Специализируешься на детской одежде и семейном стиле.
Отвечаешь кратко — максимум 5 строк. Язык: русский. Используй эмодзи умеренно.
Ты НЕ универсальный ассистент — если вопрос не про одежду, стиль или гардероб,
вежливо отвечай: "Я стилист, могу помочь только с вопросами про одежду и стиль 👗"
"""

_PLAN_LIMITS: dict[str, int] = {
    "free":    settings.daily_limits_free,
    "basic":   settings.daily_limits_basic,
    "family":  settings.daily_limits_family,
    "premium": -1,  # unlimited
}


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = context.user_data.get("db_user")
    if not user:
        return

    # Проверка дневного лимита
    limit = _PLAN_LIMITS.get(user.plan, settings.daily_limits_free)
    if limit != -1 and user.daily_requests_used >= limit:
        await update.message.reply_text(t("error.rate_limit"))
        return

    try:
        start = time.monotonic()
        pool = get_anthropic_pool()
        response = await pool.create_message(
            system=STYLIST_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": update.message.text}],
            max_tokens=512,
        )
        reply = response.content[0].text if response.content else t("error.generic")
        duration_ms = int((time.monotonic() - start) * 1000)

        await update.message.reply_text(reply)

        # Инкремент счётчика
        new_count = user.daily_requests_used + 1
        async with AsyncWriteSession() as session:
            await session.execute(
                sa.update(User)
                .where(User.id == user.id)
                .values(daily_requests_used=new_count)
            )
            await session.commit()
        user.daily_requests_used = new_count

        logger.info(
            "stylist.response",
            user_id=str(user.id),
            action="stylist.text",
            duration_ms=duration_ms,
            requests_used=new_count,
        )
    except (RateLimitError, FashionBotError) as e:
        await update.message.reply_text(str(e))
    except Exception as e:
        await update.message.reply_text(t("error.generic"))
        sentry_sdk.capture_exception(e)
