"""
/start handler — онбординг флоу.
"""
import structlog
import sentry_sdk
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes

from exceptions import FashionBotError
from services.i18n.ru import t

logger = structlog.get_logger()


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = context.user_data.get("db_user")
    if not user:
        return
    try:
        if user.onboarding_completed:
            await update.message.reply_text(f"Привет, {user.name}! Пришли фото вещи или /wardrobe")
            return
        await update.message.reply_text(t("onboarding.start"))
    except FashionBotError as e:
        await update.message.reply_text(str(e))
        logger.warning("start.error", error=str(e), user_id=str(user.id))
    except Exception as e:
        await update.message.reply_text(t("error.generic"))
        sentry_sdk.capture_exception(e)
