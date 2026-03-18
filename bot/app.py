"""Telegram Application — регистрация handlers."""
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters

from config import settings


def create_application() -> Application:
    app = Application.builder().token(settings.telegram_bot_token).build()

    from bot.handlers import wardrobe, feedback, billing, help, text, debug, brief
    from bot.handlers.onboarding import build_conversation_handler
    from bot.handlers.menu import get_main_menu
    from bot.handlers.profile import handle_profile
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

    # Photo handlers (сжатое фото и документ-изображение оригинального качества)
    app.add_handler(MessageHandler(filters.PHOTO, wardrobe.handle_photo))
    app.add_handler(MessageHandler(filters.Document.IMAGE, wardrobe.handle_photo))

    # Кнопки главного меню group=0 (Гардероб, Оценить образ, Профиль)
    app.add_handler(MessageHandler(filters.Regex("^👗 Гардероб$"), wardrobe.handle_wardrobe_menu))
    app.add_handler(MessageHandler(filters.Regex("^⭐ Оценить образ$"), wardrobe.handle_rate_menu))
    app.add_handler(MessageHandler(filters.Regex("^⚙️ Профиль$"), handle_profile))

    # ❓ Помощь — group=1 (явный приоритет перед text стилистом)
    app.add_handler(
        MessageHandler(filters.TEXT & filters.Regex("^❓ Помощь$"), help.handle_help),
        group=1,
    )

    # Callback queries (кнопки)
    app.add_handler(CallbackQueryHandler(brief.handle_brief_feedback, pattern="^brief_feedback:"))
    app.add_handler(CallbackQueryHandler(feedback.handle_feedback, pattern="^feedback:"))
    app.add_handler(CallbackQueryHandler(billing.handle_plan_callback, pattern="^plan:"))
    app.add_handler(CallbackQueryHandler(wardrobe.handle_wardrobe_page, pattern="^wardrobe:page:"))
    app.add_handler(CallbackQueryHandler(wardrobe.handle_photo_action, pattern="^photo_action:"))
    app.add_handler(CallbackQueryHandler(wardrobe.handle_rate_mode, pattern="^rate_mode:"))
    app.add_handler(CallbackQueryHandler(wardrobe.handle_set_owner, pattern="^set_owner:"))
    app.add_handler(CallbackQueryHandler(wardrobe.handle_outfit_request, pattern="^outfit_request$"))
    app.add_handler(CallbackQueryHandler(wardrobe.handle_list_callback, pattern="^show_wardrobe_list$"))

    # Текстовые сообщения → стилист — group=2 (после меню-хендлеров)
    _menu_texts = filters.Regex("^(👗 Гардероб|⭐ Оценить образ|⚙️ Профиль|❓ Помощь)$")
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND & ~_menu_texts, text.handle_text),
        group=2,
    )

    return app
