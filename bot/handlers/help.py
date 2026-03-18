"""Help handler."""
from telegram import Update
from telegram.ext import ContextTypes
from bot.handlers.menu import get_main_menu


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👋 Я Fashion Castle — твой AI-стилист!\n\n"
        "📸 Пришли фото вещей → добавлю в гардероб\n"
        "🌅 Каждое утро в 07:00 — образ дня по погоде\n"
        "⭐ Нажми Оценить образ → пришли фото → совет\n"
        "👗 Нажми Гардероб → список всех вещей\n"
        "⚙️ Нажми Профиль → твои данные\n\n"
        "💬 Напиши любой вопрос про стиль — отвечу!"
    )
    await update.message.reply_text(text, reply_markup=get_main_menu())
