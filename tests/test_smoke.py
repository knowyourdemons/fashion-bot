"""
Smoke тесты — проверяют что все модули импортируются без ошибок.
Ловят: NameError, ImportError, синтаксические ошибки.
Запускаются без БД и Redis.
"""
import pytest


# ── Handlers ──────────────────────────────────────────────────────────────

def test_import_onboarding():
    from bot.handlers import onboarding
    assert hasattr(onboarding, "handle_start")
    assert hasattr(onboarding, "_finish_onboarding")
    assert hasattr(onboarding, "build_conversation_handler")


def test_import_wardrobe():
    from bot.handlers import wardrobe
    assert hasattr(wardrobe, "handle_photo")
    assert hasattr(wardrobe, "handle_wardrobe_menu")
    assert hasattr(wardrobe, "handle_outfit_request")
    assert hasattr(wardrobe, "handle_list_callback")
    assert hasattr(wardrobe, "handle_switch_owner")
    assert hasattr(wardrobe, "_check_crop_quality")
    assert hasattr(wardrobe, "_fix_bbox")


def test_wardrobe_private_helpers_exist():
    """Регрессия: эти функции были случайно удалены при рефакторинге (2026-03-19).
    Импортируем явно — NameError сломает тест сразу."""
    from bot.handlers.wardrobe import (
        _get_owner,
        _get_scoring_matrix,
        _load_existing_set,
        _maybe_trigger_first_brief,
        _upload_crop,
        _save_one,
        _analyze_and_save,
        _rate_photos,
        _send_action_buttons,
        _collect_and_ask,
        _handle_single_photo,
        _process_media_group,
        _generate_outfit_for_user,
        _show_wardrobe_page,
    )
    # Проверяем что это coroutine-функции (не None, не строки)
    import asyncio
    for fn in [
        _get_owner, _get_scoring_matrix, _load_existing_set,
        _maybe_trigger_first_brief, _upload_crop, _save_one,
        _analyze_and_save, _rate_photos, _handle_single_photo,
        _generate_outfit_for_user, _show_wardrobe_page,
    ]:
        assert asyncio.iscoroutinefunction(fn), f"{fn.__name__} должна быть async"


def test_import_help():
    from bot.handlers import help
    assert hasattr(help, "handle_help")


def test_import_profile():
    from bot.handlers import profile
    assert hasattr(profile, "handle_profile")


def test_import_menu():
    from bot.handlers import menu
    assert hasattr(menu, "get_main_menu")
    assert hasattr(menu, "get_remove_keyboard")
    # Проверить что меню создаётся без ошибок
    m = menu.get_main_menu()
    assert m is not None


def test_import_text():
    from bot.handlers import text
    from core.permissions import get_limit
    assert hasattr(text, "handle_text")
    # Лимиты чата теперь в core.permissions, не как константы в text.py
    assert get_limit("chat_per_day", "free") == 3
    assert get_limit("chat_per_day", "premium") == 20


# ── Services ──────────────────────────────────────────────────────────────

def test_import_image_builder():
    from services.image_builder import (
        build_collage, _make_placeholder,
        _make_thumb, _build_grid, THUMB_SIZE,
    )
    assert callable(build_collage)
    assert callable(_make_placeholder)
    assert isinstance(THUMB_SIZE, int)


def test_adult_silhouette_exists():
    from services.image_builder import _draw_adult_silhouette
    assert callable(_draw_adult_silhouette)


def test_make_placeholder_adult():
    from services.image_builder import _make_placeholder, THUMB_SIZE
    ph = _make_placeholder("top", "верх", adult=True)
    assert ph.size == (THUMB_SIZE, THUMB_SIZE)
    # Взрослый силуэт не должен быть пустым
    pixels = list(ph.getdata())
    bg = (240, 238, 240)
    non_bg = [p for p in pixels if tuple(p[:3]) != bg]
    assert len(non_bg) > 100, f"Взрослый силуэт 'top' почти пустой ({len(non_bg)} пикс)"


def test_import_image_processor():
    from services.image_processor import preprocess, remove_background, compute_phash
    assert callable(preprocess)
    assert callable(remove_background)


def test_import_scoring():
    from services.scoring import ScoringService, calc_item_score
    assert callable(calc_item_score)


def test_import_weather():
    from services.weather import WeatherService, WeatherData
    assert callable(WeatherService)


# ── Worker tasks ──────────────────────────────────────────────────────────

def test_import_morning_brief():
    from worker.tasks.morning_brief import (
        generate_brief, _select_outfit,
        _get_temp_regime, _format_child_block,
        _format_item, _SEASONS,
    )
    assert callable(generate_brief)
    assert callable(_select_outfit)
    assert callable(_get_temp_regime)
    assert isinstance(_SEASONS, dict)
    assert len(_SEASONS) == 12


