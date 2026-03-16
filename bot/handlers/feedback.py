"""Feedback handler."""
import sentry_sdk
import structlog
from telegram import Update
from telegram.ext import ContextTypes
from exceptions import FashionBotError
from services.i18n.ru import t

logger = structlog.get_logger()


async def handle_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = context.user_data.get("db_user")
    if not user:
        return
    try:
        _, vote, brief_id = query.data.split(":")
        msg = t("feedback.thanks_up") if vote == "up" else t("feedback.thanks_down")
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(msg)
    except Exception as e:
        await query.message.reply_text(t("error.generic"))
        sentry_sdk.capture_exception(e)
