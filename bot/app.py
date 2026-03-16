"""Telegram Application — регистрация handlers."""
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters

from config import settings


def create_application() -> Application:
    app = Application.builder().token(settings.telegram_bot_token).build()

    from bot.handlers import wardrobe, feedback, billing, help, text, debug
    from bot.handlers.onboarding import build_conversation_handler
    from bot.middleware.auth import AuthMiddleware
    from bot.middleware.typing import TypingMiddleware

    # Middleware
    app.add_handler(MessageHandler(filters.ALL, AuthMiddleware.handle), group=-2)
    app.add_handler(MessageHandler(filters.ALL, TypingMiddleware.handle), group=-1)

    # Онбординг — ConversationHandler (должен быть первым в group=0)
    app.add_handler(build_conversation_handler())

    # Command handlers
    app.add_handler(CommandHandler("debug_reset", debug.handle_debug_reset))
    app.add_handler(CommandHandler("help", help.handle_help))
    app.add_handler(CommandHandler("wardrobe", wardrobe.handle_list))
    app.add_handler(CommandHandler("subscribe", billing.handle_subscribe))
    app.add_handler(CommandHandler("plan", billing.handle_plan))
    app.add_handler(CommandHandler("cancel", billing.handle_cancel))

    # Photo handler
    app.add_handler(MessageHandler(filters.PHOTO, wardrobe.handle_photo))

    # Callback queries (кнопки)
    app.add_handler(CallbackQueryHandler(feedback.handle_feedback, pattern="^feedback:"))
    app.add_handler(CallbackQueryHandler(billing.handle_plan_callback, pattern="^plan:"))

    # Текстовые сообщения → стилист
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text.handle_text))

    return app
