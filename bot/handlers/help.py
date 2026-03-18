"""Help handler."""
from telegram import Update
from telegram.ext import ContextTypes
from bot.handlers.menu import get_main_menu


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = context.user_data.get("db_user")
    plan = getattr(user, "plan", "free") if user else "free"
    chat_limit = 20 if plan == "premium" else 5

    text = (
        "Привет! Я Касси 👗\n\n"
        "📸 Пришли фото вещей — добавлю в гардероб\n"
        "🌅 Каждое утро в 07:00 — образ дня по погоде\n"
        "👗 Гардероб → список вещей и образ по запросу\n"
        "⭐ Оценить образ → пришли фото — дам совет\n"
        "⚙️ Профиль → твои данные\n\n"
        f"💬 Напиши вопрос про стиль — отвечу!\n"
        f"(до {chat_limit} вопросов в день)"
    )
    await update.message.reply_text(text, reply_markup=get_main_menu())
