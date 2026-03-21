"""Tests for services/brief_formatter.py — pure formatting functions."""
import pytest
from unittest.mock import MagicMock, patch

from services.brief_formatter import (
    _sign,
    _format_item,
    format_weather_line,
    _format_child_block,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_item(type_: str, color: str = "") -> MagicMock:
    """Create a fake WardrobeItem-like object."""
    item = MagicMock()
    item.type = type_
    item.color = color
    return item


# ── _sign ────────────────────────────────────────────────────────────────────

class TestSign:
    def test_positive(self):
        assert _sign(5) == "+"

    def test_negative(self):
        assert _sign(-3) == ""

    def test_zero(self):
        assert _sign(0) == "+"

    def test_large_negative(self):
        assert _sign(-20.5) == ""


# ── _format_item ─────────────────────────────────────────────────────────────

class TestFormatItem:
    def test_type_and_color(self):
        item = _make_item("Куртка", "синий")
        assert _format_item(item) == "Куртка синий"

    def test_missing_color(self):
        item = _make_item("Шапка", "")
        assert _format_item(item) == "Шапка"

    def test_none_color(self):
        item = _make_item("Кроссовки", None)
        assert _format_item(item) == "Кроссовки"

    def test_color_stem_in_type_dedup(self):
        """If the color stem is already in the type name, don't repeat it."""
        item = _make_item("Розовая кофта", "розовый")
        # "розов" (stem of "розовый") is in "розовая кофта" lowercase
        assert _format_item(item) == "Розовая кофта"

    def test_short_color_no_stem_trim(self):
        """Colors <= 5 chars use full string for stem check."""
        item = _make_item("Шорты", "беж")
        # "беж" (len 3 <= 5) — stem == full word, not in "шорты"
        assert _format_item(item) == "Шорты беж"


# ── format_weather_line ──────────────────────────────────────────────────────

class TestFormatWeatherLine:
    def test_all_three_temps(self):
        weather = {
            "temp_morning": 4.0,
            "temp_day": 8.0,
            "temp_evening": 2.0,
            "wmo_morning": 0,
            "wmo_day": 2,
            "wmo_evening": 61,
        }
        result = format_weather_line(weather)
        assert "+4°" in result
        assert "+8°" in result
        assert "+2°" in result
        assert "утро" in result
        assert "день" in result
        assert "вечер" in result
        assert " → " in result

    def test_missing_morning(self):
        weather = {
            "temp_day": 10.0,
            "temp_evening": 5.0,
            "wmo_day": 0,
            "wmo_evening": 0,
        }
        result = format_weather_line(weather)
        assert "утро" not in result
        assert "день" in result
        assert "вечер" in result

    def test_missing_all(self):
        result = format_weather_line({})
        assert result == ""

    def test_negative_temps(self):
        weather = {
            "temp_morning": -5.0,
            "temp_day": -1.0,
            "temp_evening": -10.0,
            "wmo_morning": 71,
            "wmo_day": 73,
            "wmo_evening": 75,
        }
        result = format_weather_line(weather)
        assert "-5°" in result
        assert "-1°" in result
        assert "-10°" in result
        # No "+" for negatives
        assert "+-" not in result

    def test_rounds_float(self):
        weather = {
            "temp_morning": 4.6,
            "wmo_morning": 0,
        }
        result = format_weather_line(weather)
        assert "+5°" in result


# ── _format_child_block ──────────────────────────────────────────────────────

class TestFormatChildBlock:
    def test_full_outfit(self):
        outfit = {
            "top": _make_item("Кофта", "розовый"),
            "bottom": _make_item("Джинсы", "синий"),
            "outerwear": _make_item("Куртка", "красный"),
            "footwear": _make_item("Ботинки", "коричневый"),
            "hat": _make_item("Шапка", "белый"),
        }
        result = _format_child_block("Алиса", "садик", outfit)
        assert "Алиса" in result
        assert "садик" in result
        assert "ОДЕЖДА" in result
        assert "ОБУВЬ" in result
        assert "НА ВЫХОД" in result

    def test_one_piece_instead_of_top_bottom(self):
        outfit = {
            "one_piece": _make_item("Комбинезон", "серый"),
            "footwear": _make_item("Сапоги", "чёрный"),
        }
        result = _format_child_block("Маша", "садик", outfit)
        assert "Комбинезон" in result
        assert "ОДЕЖДА" in result

    def test_underwear_text(self):
        outfit = {
            "underwear_text": "трусики, майка",
            "top": _make_item("Свитер", "зелёный"),
        }
        result = _format_child_block("Алиса", "садик", outfit)
        assert "ПОД ОДЕЖДУ" in result
        assert "трусики, майка" in result

    def test_outfit_comment(self):
        outfit = {"top": _make_item("Футболка", "белый")}
        result = _format_child_block(
            "Алиса", "садик", outfit, outfit_comment="Лёгкий образ на тёплый день!"
        )
        assert "💬" in result
        assert "Лёгкий образ" in result
        assert "Касси" in result

    def test_empty_outfit(self):
        result = _format_child_block("Алиса", "садик", {})
        assert "Алиса" in result
        assert "садик" in result
        # No clothing sections if nothing provided
        assert "ОДЕЖДА" not in result
        assert "ОБУВЬ" not in result

    def test_no_outfit_comment_when_none(self):
        outfit = {"top": _make_item("Рубашка", "голубой")}
        result = _format_child_block("Алиса", "садик", outfit)
        assert "💬" not in result
        assert "Касси" not in result

    def test_thermal_underwear(self):
        outfit = {
            "thermal_top": True,
            "thermal_bottom": True,
            "top": _make_item("Свитер", "серый"),
        }
        result = _format_child_block("Алиса", "прогулка", outfit)
        assert "термобельё верх" in result
        assert "термобельё низ" in result

    def test_tights_in_under_section(self):
        outfit = {
            "tights": _make_item("Колготки", "белый"),
            "top": _make_item("Платье", "розовый"),
        }
        result = _format_child_block("Алиса", "садик", outfit)
        assert "ПОД ОДЕЖДУ" in result
        assert "Колготки" in result

    def test_socks_fallback_when_no_tights(self):
        outfit = {
            "socks": _make_item("Носки", ""),
            "top": _make_item("Футболка", "жёлтый"),
        }
        result = _format_child_block("Алиса", "садик", outfit)
        assert "ПОД ОДЕЖДУ" in result
        assert "Носки" in result

    def test_missing_outerwear_hint_cold(self):
        """When outerwear missing and temp < 15, show hint."""
        outfit = {"top": _make_item("Кофта", "серый")}
        result = _format_child_block("Алиса", "садик", outfit, temp=5.0)
        assert "НА ВЫХОД" in result
        assert "Куртка" in result
        assert "добавь" in result

    def test_missing_hat_hint_cold(self):
        """When hat missing and temp < 8, show hint."""
        outfit = {"top": _make_item("Кофта", "серый")}
        result = _format_child_block("Алиса", "садик", outfit, temp=3.0)
        assert "Шапка" in result
        assert "добавь" in result

    def test_no_hint_warm_weather(self):
        """No outerwear/hat hint when warm."""
        outfit = {"top": _make_item("Футболка", "белый")}
        result = _format_child_block("Алиса", "садик", outfit, temp=20.0)
        assert "добавь" not in result

    def test_regime_parameter_accepted(self):
        """regime parameter is accepted without errors."""
        outfit = {"top": _make_item("Кофта", "серый")}
        result = _format_child_block(
            "Алиса", "садик", outfit, regime="тепло"
        )
        assert "Алиса" in result

    def test_html_bold_child_name(self):
        outfit = {}
        result = _format_child_block("Маша", "школа", outfit)
        assert "<b>Маша</b>" in result

    def test_scarf_hint_below_5(self):
        """When scarf missing and temp < 5, show hint."""
        outfit = {"top": _make_item("Кофта", "серый")}
        result = _format_child_block("Алиса", "садик", outfit, temp=2.0)
        assert "Шарф" in result
        assert "добавь" in result
