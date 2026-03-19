"""Tests for services/outfit_builder.py — unified outfit slot builder."""
import pytest
from datetime import date
from unittest.mock import MagicMock


def _make_item(slot_key, item_type="футболка", color="белый", score=7.0, show=True):
    item = MagicMock()
    item.type = item_type
    item.color = color
    item.score_item = score
    item.show_in_collage = show
    item.photo_id = f"photo_{slot_key}"
    item.photo_url = None
    return item


def _make_child(gender="girl", name="Алиса"):
    child = MagicMock()
    child.gender = gender
    child.name = name
    return child


# ── score_to_text ─────────────────────────────────────────────────────────────

class TestScoreToText:
    def test_excellent(self):
        from services.outfit_builder import score_to_text
        assert score_to_text(9.0) == "🌟 Отличная вещь!"

    def test_good(self):
        from services.outfit_builder import score_to_text
        assert score_to_text(7.5) == "👍 Хорошая вещь"

    def test_basic(self):
        from services.outfit_builder import score_to_text
        assert score_to_text(6.0) == "👌 Базовая вещь"

    def test_home(self):
        from services.outfit_builder import score_to_text
        assert score_to_text(3.0) == "👕 Уютная вещь для дома"

    def test_boundary_8_5(self):
        from services.outfit_builder import score_to_text
        assert score_to_text(8.5) == "🌟 Отличная вещь!"

    def test_boundary_7_0(self):
        from services.outfit_builder import score_to_text
        assert score_to_text(7.0) == "👍 Хорошая вещь"


class TestOutfitScoreToText:
    def test_excellent(self):
        from services.outfit_builder import outfit_score_to_text
        assert outfit_score_to_text(9.0) == "🌟 Супер-образ!"

    def test_good(self):
        from services.outfit_builder import outfit_score_to_text
        assert outfit_score_to_text(7.5) == "👍 Отличный образ"

    def test_ok(self):
        from services.outfit_builder import outfit_score_to_text
        assert outfit_score_to_text(6.0) == "👌 Хороший образ"

    def test_poor(self):
        from services.outfit_builder import outfit_score_to_text
        assert outfit_score_to_text(3.0) == "👌 Образ на каждый день"


# ── get_collage_params ────────────────────────────────────────────────────────

class TestGetCollageParams:
    def test_girl_child(self):
        from services.outfit_builder import get_collage_params
        child = _make_child("girl")
        params = get_collage_params(child=child, temp=15.0)
        assert params["theme"] == "girl"
        assert "fashioncastle.app" in params["footer_text"]
        assert child.name in params["header_text"]

    def test_boy_child(self):
        from services.outfit_builder import get_collage_params
        child = _make_child("boy", "Коля")
        params = get_collage_params(child=child, temp=10.0)
        assert params["theme"] == "boy"
        assert "Коля" in params["header_text"]

    def test_adult_no_child(self):
        from services.outfit_builder import get_collage_params
        params = get_collage_params(temp=20.0)
        assert params["theme"] == "adult"
        assert "fashioncastle.app" in params["footer_text"]

    def test_rain_emoji(self):
        from services.outfit_builder import get_collage_params
        params = get_collage_params(temp=15.0, precip=60.0)
        assert "🌧" in params["header_text"]

    def test_hot_emoji(self):
        from services.outfit_builder import get_collage_params
        params = get_collage_params(temp=30.0)
        assert "☀️" in params["header_text"]

    def test_temp_none(self):
        from services.outfit_builder import get_collage_params
        params = get_collage_params()
        assert params["theme"] == "adult"

    def test_day_type_in_header(self):
        from services.outfit_builder import get_collage_params
        child = _make_child()
        params = get_collage_params(child=child, temp=10.0, day_type="садик")
        assert "садик" in params["header_text"]


# ── build_outfit_slots ────────────────────────────────────────────────────────

