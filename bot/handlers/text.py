"""Text handler — stylist consultant."""
import time
import sentry_sdk
import structlog
from telegram import Update
from telegram.ext import ContextTypes
from core.anthropic_client import get_anthropic_pool
from exceptions import FashionBotError, RateLimitError
from services.i18n.ru import t

logger = structlog.get_logger()


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = context.user_data.get("db_user")
    if not user:
        return
    try:
        start = time.monotonic()
        pool = get_anthropic_pool()
        response = await pool.create_message(
            messages=[{"role": "user", "content": update.message.text}],
            max_tokens=512,
        )
        text = response.content[0].text if response.content else t("error.generic")
        duration_ms = int((time.monotonic() - start) * 1000)
        await update.message.reply_text(text)
        logger.info("stylist.response", user_id=str(user.id), action="stylist.text", duration_ms=duration_ms)
    except (RateLimitError, FashionBotError) as e:
        await update.message.reply_text(str(e))
    except Exception as e:
        await update.message.reply_text(t("error.generic"))
        sentry_sdk.capture_exception(e)
