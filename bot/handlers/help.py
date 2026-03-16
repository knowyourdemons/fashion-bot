from telegram import Update
from telegram.ext import ContextTypes
from services.i18n.ru import t


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(t("help.text"))
