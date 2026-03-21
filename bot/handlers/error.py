"""Global PTB error handler — reports unhandled exceptions to Sentry."""
import structlog
import sentry_sdk
from telegram import Update
from telegram.ext import ContextTypes

logger = structlog.get_logger()


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Catch all unhandled exceptions from Telegram handlers."""
    error = context.error
    if error is None:
        return

    # Extract useful context for logging
    extra: dict = {}
    if isinstance(update, Update):
        if update.effective_user:
            extra["telegram_id"] = update.effective_user.id
        if update.effective_chat:
            extra["chat_id"] = update.effective_chat.id

    logger.error("bot.unhandled_error", error=str(error), exc_info=error, **extra)

    with sentry_sdk.push_scope() as scope:
        if extra.get("telegram_id"):
            scope.set_user({"id": str(extra["telegram_id"])})
        if extra.get("chat_id"):
            scope.set_tag("chat_id", str(extra["chat_id"]))
        sentry_sdk.capture_exception(error)