class TestBuildOutfitSlots:
    def test_footwear_always_present(self):
        from services.outfit_builder import build_outfit_slots
        outfit = {}  # empty wardrobe
        slots = build_outfit_slots(outfit, temp=15.0)
        slot_names = [s["slot"] for s in slots]
        assert "footwear" in slot_names

    def test_footwear_placeholder_when_missing(self):
        from services.outfit_builder import build_outfit_slots
        outfit = {}
        slots = build_outfit_slots(outfit, temp=15.0)
        fw = next(s for s in slots if s["slot"] == "footwear")
        assert fw["has_item"] is False

    def test_outerwear_placeholder_cold(self):
        from services.outfit_builder import build_outfit_slots
        outfit = {}
        slots = build_outfit_slots(outfit, temp=5.0)
        slot_names = [s["slot"] for s in slots]
        assert "outerwear" in slot_names
        ow = next(s for s in slots if s["slot"] == "outerwear")
        assert ow["has_item"] is False

    def test_no_outerwear_placeholder_hot(self):
        from services.outfit_builder import build_outfit_slots
        outfit = {}
        # "жара" regime (>22°C): SEASON_SLOT_TYPES["outerwear"]["жара"] = None → no placeholder
        slots = build_outfit_slots(outfit, temp=30.0)
        slot_names = [s["slot"] for s in slots]
        assert "outerwear" not in slot_names

    def test_hat_placeholder_cold(self):
        from services.outfit_builder import build_outfit_slots
        outfit = {}
        slots = build_outfit_slots(outfit, temp=5.0)
        slot_names = [s["slot"] for s in slots]
        assert "hat" in slot_names

    def test_outerwear_and_hat_very_cold(self):
        from services.outfit_builder import build_outfit_slots
        outfit = {}
        # "мороз" regime: outerwear and hat both get placeholders
        slots = build_outfit_slots(outfit, temp=-2.0)
        slot_names = [s["slot"] for s in slots]
        assert "outerwear" in slot_names
        assert "hat" in slot_names
        # scarf/gloves are not in SEASON_SLOT_TYPES → no placeholders

    def test_real_item_in_slot(self):
        from services.outfit_builder import build_outfit_slots
        item = _make_item("top")
        outfit = {"top": item}
        slots = build_outfit_slots(outfit, temp=15.0)
        top_slot = next((s for s in slots if s["slot"] == "top"), None)
        assert top_slot is not None
        assert top_slot["has_item"] is True
        assert top_slot["photo_id"] == "photo_top"

    def test_one_piece_excludes_top_bottom(self):
        from services.outfit_builder import build_outfit_slots
        item = _make_item("one_piece", "платье")
        outfit = {"one_piece": item}
        slots = build_outfit_slots(outfit, temp=20.0)
        slot_names = [s["slot"] for s in slots]
        assert "one_piece" in slot_names
        assert "top" not in slot_names
        assert "bottom" not in slot_names

    def test_top_bottom_excludes_one_piece(self):
        from services.outfit_builder import build_outfit_slots
        outfit = {
            "top": _make_item("top"),
            "bottom": _make_item("bottom"),
        }
        slots = build_outfit_slots(outfit, temp=20.0)
        slot_names = [s["slot"] for s in slots]
        assert "top" in slot_names
        assert "bottom" in slot_names
        assert "one_piece" not in slot_names

    def test_child_gender_in_slots(self):
        from services.outfit_builder import build_outfit_slots
        child = _make_child("boy")
        outfit = {}
        slots = build_outfit_slots(outfit, child=child, temp=15.0)
        for s in slots:
            assert s["gender"] == "boy"

    def test_adult_flag_when_no_child(self):
        from services.outfit_builder import build_outfit_slots
        outfit = {}
        slots = build_outfit_slots(outfit, temp=15.0)
        for s in slots:
            assert s["adult"] is True

    def test_show_in_collage_false_skips_item(self):
        from services.outfit_builder import build_outfit_slots
        item = _make_item("top", show=False)
        outfit = {"top": item}
        slots = build_outfit_slots(outfit, temp=20.0)
        top_slot = next((s for s in slots if s["slot"] == "top"), None)
        # item with show_in_collage=False → treated as missing → placeholder or skipped
        if top_slot:
            assert top_slot["has_item"] is False

    def test_temp_none_defaults_teplo(self):
        from services.outfit_builder import build_outfit_slots
        outfit = {}
        # Default temp=15 → regime "тепло" → SEASON_SLOT_TYPES["outerwear"]["тепло"] = "лёгкую ветровку"
        # → placeholder IS added; footwear always present
        slots = build_outfit_slots(outfit, temp=None)
        slot_names = [s["slot"] for s in slots]
        assert "footwear" in slot_names