def test_import_style_config():
    from worker.tasks.style_config import (
        get_placeholder_label, get_wow_phrase,
        COLORTYPE_PALETTES, SEASON_SLOT_TYPES,
        WOW_PHRASES, _needs_tights,
    )
    assert isinstance(COLORTYPE_PALETTES, dict)
    assert isinstance(WOW_PHRASES, list)
    assert len(WOW_PHRASES) >= 5
    assert callable(_needs_tights)


def test_get_text_system_importable():
    from bot.handlers.text import _get_text_system
    assert callable(_get_text_system)


def test_handle_switch_owner_exists():
    from bot.handlers.wardrobe import handle_switch_owner, handle_add_items_hint
    assert callable(handle_switch_owner)
    assert callable(handle_add_items_hint)


def test_rate_system_prompts_exist():
    from bot.handlers.wardrobe import _RATE_SYSTEM_CHILD, _RATE_SYSTEM_ADULT
    assert len(_RATE_SYSTEM_CHILD) > 500, "CHILD промпт слишком короткий"
    assert len(_RATE_SYSTEM_ADULT) > 500, "ADULT промпт слишком короткий"
    assert "взрослого" in _RATE_SYSTEM_ADULT.lower(), \
        "ADULT промпт должен упоминать взрослого"
    assert "детск" in _RATE_SYSTEM_CHILD.lower() or \
           "ребёнк" in _RATE_SYSTEM_CHILD.lower(), \
        "CHILD промпт должен упоминать детей/ребёнка"
    assert "НЕ упоминай детей" in _RATE_SYSTEM_ADULT, \
        "ADULT промпт должен запрещать упоминание детей"


def test_call_rate_vision_accepts_owner_type():
    import inspect
    from bot.handlers.wardrobe import _call_rate_vision
    sig = inspect.signature(_call_rate_vision)
    assert "owner_type" in sig.parameters, \
        "_call_rate_vision должен принимать owner_type"


# ── DB models ─────────────────────────────────────────────────────────────

def test_import_db_models():
    from db.models.user import User
    from db.models.child import Child
    from db.models.wardrobe import WardrobeItem
    from db.models.brief_log import BriefLog
    # Проверить что colortype есть в User
    assert hasattr(User, "colortype"), "Миграция colortype не применена!"


# ── Core ──────────────────────────────────────────────────────────────────

def test_import_anthropic_client():
    from core.anthropic_client import AnthropicPool, get_anthropic_pool
    assert AnthropicPool is not None
    assert callable(get_anthropic_pool)


def test_import_config():
    from config import settings
    assert settings.telegram_bot_token
    assert settings.database_write_url


def test_import_app():
    """Критичный тест — app.py должен импортироваться без ошибок."""
    from bot.app import create_application
    assert callable(create_application)


def test_permissions_importable():
    from core.permissions import (
        get_effective_plan, get_limit,
        is_brief_day, is_brief_day_tomorrow,
        get_trial_days_left, is_trial_active,
        LIMITS, PRICES, ULTRA_FEATURES,
    )
    assert isinstance(LIMITS, dict)
    assert isinstance(PRICES, dict)
    assert len(ULTRA_FEATURES) >= 3
    assert "free" in LIMITS
    assert "premium" in LIMITS


def test_subscribe_handler_importable():
    from bot.handlers.billing import handle_subscribe, handle_stay_free
    assert callable(handle_subscribe)
    assert callable(handle_stay_free)


def test_upgrade_handlers_importable():
    from bot.handlers.wardrobe import (
        handle_show_upgrade, handle_show_ultra, handle_notify_ultra,
    )
    assert callable(handle_show_upgrade)
    assert callable(handle_show_ultra)
    assert callable(handle_notify_ultra)


def test_evening_push_importable():
    from worker.tasks.evening_push import run
    assert callable(run)


def test_subscription_expiry_updated():
    from worker.tasks.subscription_expiry import run
    import inspect
    src = inspect.getsource(run)
    assert "trial_ends_at" in src, "subscription_expiry должен проверять trial_ends_at"


def test_stripe_provider_importable():
    from billing.stripe_provider import StripeProvider
    assert callable(getattr(StripeProvider, "create_invoice", None))


def test_yukassa_stub_importable():
    from billing.yukassa_provider import YuKassaProvider
    import asyncio, pytest
    p = YuKassaProvider()
    with pytest.raises(NotImplementedError):
        asyncio.run(p.create_invoice("1", "premium", "monthly"))


def test_paddle_stub_importable():
    from billing.paddle_provider import PaddleProvider
    import asyncio, pytest
    p = PaddleProvider()
    with pytest.raises(NotImplementedError):
        asyncio.run(p.create_invoice("1", "premium", "monthly"))


