"""Wardrobe handlers."""
import structlog
import sentry_sdk
from telegram import Update
from telegram.ext import ContextTypes
from exceptions import FashionBotError
from services.i18n.ru import t

logger = structlog.get_logger()


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = context.user_data.get("db_user")
    if not user:
        return
    try:
        photo = update.message.photo[-1]
        # TODO: download, preprocess, add to wardrobe
        await update.message.reply_text(t("wardrobe.add.success"))
    except FashionBotError as e:
        await update.message.reply_text(str(e))
    except Exception as e:
        await update.message.reply_text(t("error.generic"))
        sentry_sdk.capture_exception(e)


async def handle_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = context.user_data.get("db_user")
    if not user:
        return
    await update.message.reply_text(t("wardrobe.empty"))
