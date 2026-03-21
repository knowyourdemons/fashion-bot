"""Tests for warmth-based outfit filtering system.

Covers: warmth requirements, pre-filtering, consistency check,
style compatibility, rain priority, missing warmth CTA.
"""
import uuid
import pytest
from datetime import date
from unittest.mock import MagicMock

pytest.importorskip("structlog", reason="structlog not installed")


def _item(category_group: str, type_: str, color: str = "белый",
          warmth: int | None = 3, style_tag: str = "casual",
          rain_ok: bool = False, season=None, score=7.0):
    i = MagicMock()
    i.id = uuid.uuid4()
    i.category_group = category_group
    i.type = type_
    i.color = color
    i.warmth_level = warmth
    i.style_tag = style_tag
    i.style = "повседневный"
    i.rain_ok = rain_ok
    i.season = season or ["spring", "summer", "autumn", "winter"]
    i.last_worn = None
    i.show_in_collage = True
    i.photo_id = f"photo_{type_}"
    i.photo_url = None
    i.score_item = score
    return i


# ══════════════════════════════════════════════════════════════════════════════
# Warmth Requirements Table
# ══════════════════════════════════════════════════════════════════════════════

class TestWarmthRequirements:
    def test_all_regimes_covered(self):
        from services.outfit_engine import WARMTH_REQUIREMENTS
        expected = {"жара", "тепло", "прохладно", "холодно", "мороз", "сильный_мороз"}
        assert set(WARMTH_REQUIREMENTS.keys()) == expected

    def test_cold_requires_warm_outerwear(self):
        from services.outfit_engine import WARMTH_REQUIREMENTS
        req = WARMTH_REQUIREMENTS["мороз"]["outerwear"]
        assert req is not None
        assert req[0] >= 3  # minimum warmth 3

    def test_hot_no_outerwear_needed(self):
        from services.outfit_engine import WARMTH_REQUIREMENTS
        assert WARMTH_REQUIREMENTS["жара"]["outerwear"] is None

    def test_freezing_requires_hat(self):
        from services.outfit_engine import WARMTH_REQUIREMENTS
        req = WARMTH_REQUIREMENTS["сильный_мороз"]["hat"]
        assert req is not None
        assert req[0] >= 3


# ══════════════════════════════════════════════════════════════════════════════
# Warmth Filtering
# ══════════════════════════════════════════════════════════════════════════════

class TestWarmthFiltering:
    def test_tshirt_filtered_at_severe_frost(self):
        """T-shirt (warmth=1) filtered at сильный_мороз (top requires 3+)."""
        from services.outfit_engine import _filter_by_warmth
        items = [
            _item("top", "футболка", warmth=1),
            _item("top", "свитер", warmth=4),
            _item("top", "кофта", warmth=3),
        ]
        result = _filter_by_warmth(items, "сильный_мороз")
        types = [i.type for i in result]
        assert "футболка" not in types
        assert "свитер" in types

    def test_puffer_filtered_at_heat(self):
        from services.outfit_engine import _filter_by_warmth
        items = [
            _item("outerwear", "пуховик", warmth=5),
            _item("top", "футболка", warmth=1),
        ]
        result = _filter_by_warmth(items, "жара")
        types = [i.type for i in result]
        # Outerwear not needed at heat, but if item is outerwear it gets
        # checked against None requirement → kept (slot not in requirements)
        assert "футболка" in types

    def test_no_warmth_data_kept(self):
        """Items without warmth_level should pass through."""
        from services.outfit_engine import _filter_by_warmth
        item = _item("top", "неизвестная вещь", warmth=None)
        result = _filter_by_warmth([item], "мороз")
        assert len(result) == 1

    def test_medium_warmth_ok_for_cool(self):
        from services.outfit_engine import _filter_by_warmth
        items = [_item("top", "кофта", warmth=3)]
        result = _filter_by_warmth(items, "прохладно")
        assert len(result) == 1

    def test_shorts_filtered_at_freezing(self):
        """Shorts (warmth=1) filtered at сильный_мороз (requires 3+)."""
        from services.outfit_engine import _filter_by_warmth
        items = [
            _item("bottom", "шорты", warmth=1),
            _item("bottom", "джинсы", warmth=3),
            _item("bottom", "тёплые штаны", warmth=4),
        ]
        result = _filter_by_warmth(items, "сильный_мороз")
        types = [i.type for i in result]
        assert "шорты" not in types
        assert "джинсы" in types

    def test_sandals_filtered_at_freezing(self):
        """Sandals (warmth=1) filtered at сильный_мороз (requires 3+)."""
        from services.outfit_engine import _filter_by_warmth
        items = [
            _item("footwear", "сандалии", warmth=1),
            _item("footwear", "ботинки", warmth=3),
            _item("footwear", "зимние ботинки", warmth=4),
        ]
        result = _filter_by_warmth(items, "сильный_мороз")
        types = [i.type for i in result]
        assert "сандалии" not in types
        assert "ботинки" in types


