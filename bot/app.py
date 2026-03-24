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
    from bot.middleware.antibot import AntibotMiddleware
    from bot.middleware.auth import AuthMiddleware
    from bot.middleware.typing import TypingMiddleware

    # Middleware (order: antibot → auth → typing)
    app.add_handler(MessageHandler(filters.ALL, AntibotMiddleware.handle), group=-3)
    app.add_handler(CallbackQueryHandler(AntibotMiddleware.handle, pattern=".*"), group=-3)
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
    app.add_handler(CommandHandler("stats", debug.handle_stats))
    app.add_handler(CommandHandler("test_subscribe", handle_test_subscribe))
    app.add_handler(CommandHandler("help", help.handle_help))
    app.add_handler(CommandHandler("wardrobe", wardrobe.handle_list))
    app.add_handler(CommandHandler("subscribe", billing.handle_subscribe))
    app.add_handler(CommandHandler("plan", billing.handle_plan))
    app.add_handler(CommandHandler("cancel", billing.handle_cancel))
    app.add_handler(CommandHandler("shopping", handle_shopping))

    # Style passport command
    async def _style_passport_cmd(update, context):
        user = context.user_data.get("db_user")
        if not user or not getattr(user, "colortype", None):
            from services.i18n import t, get_user_lang
            await update.message.reply_text(
                "Для стиль-паспорта нужен цветотип.\n"
                "Отправь селфи или зайди в 👤 Профиль → 🎨 Цветотип"
            )
            return
        from services.selfie_analysis import _send_style_passport
        from services.i18n import get_user_lang
        await _send_style_passport(update.message, user, get_user_lang(user))
    app.add_handler(CommandHandler("style_passport", _style_passport_cmd))

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
    app.add_handler(CallbackQueryHandler(wardrobe.handle_fix_category, pattern="^fix_cg:"))
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

    # Redo selfie (from profile)
    async def _redo_selfie(update, context):
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            "📸 Отправь новое селфи при дневном свете:\n"
            "• Лицо и плечи в кадре\n"
            "• Без фильтров\n\n"
            "Касси обновит твой стилевой профиль!"
        )
        context.user_data["awaiting_selfie"] = True
    app.add_handler(CallbackQueryHandler(_redo_selfie, pattern="^redo_selfie$"))

    # Brief share
    app.add_handler(CallbackQueryHandler(brief.handle_share, pattern="^share:"))

    # Challenge
    from bot.handlers.challenge import handle_challenge_start, handle_challenge_later
    app.add_handler(CallbackQueryHandler(handle_challenge_start, pattern="^challenge_start$"))
    app.add_handler(CallbackQueryHandler(handle_challenge_later, pattern="^challenge_later$"))

    # Capsule
    from bot.handlers.capsule import handle_capsule, handle_capsule_ok, handle_capsule_share
    app.add_handler(CommandHandler("capsule", handle_capsule))
    app.add_handler(CallbackQueryHandler(handle_capsule, pattern="^capsule:build$"))
    app.add_handler(CallbackQueryHandler(handle_capsule_ok, pattern="^capsule:ok$"))
    app.add_handler(CallbackQueryHandler(handle_capsule_share, pattern="^capsule:share$"))

    # Travel
    from bot.handlers.travel import (
        handle_travel_start, handle_travel_days,
        handle_travel_occasion_toggle, handle_travel_build,
    )
    app.add_handler(CommandHandler("travel", handle_travel_start))
    app.add_handler(CallbackQueryHandler(handle_travel_start, pattern="^travel:start$"))
    app.add_handler(CallbackQueryHandler(handle_travel_days, pattern="^trv:days:"))
    app.add_handler(CallbackQueryHandler(handle_travel_occasion_toggle, pattern="^trv:occ:"))
    app.add_handler(CallbackQueryHandler(handle_travel_build, pattern="^trv:build$"))

    # Monthly report callbacks
    async def _report_ok(update, context):
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
    app.add_handler(CallbackQueryHandler(_report_ok, pattern="^report:ok$"))
    app.add_handler(CallbackQueryHandler(_report_ok, pattern="^report:share$"))

    # Language selection
    from bot.handlers.settings import handle_lang_callback
    app.add_handler(CallbackQueryHandler(handle_lang_callback, pattern="^lang:"))

    # Settings:lang → show language picker
    async def _settings_lang(update, context):
        await update.callback_query.answer()
        from bot.handlers.settings import lang_keyboard
        from services.i18n import t, get_user_lang
        lang = get_user_lang(context.user_data.get("db_user"))
        await update.callback_query.message.reply_text(
            t("lang.choose", lang), reply_markup=lang_keyboard(),
        )
    app.add_handler(CallbackQueryHandler(_settings_lang, pattern="^settings:lang$"))

    # Ask friend
    from bot.handlers.ask_friend import handle_ask_friend, handle_vote_callback
    app.add_handler(CallbackQueryHandler(handle_ask_friend, pattern="^ask_friend:"))
    app.add_handler(CallbackQueryHandler(handle_vote_callback, pattern="^vote:"))

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
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text(
                update.callback_query.message.text + "\n\n🔄 Новый план придёт завтра утром!",
                reply_markup=None,
            )
        except Exception:
            await update.callback_query.answer("🔄 Новый план придёт завтра утром!")
    app.add_handler(CallbackQueryHandler(_weekly_ok, pattern="^weekly_ok$"))
    app.add_handler(CallbackQueryHandler(_weekly_reshuffle, pattern="^weekly_reshuffle$"))

    # Геолокация для смены города в профиле
    app.add_handler(MessageHandler(filters.LOCATION, handle_edit_city_location))

    # Fitting (🛍 Подойдёт?) — menu handler
    from bot.handlers.fitting import handle_fitting_start
    app.add_handler(MessageHandler(filters.Regex("^🛍 Подойдёт"), handle_fitting_start))

    # Boost (💪 Как я?) — menu handler
    from bot.handlers.boost import handle_boost_start
    app.add_handler(MessageHandler(filters.Regex("^💪 Как я"), handle_boost_start))

    # Текстовые сообщения → стилист — group=2 (после меню-хендлеров)
    _menu_texts = filters.Regex("^((👗|👧|👦|👩)\uFE0F? Гардероб|✨ Что надеть|💬 Спросить Касси|🛍 Подойдёт|💪 Как я|👤 Профиль|❓ Помощь)$")

    # Travel city text input (group=1, before stylist chat; checks travel_step inside)
    from bot.handlers.travel import handle_travel_city
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & ~_menu_texts,
        handle_travel_city,
    ), group=1)

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND & ~_menu_texts, text.handle_text),
        group=2,
    )

    # Global error handler — reports unhandled exceptions to Sentry
    from bot.handlers.error import handle_error
    app.add_error_handler(handle_error)

    return app
