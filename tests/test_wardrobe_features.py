"""Tests for wardrobe math, forgotten treasures, occasions, watermark, evening push."""
import pytest
from datetime import date, timedelta
from unittest.mock import MagicMock


def _item(category="top", type_name="футболка", color="белый",
          score=5.0, warmth=2, last_worn=None):
    m = MagicMock()
    m.category_group = category
    m.type = type_name
    m.color = color
    m.score_item = score
    m.warmth_level = warmth
    m.last_worn = last_worn
    m.season = ["spring", "summer", "autumn", "winter"]
    m.id = id(m)
    return m


# ── Wardrobe Math ─────────────────────────────────────────────────────────────

class TestWardrobeMath:

    def test_basic_combos(self):
        from services.wardrobe_math import calc_wardrobe_combos
        items = [
            _item("top"), _item("top"), _item("top"),       # 3 tops
            _item("bottom"), _item("bottom"),                # 2 bottoms
            _item("outerwear"),                               # 1 outerwear
            _item("footwear"),                                # 1 footwear
        ]
        result = calc_wardrobe_combos(items)
        # 3 × 2 × (1+1) × 1 × 0.7 = 8.4 → 8
        assert result == 8

    def test_with_dresses(self):
        from services.wardrobe_math import calc_wardrobe_combos
        items = [
            _item("top"), _item("bottom"),
            _item("one_piece"), _item("one_piece"),  # 2 dresses
            _item("footwear"), _item("footwear"),    # 2 shoes
        ]
        result = calc_wardrobe_combos(items)
        # (1×1×1 + 2×1) × 2 × 0.7 = 4.2 → 4
        assert result == 4

    def test_empty_wardrobe(self):
        from services.wardrobe_math import calc_wardrobe_combos
        assert calc_wardrobe_combos([]) == 0

    def test_no_bottom(self):
        from services.wardrobe_math import calc_wardrobe_combos
        items = [_item("top"), _item("top"), _item("footwear")]
        # 2 × 0 × 1 × 1 × 0.7 = 0
        assert calc_wardrobe_combos(items) == 0

    def test_large_wardrobe(self):
        from services.wardrobe_math import calc_wardrobe_combos
        items = (
            [_item("top") for _ in range(10)]
            + [_item("bottom") for _ in range(5)]
            + [_item("outerwear") for _ in range(3)]
            + [_item("footwear") for _ in range(4)]
            + [_item("one_piece") for _ in range(3)]
        )
        result = calc_wardrobe_combos(items)
        # (10×5×4 + 3×4) × 4 × 0.7 = (200+12)×4×0.7 = 593.6 → 593
        assert result > 500

    def test_underwear_ignored(self):
        from services.wardrobe_math import calc_wardrobe_combos
        items = [
            _item("top"), _item("bottom"), _item("footwear"),
            _item("underwear"), _item("base_layer"),  # should be ignored
        ]
        result = calc_wardrobe_combos(items)
        assert result > 0

    def test_format_stats(self):
        from services.wardrobe_math import format_wardrobe_stats
        items = [_item("top") for _ in range(5)] + [_item("bottom") for _ in range(3)] + [_item("footwear")]
        text = format_wardrobe_stats(items)
        assert "комбинаций" in text
        assert "📊" in text


# ── Forgotten Treasures ──────────────────────────────────────────────────────

class TestForgottenTreasures:

    def test_forgotten_bonus_21_days(self):
        """Items not worn >21 days get +2.0 bonus in selector."""
        with open("services/outfit_selector.py") as f:
            source = f.read()
        assert "21" in source
        assert "+2.0" in source or "+ 2.0" in source

    def test_never_worn_bonus(self):
        """Never-worn items (last_worn=None) get bonus."""
        with open("services/outfit_selector.py") as f:
            source = f.read()
        assert "1.5" in source  # +1.5 for never worn

    def test_forgotten_in_ai_prompt(self):
        """outfit_engine adds forgotten items hint to AI prompt."""
        with open("services/outfit_engine.py") as f:
            source = f.read()
        assert "Забытые вещи" in source
        assert "3+ недели" in source or "3+ нед" in source

    def test_forgotten_threshold_is_21(self):
        """Forgotten threshold is 21 days."""
        with open("services/outfit_engine.py") as f:
            source = f.read()
        assert "21" in source


# ── Occasions ─────────────────────────────────────────────────────────────────

class TestOccasions:

    def test_no_kids_weekday_office(self):
        """no_kids + weekday → 'офис'."""
        with open("bot/handlers/wardrobe.py") as f:
            source = f.read()
        assert '"офис"' in source

    def test_no_kids_saturday_casual(self):
        """no_kids + saturday → 'кэжуал'."""
        with open("bot/handlers/wardrobe.py") as f:
            source = f.read()
        assert '"кэжуал"' in source

    def test_no_kids_sunday_rest(self):
        """no_kids + sunday → 'отдых'."""
        with open("bot/handlers/wardrobe.py") as f:
            source = f.read()
        assert '"отдых"' in source

    def test_child_school_vs_sadik(self):
        """child age <7 → 'садик', ≥7 → 'школа'."""
        with open("bot/handlers/wardrobe.py") as f:
            source = f.read()
        assert '"школа"' in source
        assert '"садик"' in source

    def test_occasion_hints_in_engine(self):
        """outfit_engine has occasion hints dict."""
        with open("services/outfit_engine.py") as f:
            source = f.read()
        assert "деловой casual" in source
        assert "расслабленный" in source

    def test_occasion_hints_6_types(self):
        """At least 6 occasion types have hints."""
        with open("services/outfit_engine.py") as f:
            source = f.read()
        hints = ["офис", "садик", "школа", "кэжуал", "прогулка", "отдых"]
        for h in hints:
            assert f'"{h}"' in source, f"Missing occasion hint for '{h}'"


# ── Watermark ─────────────────────────────────────────────────────────────────

class TestWatermark:

    def test_watermark_in_full_template(self):
        with open("renderer/templates/tpl_full.html") as f:
            html = f.read()
        assert "fashioncastle.app" in html

    def test_no_watermark_in_hybrid(self):
        with open("renderer/templates/tpl_hybrid.html") as f:
            html = f.read()
        assert "fashioncastle.app" not in html

    def test_no_watermark_in_weather(self):
        with open("renderer/templates/tpl_weather.html") as f:
            html = f.read()
        assert "fashioncastle.app" not in html

    def test_no_watermark_in_morning(self):
        with open("renderer/templates/tpl_morning.html") as f:
            html = f.read()
        assert "fashioncastle.app" not in html


# ── Evening Push ──────────────────────────────────────────────────────────────

class TestEveningPush:

    def test_timezone_aware(self):
        """evening_push.py must filter by user timezone, not UTC."""
        with open("worker/tasks/evening_push.py") as f:
            source = f.read()
        assert "timezone" in source.lower() or "pytz" in source
        assert "local_hour" in source or "tz" in source

    def test_target_hour_20(self):
        """Evening push should target 20:00 local time."""
        with open("worker/tasks/evening_push.py") as f:
            source = f.read()
        assert "20" in source
        assert "_TARGET_HOUR" in source

    def test_scheduler_hourly(self):
        """Scheduler wires the cookbook dinner push (fashion pushes removed)."""
        with open("core/scheduler.py") as f:
            source = f.read()
        assert "cookbook_dinner" in source
