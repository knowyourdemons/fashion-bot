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
    assert hasattr(wardrobe, "handle_set_owner")
    assert hasattr(wardrobe, "_check_crop_quality")
    assert hasattr(wardrobe, "_fix_bbox")


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
    assert hasattr(text, "handle_text")
    assert hasattr(text, "CHAT_LIMIT_FREE")
    assert hasattr(text, "CHAT_LIMIT_PREMIUM")
    assert text.CHAT_LIMIT_FREE == 5
    assert text.CHAT_LIMIT_PREMIUM == 20


# ── Services ──────────────────────────────────────────────────────────────

def test_import_image_builder():
    from services.image_builder import (
        build_collage, _make_placeholder,
        _make_thumb, _build_grid, THUMB_SIZE,
    )
    assert callable(build_collage)
    assert callable(_make_placeholder)
    assert isinstance(THUMB_SIZE, int)


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
        WOW_PHRASES,
    )
    assert isinstance(COLORTYPE_PALETTES, dict)
    assert isinstance(WOW_PHRASES, list)
    assert len(WOW_PHRASES) >= 5


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
