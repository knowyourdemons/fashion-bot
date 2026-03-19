"""Telegram Application — регистрация handlers."""
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    PreCheckoutQueryHandler, filters,
)

from config import settings


def create_application() -> Application:
    app = Application.builder().token(settings.telegram_bot_token).build()

    from bot.handlers import wardrobe, feedback, billing, help, text, debug, brief
    from bot.handlers.shopping import handle_shopping
    from bot.handlers.test_billing import (
        handle_test_subscribe, handle_test_subscribe_action,
    )
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
    app.add_handler(CommandHandler("debug_free", debug.handle_debug_free))
    app.add_handler(CommandHandler("debug_brief", debug.handle_debug_brief))
    app.add_handler(CommandHandler("test_subscribe", handle_test_subscribe))
    app.add_handler(CommandHandler("help", help.handle_help))
    app.add_handler(CommandHandler("wardrobe", wardrobe.handle_list))
    app.add_handler(CommandHandler("subscribe", billing.handle_subscribe))
    app.add_handler(CommandHandler("plan", billing.handle_plan))
    app.add_handler(CommandHandler("cancel", billing.handle_cancel))
    app.add_handler(CommandHandler("shopping", handle_shopping))

    # Photo handlers (сжатое фото и документ-изображение оригинального качества)
    app.add_handler(MessageHandler(filters.PHOTO, wardrobe.handle_photo))
    app.add_handler(MessageHandler(filters.Document.IMAGE, wardrobe.handle_photo))

    # Кнопки главного меню
    app.add_handler(MessageHandler(filters.Regex("^✨ Что надеть$"), wardrobe.handle_what_to_wear))
    app.add_handler(MessageHandler(filters.Regex("^👗 Гардероб$"), wardrobe.handle_wardrobe_menu))
    app.add_handler(MessageHandler(filters.Regex("^💬 Спросить Касси$"), wardrobe.handle_ask_kassi))
    app.add_handler(MessageHandler(filters.Regex("^👤 Профиль$"), handle_profile))

    # ❓ Помощь — group=1 (явный приоритет перед text стилистом)
    app.add_handler(
        MessageHandler(filters.TEXT & filters.Regex("^❓ Помощь$"), help.handle_help),
        group=1,
    )

    # Test billing callbacks (ts:*)
    app.add_handler(CallbackQueryHandler(handle_test_subscribe_action, pattern="^ts:"))

    # Callback queries (кнопки)
    app.add_handler(CallbackQueryHandler(brief.handle_brief_feedback, pattern="^brief_feedback:"))
    app.add_handler(CallbackQueryHandler(brief.handle_reroll, pattern="^reroll:"))
    app.add_handler(CallbackQueryHandler(feedback.handle_feedback, pattern="^feedback:"))
    app.add_handler(CallbackQueryHandler(billing.handle_stay_free, pattern="^stay_free$"))
    app.add_handler(CallbackQueryHandler(billing.handle_compare_plans, pattern="^compare_plans$"))
    app.add_handler(CallbackQueryHandler(billing.handle_pay_stars, pattern="^pay_stars:"))
    app.add_handler(CallbackQueryHandler(billing.handle_confirm_stars, pattern="^confirm_stars:"))
    app.add_handler(CallbackQueryHandler(billing.handle_pay_stripe, pattern="^pay_stripe:"))

    # Stars payments — PreCheckout должен отвечать в течение 10 сек
    app.add_handler(PreCheckoutQueryHandler(billing.handle_pre_checkout))
    app.add_handler(
        MessageHandler(filters.SUCCESSFUL_PAYMENT, billing.handle_successful_payment),
        group=1,
    )
    app.add_handler(CallbackQueryHandler(wardrobe.handle_wardrobe_page, pattern="^wardrobe:page:"))
    app.add_handler(CallbackQueryHandler(wardrobe.handle_photo_action, pattern="^photo_action:"))
    app.add_handler(CallbackQueryHandler(wardrobe.handle_rate_mode, pattern="^rate_mode:"))
    app.add_handler(CallbackQueryHandler(wardrobe.handle_switch_owner, pattern="^switch_owner:"))
    app.add_handler(CallbackQueryHandler(wardrobe.handle_outfit_request, pattern="^outfit_request$"))
    app.add_handler(CallbackQueryHandler(wardrobe.handle_list_callback, pattern="^show_wardrobe_list$"))
    app.add_handler(CallbackQueryHandler(wardrobe.handle_add_items_hint, pattern="^add_items_hint$"))
    app.add_handler(CallbackQueryHandler(wardrobe.handle_show_upgrade, pattern="^show_upgrade$"))
    app.add_handler(CallbackQueryHandler(wardrobe.handle_show_ultra, pattern="^show_ultra$"))
    app.add_handler(CallbackQueryHandler(wardrobe.handle_notify_ultra, pattern="^notify_ultra$"))

    # Profile editing callbacks
    from bot.handlers.profile import (
        handle_edit_city, handle_edit_colortype,
        handle_add_child_start, handle_new_child_gender,
    )
    app.add_handler(CallbackQueryHandler(handle_edit_city, pattern="^edit_city$"))
    app.add_handler(CallbackQueryHandler(handle_edit_colortype, pattern="^edit_colortype$"))
    app.add_handler(CallbackQueryHandler(handle_add_child_start, pattern="^add_child_start$"))
    app.add_handler(CallbackQueryHandler(handle_new_child_gender, pattern="^new_child:"))

    # Brief share
    app.add_handler(CallbackQueryHandler(brief.handle_share, pattern="^share:"))

    # Gap analysis
    app.add_handler(CallbackQueryHandler(wardrobe.handle_gap_analysis, pattern="^gap_analysis$"))

    # edit_child_size — stub (from growth_alert button)
    app.add_handler(CallbackQueryHandler(handle_profile, pattern="^edit_child_size$"))

    # Текстовые сообщения → стилист — group=2 (после меню-хендлеров)
    _menu_texts = filters.Regex("^(👗 Гардероб|✨ Что надеть|💬 Спросить Касси|👤 Профиль|❓ Помощь)$")
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND & ~_menu_texts, text.handle_text),
        group=2,
    )

    return app
