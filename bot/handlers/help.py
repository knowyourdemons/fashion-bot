"""Help handler."""
from telegram import Update
from telegram.ext import ContextTypes
from bot.handlers.menu import get_main_menu
from core.permissions import get_effective_plan, get_limit, get_effective_limits


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = context.user_data.get("db_user")
    plan = get_effective_plan(user) if user else "free"
    _eff = get_effective_limits(user) if user else {}
    chat_limit = _eff.get("chat_per_day", get_limit("chat_per_day", plan))

    text = (
        "Привет! Я Касси — твой личный стилист 👗\n\n"
        "📸 Пришли фото вещей — добавлю в гардероб\n"
        "✨ Что надеть — соберу образ по погоде\n"
        "💬 Напиши вопрос — дам совет по стилю\n"
        "👗 Гардероб — список вещей и образы\n\n"
        "Каждое утро в 07:00 — готовый образ на день!\n\n"
        "Советы:\n"
        "• Фотографируй вещи по одной на светлом фоне\n"
        "• Чем больше вещей — тем интереснее образы\n"
        "• Нажми 👍 Надели — я запомню и буду учитывать\n\n"
        f"(до {chat_limit} вопросов в день)"
    )
    await update.message.reply_text(text, reply_markup=get_main_menu())
