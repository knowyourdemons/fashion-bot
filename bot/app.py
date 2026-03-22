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
    from bot.handlers.profile import handle_profile, handle_edit_city_location
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
    app.add_handler(CommandHandler("debug_eval", debug.handle_debug_eval))
    app.add_handler(CommandHandler("debug_gaps", debug.handle_debug_gaps))
    app.add_handler(CommandHandler("debug_style", debug.handle_debug_style))
    app.add_handler(CommandHandler("debug_wardrobe", debug.handle_debug_wardrobe))
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
    app.add_handler(MessageHandler(filters.Regex("^(👗|👧|👦|👩)\uFE0F? Гардероб$"), wardrobe.handle_wardrobe_menu))
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
    app.add_handler(CallbackQueryHandler(brief.handle_reroll, pattern="^reroll[:_]"))
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
    # Wardrobe browser (visual navigation)
    from bot.handlers.wardrobe_browser import (
        handle_overview, handle_season_filter, handle_category_grid,
        handle_item_card, handle_delete_confirm, handle_delete_yes,
        handle_owner_switch, handle_season_edit, handle_noop,
    )
    app.add_handler(CallbackQueryHandler(handle_overview, pattern="^w:ov$"))
    app.add_handler(CallbackQueryHandler(handle_owner_switch, pattern="^w:ow:"))
    app.add_handler(CallbackQueryHandler(handle_season_filter, pattern="^w:sz:"))
    app.add_handler(CallbackQueryHandler(handle_category_grid, pattern="^w:cat:"))
    app.add_handler(CallbackQueryHandler(handle_item_card, pattern="^w:it:"))
    app.add_handler(CallbackQueryHandler(handle_delete_confirm, pattern="^w:del:"))
    app.add_handler(CallbackQueryHandler(handle_delete_yes, pattern="^w:dly:"))
    app.add_handler(CallbackQueryHandler(handle_season_edit, pattern="^w:szed:"))
    app.add_handler(CallbackQueryHandler(handle_noop, pattern="^w:noop$"))

    # Noop callback (page counter, active tab)
    async def _noop_callback(update, context):
        await update.callback_query.answer()
    app.add_handler(CallbackQueryHandler(_noop_callback, pattern="^noop$"))

    app.add_handler(CallbackQueryHandler(wardrobe.handle_list_callback, pattern="^show_wardrobe_list$"))
    app.add_handler(CallbackQueryHandler(wardrobe.handle_add_items_hint, pattern="^add_items_hint$"))
    app.add_handler(CallbackQueryHandler(wardrobe.handle_show_upgrade, pattern="^show_upgrade$"))
    app.add_handler(CallbackQueryHandler(wardrobe.handle_show_ultra, pattern="^show_ultra$"))
    app.add_handler(CallbackQueryHandler(wardrobe.handle_notify_ultra, pattern="^notify_ultra$"))

    # Profile editing callbacks
    from bot.handlers.profile import (
        handle_edit_city, handle_edit_colortype, handle_set_colortype,
        handle_add_child_start, handle_new_child_gender, handle_edit_child_size,
        handle_edit_style_prefs, handle_set_style, handle_avoid_pref,
    )
    app.add_handler(CallbackQueryHandler(handle_edit_city, pattern="^edit_city$"))
    app.add_handler(CallbackQueryHandler(handle_edit_colortype, pattern="^edit_colortype$"))
    app.add_handler(CallbackQueryHandler(handle_set_colortype, pattern="^set_colortype:"))
    app.add_handler(CallbackQueryHandler(handle_edit_style_prefs, pattern="^edit_style_prefs$"))
    app.add_handler(CallbackQueryHandler(handle_set_style, pattern="^set_style:"))
    app.add_handler(CallbackQueryHandler(handle_avoid_pref, pattern="^avoid_pref:"))
    app.add_handler(CallbackQueryHandler(handle_add_child_start, pattern="^add_child_start$"))
    app.add_handler(CallbackQueryHandler(handle_new_child_gender, pattern="^new_child:"))
    app.add_handler(CallbackQueryHandler(handle_edit_child_size, pattern="^edit_child_size:"))

    # Brief share
    app.add_handler(CallbackQueryHandler(brief.handle_share, pattern="^share:"))

    # Gap analysis
    app.add_handler(CallbackQueryHandler(wardrobe.handle_gap_analysis, pattern="^gap_analysis$"))

    # Style quiz
    from bot.handlers.style_quiz import handle_quiz_start, handle_quiz_answer, handle_quiz_later, handle_quiz_done
    app.add_handler(CallbackQueryHandler(handle_quiz_start, pattern="^quiz_start$"))
    app.add_handler(CallbackQueryHandler(handle_quiz_answer, pattern="^quiz:"))
    app.add_handler(CallbackQueryHandler(handle_quiz_later, pattern="^quiz_later$"))
    app.add_handler(CallbackQueryHandler(handle_quiz_done, pattern="^quiz_done$"))

    # Selfie colortype
    app.add_handler(CallbackQueryHandler(wardrobe.handle_selfie_colortype_start, pattern="^selfie_colortype_start$"))
    app.add_handler(CallbackQueryHandler(wardrobe.handle_selfie_colortype_later, pattern="^selfie_colortype_later$"))
    app.add_handler(CallbackQueryHandler(wardrobe.handle_selfie_colortype_manual, pattern="^manual_colortype:"))

    # Weekly plan callbacks
    async def _weekly_ok(update, context):
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
    async def _weekly_reshuffle(update, context):
        await update.callback_query.answer("🔄 Перемешиваю...")
        # TODO: regenerate weekly plan
        try:
            await update.callback_query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
    app.add_handler(CallbackQueryHandler(_weekly_ok, pattern="^weekly_ok$"))
    app.add_handler(CallbackQueryHandler(_weekly_reshuffle, pattern="^weekly_reshuffle$"))

    # Геолокация для смены города в профиле
    app.add_handler(MessageHandler(filters.LOCATION, handle_edit_city_location))

    # Fitting (🛍 Подойдёт?) — menu handler
    from bot.handlers.fitting import handle_fitting_start
    app.add_handler(MessageHandler(filters.Regex("^🛍 Подойдёт"), handle_fitting_start))

    # Текстовые сообщения → стилист — group=2 (после меню-хендлеров)
    _menu_texts = filters.Regex("^((👗|👧|👦|👩)\uFE0F? Гардероб|✨ Что надеть|💬 Спросить Касси|🛍 Подойдёт|👤 Профиль|❓ Помощь)$")
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND & ~_menu_texts, text.handle_text),
        group=2,
    )

    # Global error handler — reports unhandled exceptions to Sentry
    from bot.handlers.error import handle_error
    app.add_error_handler(handle_error)

    return app