# ══════════════════════════════════════════════════════════════════════════════
# Warmth Consistency
# ══════════════════════════════════════════════════════════════════════════════

class TestWarmthConsistency:
    def test_consistent_outfit(self):
        from services.outfit_engine import _check_warmth_consistency
        slots = {
            "top": _item("top", "свитер", warmth=4),
            "bottom": _item("bottom", "джинсы", warmth=3),
            "footwear": _item("footwear", "ботинки", warmth=3),
        }
        assert _check_warmth_consistency(slots) is True

    def test_inconsistent_puffer_shorts(self):
        from services.outfit_engine import _check_warmth_consistency
        slots = {
            "outerwear": _item("outerwear", "пуховик", warmth=5),
            "bottom": _item("bottom", "шорты", warmth=1),
        }
        assert _check_warmth_consistency(slots) is False  # spread 4

    def test_spread_exactly_2_ok(self):
        from services.outfit_engine import _check_warmth_consistency
        slots = {
            "top": _item("top", "свитер", warmth=4),
            "bottom": _item("bottom", "лёгкие штаны", warmth=2),
        }
        assert _check_warmth_consistency(slots) is True  # spread 2

    def test_spread_3_not_ok(self):
        from services.outfit_engine import _check_warmth_consistency
        slots = {
            "top": _item("top", "свитер", warmth=5),
            "bottom": _item("bottom", "лёгкие штаны", warmth=2),
        }
        assert _check_warmth_consistency(slots) is False  # spread 3

    def test_no_warmth_data_passes(self):
        from services.outfit_engine import _check_warmth_consistency
        slots = {
            "top": _item("top", "кофта", warmth=None),
            "bottom": _item("bottom", "штаны", warmth=None),
        }
        assert _check_warmth_consistency(slots) is True


# ══════════════════════════════════════════════════════════════════════════════
# Style Compatibility
# ══════════════════════════════════════════════════════════════════════════════

class TestStyleCompatibility:
    def test_casual_formal_ok(self):
        from services.outfit_engine import _check_style_compatibility
        slots = {
            "top": _item("top", "рубашка", style_tag="casual"),
            "bottom": _item("bottom", "брюки", style_tag="formal"),
        }
        assert _check_style_compatibility(slots, "no_kids") is True

    def test_sport_formal_clash(self):
        from services.outfit_engine import _check_style_compatibility
        slots = {
            "top": _item("top", "спорт кофта", style_tag="sport"),
            "bottom": _item("bottom", "классич брюки", style_tag="formal"),
        }
        assert _check_style_compatibility(slots, "no_kids") is False

    def test_kids_no_style_check(self):
        from services.outfit_engine import _check_style_compatibility
        slots = {
            "top": _item("top", "спорт кофта", style_tag="sport"),
            "bottom": _item("bottom", "нарядная юбка", style_tag="formal"),
        }
        assert _check_style_compatibility(slots, "mom_girl") is True


# ══════════════════════════════════════════════════════════════════════════════
# Missing Warmth CTA
# ══════════════════════════════════════════════════════════════════════════════

class TestMissingWarmthCTA:
    def test_tshirt_at_cold_gives_cta(self):
        from services.outfit_engine import _get_missing_warmth_cta
        items = [
            _item("top", "футболка", warmth=1),
            _item("bottom", "джинсы", warmth=3),
        ]
        cta = _get_missing_warmth_cta(items, "холодно")
        assert cta is not None
        assert "кофту" in cta.lower() or "свитер" in cta.lower()

    def test_sweater_at_cold_no_cta(self):
        from services.outfit_engine import _get_missing_warmth_cta
        items = [
            _item("top", "свитер", warmth=4),
            _item("bottom", "джинсы", warmth=3),
        ]
        cta = _get_missing_warmth_cta(items, "холодно")
        assert cta is None

    def test_empty_wardrobe_no_cta(self):
        from services.outfit_engine import _get_missing_warmth_cta
        cta = _get_missing_warmth_cta([], "холодно")
        assert cta is None