def test_stars_billing_handlers_importable():
    from bot.handlers.billing import (
        handle_pay_stars, handle_pay_stripe, handle_confirm_stars,
        handle_successful_payment, handle_pre_checkout,
        _subscribe_keyboard,
    )
    assert callable(handle_pay_stars)
    assert callable(handle_pay_stripe)
    assert callable(handle_confirm_stars)
    assert callable(handle_successful_payment)
    assert callable(handle_pre_checkout)
    kb = _subscribe_keyboard()
    assert len(kb.inline_keyboard) >= 3  # минимум 3 ряда Stars


def test_stars_keyboard_amounts():
    from bot.handlers.billing import _subscribe_keyboard
    from core.permissions import PRICES
    kb = _subscribe_keyboard()
    labels = [btn.text for row in kb.inline_keyboard for btn in row]
    assert any("700" in l for l in labels), "monthly 700 stars должен быть"
    assert any("5500" in l for l in labels), "yearly 5500 stars должен быть"


def test_stripe_webhook_importable():
    from api.routes.webhooks import stripe_webhook, _activate_premium_after_payment
    assert callable(stripe_webhook)
    assert callable(_activate_premium_after_payment)


def test_app_has_precheckout_handler():
    from bot.app import create_application
    from telegram.ext import PreCheckoutQueryHandler
    app = create_application()
    handler_types = [type(h) for h in app.handlers.get(0, [])]
    assert PreCheckoutQueryHandler in handler_types, "PreCheckoutQueryHandler must be registered"


def test_billing_providers_available():
    """Все billing провайдеры импортируются."""
    from billing.stripe_provider import StripeProvider
    from billing.yukassa_provider import YuKassaProvider
    from billing.paddle_provider import PaddleProvider
    assert callable(getattr(StripeProvider, "create_invoice", None))
    assert callable(getattr(YuKassaProvider, "create_invoice", None))
    assert callable(getattr(PaddleProvider, "create_invoice", None))


def test_yukassa_not_available_by_default():
    """ЮKassa заглушка — NotImplementedError при вызове."""
    from billing.yukassa_provider import YuKassaProvider
    import asyncio, pytest
    p = YuKassaProvider()
    with pytest.raises(NotImplementedError):
        asyncio.run(p.create_invoice("1", "premium", "monthly"))


def test_paddle_not_available_by_default():
    """Paddle заглушка — NotImplementedError при вызове."""
    from billing.paddle_provider import PaddleProvider
    import asyncio, pytest
    p = PaddleProvider()
    with pytest.raises(NotImplementedError):
        asyncio.run(p.create_invoice("1", "premium", "monthly"))


def test_trial_activation_in_wardrobe():
    """handle_photo содержит логику активации trial."""
    import inspect
    from bot.handlers.wardrobe import handle_photo
    src = inspect.getsource(handle_photo)
    assert "trial_started_at" in src, "trial активация должна быть в handle_photo"
    assert "trial_ends_at" in src


def test_limits_in_wardrobe():
    """handle_photo проверяет лимиты фото."""
    import inspect
    from bot.handlers.wardrobe import handle_photo
    src = inspect.getsource(handle_photo)
    assert "photos_per_day" in src


def test_limits_in_text_handler():
    """handle_text проверяет лимит чатов."""
    import inspect
    from bot.handlers.text import handle_text
    src = inspect.getsource(handle_text)
    assert "chat_per_day" in src


def test_brief_by_day_gate():
    """generate_brief пропускает дни без брифа."""
    import os
    src_path = os.path.join(os.path.dirname(__file__), "..", "worker", "tasks", "morning_brief.py")
    with open(os.path.abspath(src_path)) as f:
        src = f.read()
    assert "is_brief_day" in src, "бриф должен проверять день недели"


def test_subscription_expiry_checks_trial():
    """subscription_expiry проверяет trial_ends_at."""
    import inspect
    from worker.tasks.subscription_expiry import run
    src = inspect.getsource(run)
    assert "trial_ends_at" in src


def test_evening_push_checks_brief_day_tomorrow():
    """evening_push проверяет is_brief_day_tomorrow."""
    import inspect
    from worker.tasks.evening_push import run
    src = inspect.getsource(run)
    assert "is_brief_day_tomorrow" in src or "brief_day" in src.lower()


def test_scheduler_has_cookbook_dinner():
    """Планировщик регистрирует кукбук-пуш «что на ужин» (заменил фешн-рассылки)."""
    import inspect
    from core.scheduler import Scheduler
    src = inspect.getsource(Scheduler._setup_jobs)
    assert "cookbook_dinner" in src
