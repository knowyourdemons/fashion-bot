"""Settings handler — language selection."""
import structlog
import sqlalchemy as sa
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from db.base import AsyncWriteSession
from db.models.user import User as UserModel
from services.i18n import t, get_user_lang

logger = structlog.get_logger()


def lang_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🇷🇺 Русский", callback_data="lang:ru"),
        InlineKeyboardButton("🇬🇧 English", callback_data="lang:en"),
    ]])


async def handle_lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback: lang:ru or lang:en → save language."""
    query = update.callback_query
    await query.answer()

    user = context.user_data.get("db_user")
    if not user:
        return

    lang = query.data.split(":")[1]
    if lang not in ("ru", "en"):
        lang = "ru"

    async with AsyncWriteSession() as session:
        await session.execute(
            sa.update(UserModel).where(UserModel.id == user.id)
            .values(language=lang)
        )
        await session.commit()
    user.language = lang

    await query.edit_message_text(t("lang.changed", lang))
    logger.info("settings.lang_changed", user_id=str(user.id), lang=lang)