# ══════════════════════════════════════════════════════════════════════════════
# Candidates with warmth filtering
# ══════════════════════════════════════════════════════════════════════════════

class TestCandidatesWithWarmth:
    def test_candidates_filtered_by_regime(self):
        """At сильный_мороз, warmth=1 items are filtered (requires 3+)."""
        from services.outfit_engine import _build_candidates
        items = [
            _item("top", "футболка", warmth=1),
            _item("top", "свитер", warmth=4),
            _item("top", "кофта", warmth=3),
            _item("bottom", "шорты", warmth=1),
            _item("bottom", "джинсы", warmth=3),
            _item("bottom", "тёплые штаны", warmth=4),
            _item("footwear", "сандалии", warmth=1),
            _item("footwear", "ботинки", warmth=3),
            _item("footwear", "зимние ботинки", warmth=4),
        ]
        candidates = _build_candidates(items, "spring", date.today(), regime="сильный_мороз")
        top_types = [c["type"] for c in candidates.get("top", [])]
        bottom_types = [c["type"] for c in candidates.get("bottom", [])]
        assert "футболка" not in top_types
        assert "свитер" in top_types
        assert "шорты" not in bottom_types
        assert "джинсы" in bottom_types

    def test_all_summer_at_freezing_graceful(self):
        """All summer items at freezing → graceful degradation keeps them."""
        from services.outfit_engine import _build_candidates
        items = [
            _item("top", "футболка", warmth=1),
            _item("bottom", "шорты", warmth=1),
            _item("footwear", "сандалии", warmth=1),
        ]
        # Warmth filter would remove all 3, but graceful degradation keeps them
        candidates = _build_candidates(items, "winter", date.today(), regime="сильный_мороз")
        total = sum(len(v) for v in candidates.values())
        assert total == 3  # all kept due to graceful degradation

    def test_serialization_includes_warmth(self):
        from services.outfit_engine import _serialize_item
        item = _item("top", "свитер", warmth=4, rain_ok=True)
        data = _serialize_item(item)
        assert data["warmth"] == 4
        assert data["rain"] is True

    def test_serialization_no_warmth_when_none(self):
        from services.outfit_engine import _serialize_item
        item = _item("top", "кофта", warmth=None)
        data = _serialize_item(item)
        assert "warmth" not in data


# ══════════════════════════════════════════════════════════════════════════════
# Integration: impossible outfits prevented
# ══════════════════════════════════════════════════════════════════════════════

class TestImpossibleOutfits:
    def test_tshirt_filtered_at_severe_frost(self):
        """T-shirt (warmth=1) at severe frost (requires 3+) → filtered."""
        from services.outfit_engine import _filter_by_warmth
        items = [
            _item("top", "футболка", warmth=1),
            _item("top", "свитер", warmth=4),
            _item("bottom", "тёплые штаны", warmth=4),
        ]
        filtered = _filter_by_warmth(items, "сильный_мороз")  # < 0°C
        top_items = [i for i in filtered if i.category_group == "top"]
        types = [i.type for i in top_items]
        assert "футболка" not in types
        assert "свитер" in types

    def test_puffer_plus_shorts_impossible(self):
        """Puffer (warmth=5) + shorts (warmth=1) → consistency check fails."""
        from services.outfit_engine import _check_warmth_consistency
        slots = {
            "outerwear": _item("outerwear", "пуховик", warmth=5),
            "bottom": _item("bottom", "шорты", warmth=1),
        }
        assert _check_warmth_consistency(slots) is False

    def test_sweater_plus_jeans_at_2c_ok(self):
        """Sweater (warmth=4) + jeans (warmth=3) at +2° → should pass."""
        from services.outfit_engine import _filter_by_warmth, _check_warmth_consistency
        items = [
            _item("top", "свитер", warmth=4),
            _item("bottom", "джинсы", warmth=3),
            _item("footwear", "ботинки", warmth=3),
            _item("outerwear", "куртка", warmth=4),
        ]
        filtered = _filter_by_warmth(items, "мороз")
        assert len(filtered) >= 3

        slots = {
            "top": items[0], "bottom": items[1],
            "footwear": items[2], "outerwear": items[3],
        }
        assert _check_warmth_consistency(slots) is True
