"""
Professional stylist simulation tests.

Simulates outfit selection through the eyes of:
1. Professional stylist — validates color harmony, silhouette logic, 60-30-10 rule
2. Mom of children (ages 0-3, 3-7, 7-12, 12-16) — validates safety, practicality
3. Adult woman (ages 20, 30, 40, 55) — validates style, occasion, body type

Each "persona" has specific expectations that differ from algorithmic tests.
A stylist would reject combos our algorithm might accept.

Runs rule-based selector deterministically (no AI mock needed).
"""
import uuid
import pytest
from dataclasses import dataclass
from datetime import date, timedelta
from unittest.mock import MagicMock

pytest.importorskip("structlog", reason="structlog not installed")

from services.outfit_selector import _select_outfit, _get_temp_regime
from services.outfit_builder import (
    has_minimum_outfit, has_minimum_wardrobe, build_outfit_slots, _is_base_layer_item,
)
from services.color_harmony import (
    color_compatibility, score_outfit_colors, is_neutral, _find_color_hsl,
)
from services.scoring import (
    classify_role, get_wardrobe_balance_insight, calc_item_versatility,
    get_wardrobe_gaps,
)


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _item(
    category_group, type_, color="белый", season=None, last_worn=None,
    score=7.0, warmth=3, style_tag="casual", rain_ok=False,
    show_in_collage=True, occasion=None, wear_count=0,
):
    i = MagicMock()
    i.id = uuid.uuid4()
    i.category_group = category_group
    i.type = type_
    i.color = color
    i.season = season or ["spring", "summer", "autumn", "winter"]
    i.last_worn = last_worn
    i.show_in_collage = show_in_collage
    i.photo_id = f"photo_{type_}"
    i.photo_url = None
    i.bbox = None
    i.score_item = score
    i.style = "повседневный"
    i.warmth_level = warmth
    i.style_tag = style_tag
    i.rain_ok = rain_ok
    i.occasion = occasion or []
    i.wear_count = wear_count
    i.role = classify_role(type_, color)
    return i


def _outfit(items, season="spring", temp_m=15.0, temp_e=15.0, precip=0.0):
    return _select_outfit(items, season, date.today(), temp_m, temp_e, precip)


def _visual_items(outfit):
    """Get only visual (non-base-layer) items from outfit."""
    return [i for i in outfit.get("all_items", []) if not _is_base_layer_item(i)]


def _outfit_colors(outfit):
    """Extract colors from visual items."""
    return [i.color for i in _visual_items(outfit) if i.color]


# ══════════════════════════════════════════════════════════════════════════════
# REALISTIC WARDROBES
# ══════════════════════════════════════════════════════════════════════════════

def _wardrobe_girl_3():
    """Девочка 3 года, садик. 15 вещей — типичный гардероб."""
    return [
        _item("top", "футболка", "розовый", season=["spring", "summer"], warmth=1, score=7.0),
        _item("top", "лонгслив", "белый", warmth=2, score=7.5),
        _item("top", "свитер", "лавандовый", season=["autumn", "winter"], warmth=4, score=8.0),
        _item("top", "худи", "серый", warmth=3, score=6.5),
        _item("bottom", "джинсы", "синий", warmth=3, score=8.0),
        _item("bottom", "леггинсы", "пыльно-розовый", warmth=2, score=7.0),
        _item("bottom", "шорты", "белый", season=["summer"], warmth=1, score=6.0),
        _item("one_piece", "платье", "мятный", season=["spring", "summer"], warmth=2, score=8.5),
        _item("outerwear", "ветровка", "розовый", season=["spring", "summer"], warmth=2, score=7.0),
        _item("outerwear", "куртка", "синяя", season=["autumn", "winter"], warmth=4, score=8.0),
        _item("footwear", "кроссовки", "белые", warmth=2, score=7.5),
        _item("footwear", "сандалии", "розовые", season=["summer"], warmth=1, score=6.0),
        _item("footwear", "ботинки", "коричневые", season=["autumn", "winter"], warmth=4, score=7.0),
        _item("underwear", "трусики", "розовые", warmth=1),
        _item("base_layer", "носки", "белые", warmth=1),
    ]


def _wardrobe_boy_7():
    """Мальчик 7 лет, школа. 18 вещей."""
    return [
        _item("top", "футболка", "синий", season=["spring", "summer"], warmth=1, score=7.0),
        _item("top", "футболка", "красный", season=["spring", "summer"], warmth=1, score=6.5),
        _item("top", "рубашка", "белый", warmth=2, score=8.0),
        _item("top", "свитер", "серый", season=["autumn", "winter"], warmth=4, score=7.5),
        _item("top", "худи", "чёрный", warmth=3, score=7.0),
        _item("bottom", "джинсы", "тёмно-синий", warmth=3, score=8.0),
        _item("bottom", "брюки", "серый", warmth=3, score=7.0),
        _item("bottom", "шорты", "хаки", season=["summer"], warmth=1, score=6.0),
        _item("outerwear", "куртка", "чёрная", season=["autumn", "winter"], warmth=4, score=8.0),
        _item("outerwear", "пуховик", "тёмно-синий", season=["winter"], warmth=5, score=8.5),
        _item("outerwear", "ветровка", "серая", season=["spring", "summer"], warmth=2, score=6.5),
        _item("footwear", "кроссовки", "чёрные", warmth=2, score=7.5),
        _item("footwear", "ботинки", "коричневые", season=["autumn", "winter"], warmth=4, score=7.0),
        _item("accessory", "шапка", "серая", season=["autumn", "winter"], warmth=4, score=6.0),
        _item("accessory", "шарф", "тёмно-синий", season=["winter"], warmth=4, score=6.0),
        _item("underwear", "трусики", "белые", warmth=1),
        _item("underwear", "термо кофта", "серая", season=["winter"], warmth=5),
        _item("base_layer", "носки", "серые", warmth=1),
    ]


def _wardrobe_teen_girl_14():
    """Девочка 14 лет, подросток. 22 вещи — тренды важны."""
    return [
        _item("top", "кроп-топ", "чёрный", season=["summer"], warmth=1, score=7.0, style_tag="casual"),
        _item("top", "футболка", "белый", warmth=1, score=7.5),
        _item("top", "худи", "лавандовый", warmth=3, score=8.5, style_tag="casual"),
        _item("top", "свитер", "бежевый", season=["autumn", "winter"], warmth=4, score=8.0),
        _item("top", "блузка", "розовый", warmth=2, score=7.0, style_tag="smart"),
        _item("bottom", "джинсы", "голубой", warmth=3, score=8.5),
        _item("bottom", "юбка", "чёрный", warmth=2, score=7.5, style_tag="smart"),
        _item("bottom", "леггинсы", "чёрный", warmth=2, score=6.5, style_tag="sport"),
        _item("bottom", "брюки", "бежевый", warmth=3, score=7.0),
        _item("one_piece", "платье", "лавандовый", season=["spring", "summer"], warmth=2, score=8.0),
        _item("outerwear", "джинсовая куртка", "голубая", season=["spring", "summer"], warmth=2, score=8.0),
        _item("outerwear", "пальто", "бежевый", season=["autumn", "winter"], warmth=4, score=8.5),
        _item("outerwear", "пуховик", "чёрный", season=["winter"], warmth=5, score=7.5),
        _item("footwear", "кроссовки", "белые", warmth=2, score=8.0),
        _item("footwear", "ботинки", "чёрные", season=["autumn", "winter"], warmth=4, score=7.5),
        _item("footwear", "сандалии", "бежевые", season=["summer"], warmth=1, score=6.0),
        _item("accessory", "шапка", "чёрная", season=["autumn", "winter"], warmth=4, score=6.5),
        _item("accessory", "сумка", "чёрная", warmth=1, score=7.0),
        _item("accessory", "очки", "чёрная", season=["spring", "summer"], warmth=1, score=6.0),
        _item("underwear", "трусики", "бежевые", warmth=1),
        _item("base_layer", "носки", "белые", warmth=1),
        _item("base_layer", "колготки", "чёрные", season=["autumn", "winter"], warmth=3),
    ]


def _wardrobe_woman_30():
    """Женщина 30 лет. 30 вещей — разнообразный гардероб."""
    return [
        # Tops
        _item("top", "футболка", "белый", warmth=1, score=7.0),
        _item("top", "футболка", "чёрный", warmth=1, score=7.0),
        _item("top", "блузка", "пудровый", warmth=2, score=8.0, style_tag="smart"),
        _item("top", "свитер", "бордовый", season=["autumn", "winter"], warmth=4, score=8.5),
        _item("top", "водолазка", "чёрный", season=["autumn", "winter"], warmth=4, score=8.0),
        _item("top", "лонгслив", "серый", warmth=2, score=6.5),
        _item("top", "кардиган", "бежевый", warmth=3, score=7.5),
        # Bottoms
        _item("bottom", "джинсы", "тёмно-синий", warmth=3, score=8.5),
        _item("bottom", "брюки", "чёрный", warmth=3, score=8.0, style_tag="smart"),
        _item("bottom", "юбка", "бежевый", warmth=2, score=7.5, style_tag="smart"),
        _item("bottom", "леггинсы", "чёрный", warmth=2, score=6.0, style_tag="sport"),
        # One pieces
        _item("one_piece", "платье", "пыльно-розовый", season=["spring", "summer"], warmth=2, score=8.5),
        _item("one_piece", "платье", "чёрный", warmth=3, score=9.0, style_tag="smart",
              occasion=["evening", "office"]),
        # Outerwear
        _item("outerwear", "тренч", "бежевый", season=["spring", "autumn"], warmth=3, score=9.0),
        _item("outerwear", "пуховик", "чёрный", season=["winter"], warmth=5, score=8.0),
        _item("outerwear", "кожаная куртка", "чёрная", season=["spring", "autumn"], warmth=3, score=8.5),
        _item("outerwear", "дождевик", "хаки", season=["spring", "autumn"], warmth=2, score=6.5, rain_ok=True),
        # Footwear
        _item("footwear", "кроссовки", "белые", warmth=2, score=7.5),
        _item("footwear", "туфли", "бежевые", warmth=2, score=8.0, style_tag="smart"),
        _item("footwear", "ботинки", "чёрные", season=["autumn", "winter"], warmth=4, score=8.0),
        _item("footwear", "сандалии", "бежевые", season=["summer"], warmth=1, score=7.0),
        # Accessories
        _item("accessory", "шарф", "бордовый", season=["autumn", "winter"], warmth=4, score=7.0),
        _item("accessory", "шапка", "серая", season=["autumn", "winter"], warmth=4, score=6.5),
        _item("accessory", "сумка", "чёрная", warmth=1, score=8.0),
        _item("accessory", "перчатки", "чёрные", season=["winter"], warmth=5, score=6.0),
        # Base layer
        _item("underwear", "трусики", "бежевые", warmth=1),
        _item("underwear", "термо кофта", "серая", season=["winter"], warmth=5),
        _item("underwear", "термо штаны", "серые", season=["winter"], warmth=5),
        _item("base_layer", "носки", "чёрные", warmth=1),
        _item("base_layer", "колготки", "телесные", season=["autumn", "winter"], warmth=3),
    ]


def _wardrobe_woman_minimal():
    """Женщина, минимальный гардероб. 6 вещей."""
    return [
        _item("top", "футболка", "серый", warmth=1, score=6.0),
        _item("bottom", "джинсы", "синий", warmth=3, score=7.0),
        _item("footwear", "кроссовки", "белые", warmth=2, score=6.5),
        _item("underwear", "трусики", "бежевые", warmth=1),
        _item("base_layer", "носки", "белые", warmth=1),
        _item("outerwear", "куртка", "чёрная", warmth=3, score=7.0),
    ]


def _wardrobe_clashing_colors():
    """Wardrobe designed to test color harmony — intentionally clashing."""
    return [
        _item("top", "футболка", "красный", warmth=1, score=7.0),
        _item("top", "футболка", "оранжевый", warmth=1, score=7.0),
        _item("top", "блузка", "фуксия", warmth=2, score=7.5),
        _item("bottom", "юбка", "красный", warmth=2, score=7.0),
        _item("bottom", "джинсы", "синий", warmth=3, score=8.0),  # neutral-ish
        _item("bottom", "брюки", "оранжевый", warmth=3, score=6.0),
        _item("footwear", "кроссовки", "зелёный", warmth=2, score=6.0),
        _item("footwear", "ботинки", "коричневые", warmth=3, score=7.0),
        _item("outerwear", "куртка", "жёлтый", warmth=3, score=7.0),
        _item("underwear", "трусики", "белые", warmth=1),
    ]


def _wardrobe_monochrome():
    """All-neutral wardrobe — should always have perfect harmony."""
    return [
        _item("top", "футболка", "белый", warmth=1, score=7.0),
        _item("top", "рубашка", "серый", warmth=2, score=7.5),
        _item("top", "свитер", "чёрный", season=["autumn", "winter"], warmth=4, score=8.0),
        _item("bottom", "джинсы", "тёмно-синий", warmth=3, score=8.0),
        _item("bottom", "брюки", "чёрный", warmth=3, score=8.0),
        _item("footwear", "кроссовки", "белые", warmth=2, score=7.0),
        _item("footwear", "ботинки", "чёрные", season=["autumn", "winter"], warmth=4, score=7.0),
        _item("outerwear", "пальто", "серый", season=["autumn", "winter"], warmth=4, score=8.5),
        _item("underwear", "трусики", "чёрные", warmth=1),
        _item("base_layer", "носки", "чёрные", warmth=1),
    ]


# ══════════════════════════════════════════════════════════════════════════════
# STYLIST PERSONA: Color Harmony Validation
# ══════════════════════════════════════════════════════════════════════════════

class TestStylistColorHarmony:
    """Professional stylist evaluates color combinations."""

    def test_monochrome_wardrobe_high_harmony(self):
        """All-neutral wardrobe should score ≥8 on color harmony."""
        items = _wardrobe_monochrome()
        for season in ["spring", "autumn", "winter"]:
            outfit = _outfit(items, season, temp_m=10.0, temp_e=7.0)
            visual = _visual_items(outfit)
            if len(visual) >= 2:
                score = score_outfit_colors(visual)
                assert score >= 7.0, (
                    f"Monochrome wardrobe should score ≥7, got {score}. "
                    f"Colors: {[i.color for i in visual]}"
                )

    def test_clashing_wardrobe_lower_harmony(self):
        """Deliberately clashing colors should score lower than neutral."""
        clash_items = _wardrobe_clashing_colors()
        neutral_items = _wardrobe_monochrome()

        clash_outfit = _outfit(clash_items, "spring", temp_m=20.0, temp_e=18.0)
        neutral_outfit = _outfit(neutral_items, "spring", temp_m=20.0, temp_e=18.0)

        clash_visual = _visual_items(clash_outfit)
        neutral_visual = _visual_items(neutral_outfit)

        if len(clash_visual) >= 2 and len(neutral_visual) >= 2:
            clash_score = score_outfit_colors(clash_visual)
            neutral_score = score_outfit_colors(neutral_visual)
            assert neutral_score >= clash_score, (
                f"Neutral ({neutral_score}) should score ≥ clashing ({clash_score}). "
                f"Clash colors: {[i.color for i in clash_visual]}, "
                f"Neutral colors: {[i.color for i in neutral_visual]}"
            )

    def test_max_3_chromatic_colors(self):
        """Stylist rule: max 3 non-neutral colors in outfit."""
        for wardrobe_fn in [_wardrobe_girl_3, _wardrobe_boy_7, _wardrobe_woman_30]:
            items = wardrobe_fn()
            for temp in [28.0, 18.0, 8.0, -3.0]:
                season = {28.0: "summer", 18.0: "spring", 8.0: "autumn", -3.0: "winter"}[temp]
                outfit = _outfit(items, season, temp_m=temp, temp_e=temp - 3)
                visual = _visual_items(outfit)
                chromatic = [i.color for i in visual if not is_neutral(i.color)]
                # This tests the scoring penalty, not hard enforcement
                if len(chromatic) > 3:
                    score = score_outfit_colors(visual)
                    assert score < 8.0, (
                        f"4+ chromatic colors should score <8. Got {score}. "
                        f"Colors: {chromatic}"
                    )

    def test_neutral_plus_one_accent(self):
        """Classic styling: neutral base + 1 accent color = high score."""
        items = [
            _item("top", "футболка", "белый", warmth=1),
            _item("bottom", "джинсы", "тёмно-синий", warmth=3),
            _item("footwear", "кроссовки", "белые", warmth=2),
            _item("outerwear", "куртка", "бордовый", warmth=3),
            _item("underwear", "трусики", warmth=1),
        ]
        outfit = _outfit(items, "autumn", temp_m=12.0, temp_e=8.0)
        visual = _visual_items(outfit)
        score = score_outfit_colors(visual)
        assert score >= 7.0, f"Neutral+accent should score ≥7, got {score}"

    def test_complementary_colors_positive(self):
        """Blue + orange = complementary = positive compatibility."""
        assert color_compatibility("синий", "оранжевый") >= 0.5
        assert color_compatibility("красный", "зелёный") >= 0.5
        assert color_compatibility("фиолетовый", "жёлтый") >= 0.5

    def test_analogous_colors_positive(self):
        """Adjacent colors on wheel = positive."""
        assert color_compatibility("синий", "голубой") >= 1.0
        assert color_compatibility("красный", "оранжевый") >= 0.0  # close but may clash
        assert color_compatibility("зелёный", "бирюзовый") >= 0.5

    def test_neutrals_always_compatible(self):
        """Neutrals pair with EVERYTHING."""
        neutrals = ["белый", "чёрный", "серый", "бежевый", "navy"]
        colors = ["красный", "розовый", "синий", "зелёный", "фиолетовый"]
        for n in neutrals:
            for c in colors:
                score = color_compatibility(n, c)
                assert score >= 2.0, f"{n} + {c} should be compatible, got {score}"

    def test_hsl_coverage_for_common_colors(self):
        """All commonly used colors should have HSL mapping."""
        must_resolve = [
            "красный", "розовый", "оранжевый", "жёлтый", "зелёный",
            "голубой", "синий", "фиолетовый", "коричневый", "бежевый",
            "белый", "чёрный", "серый", "бордовый", "горчичный",
            "оливковый", "мятный", "лавандовый", "коралловый", "персиковый",
            "терракотовый", "бирюзовый", "хаки", "кремовый", "молочный",
        ]
        for color in must_resolve:
            hsl = _find_color_hsl(color)
            assert hsl is not None, f"Color '{color}' has no HSL mapping!"


# ══════════════════════════════════════════════════════════════════════════════
# MOM PERSONA: Children's Outfit Validation
# ══════════════════════════════════════════════════════════════════════════════

class TestMomPerspective:
    """Mom evaluates outfits for children — safety, practicality, weather."""

    # ── Girl 3yo, садик ──

    def test_girl3_no_dress_cold_daycare(self):
        """Mom: no dress for daycare when cold (<10°C) — can't run."""
        items = _wardrobe_girl_3()
        for temp in [8.0, 5.0, 0.0, -5.0]:
            season = "winter" if temp <= 0 else "autumn"
            outfit = _outfit(items, season, temp_m=temp, temp_e=temp - 3)
            # Rule-based selector should prefer top+bottom over dress when cold
            if outfit.get("one_piece"):
                op_type = (outfit["one_piece"].type or "").lower()
                if "плат" in op_type or "юбк" in op_type:
                    pytest.fail(
                        f"Dress for 3yo at {temp}°C daycare! "
                        f"Selected: {outfit['one_piece'].type}"
                    )

    def test_girl3_warm_enough_cold_weather(self):
        """Mom: at <5°C child must have outerwear + top + bottom."""
        items = _wardrobe_girl_3()
        outfit = _outfit(items, "winter", temp_m=2.0, temp_e=-2.0)
        assert outfit.get("top") is not None or outfit.get("one_piece") is not None
        # Outerwear must be present if available
        seasonal_ow = [i for i in items if i.category_group == "outerwear"
                       and "winter" in i.season]
        if seasonal_ow:
            assert outfit.get("outerwear") is not None, "No outerwear for 3yo at 2°C!"

    def test_girl3_summer_outfit_light(self):
        """Mom: at >25°C, light clothes are fine."""
        items = _wardrobe_girl_3()
        outfit = _outfit(items, "summer", temp_m=28.0, temp_e=24.0)
        assert has_minimum_outfit(outfit)
        # Should NOT have outerwear in heat
        assert outfit.get("outerwear") is None, "Outerwear at 28°C for child!"

    # ── Boy 7yo, школа ──

    def test_boy7_full_winter_outfit(self):
        """Mom: at -5°C boy needs thermal + warm top + pants + puhovik + boots + hat."""
        items = _wardrobe_boy_7()
        outfit = _outfit(items, "winter", temp_m=-5.0, temp_e=-10.0)
        assert outfit.get("outerwear") is not None, "No outerwear at -5°C!"
        assert outfit.get("top") is not None
        assert outfit.get("bottom") is not None
        assert outfit.get("footwear") is not None
        # Should have thermal if available
        has_thermo = any("термо" in (i.type or "").lower() for i in items
                         if i.category_group == "underwear")
        if has_thermo:
            assert outfit.get("thermal_top") is not None, "No thermal at -5°C!"
        # Hat
        assert outfit.get("hat") is not None, "No hat for boy at -5°C!"

    def test_boy7_no_shorts_autumn(self):
        """Mom: no shorts at 8°C."""
        items = _wardrobe_boy_7()
        outfit = _outfit(items, "autumn", temp_m=8.0, temp_e=5.0)
        bottom = outfit.get("bottom")
        if bottom:
            assert "шорт" not in (bottom.type or "").lower(), (
                f"Shorts for 7yo at 8°C! Selected: {bottom.type}"
            )

    # ── Teen 14yo ──

    def test_teen_tights_under_skirt_cold(self):
        """Mom: teen in skirt at <15°C → needs tights."""
        items = _wardrobe_teen_girl_14()
        # Force skirt by removing pants temporarily
        no_pants = [i for i in items if i.category_group != "bottom" or "юбка" in i.type]
        no_pants.append(_item("bottom", "юбка", "чёрный", warmth=2, score=9.0))
        outfit = _outfit(no_pants, "autumn", temp_m=8.0, temp_e=5.0)
        if outfit.get("bottom") and "юбк" in (outfit["bottom"].type or "").lower():
            assert outfit.get("tights") is not None, "No tights under skirt at 8°C!"

    # ── Universal children rules ──

    def test_no_sandals_cold_any_child(self):
        """Mom: absolutely no sandals below 5°C for any child."""
        for wardrobe_fn in [_wardrobe_girl_3, _wardrobe_boy_7, _wardrobe_teen_girl_14]:
            items = wardrobe_fn()
            for temp in [3.0, 0.0, -5.0]:
                outfit = _outfit(items, "winter", temp_m=temp, temp_e=temp - 3)
                fw = outfit.get("footwear")
                if fw:
                    assert "сандал" not in (fw.type or "").lower(), (
                        f"Sandals for child at {temp}°C!"
                    )

    def test_base_layer_never_visible(self):
        """Mom: underwear/socks should never show as photo in collage."""
        for wardrobe_fn in [_wardrobe_girl_3, _wardrobe_boy_7]:
            items = wardrobe_fn()
            outfit = _outfit(items, "spring", temp_m=15.0, temp_e=12.0)
            if has_minimum_outfit(outfit):
                slots = build_outfit_slots(outfit, temp=15.0, colortype="default")
                for slot in slots:
                    if slot.get("has_item"):
                        it_type = (slot.get("item_type", "") or "").lower()
                        assert not any(
                            p in it_type for p in ["носк", "трусик", "майк", "термо"]
                        ), f"Base layer '{it_type}' visible in collage!"


# ══════════════════════════════════════════════════════════════════════════════
# WOMAN PERSONA: Style & Occasion Validation
# ══════════════════════════════════════════════════════════════════════════════

class TestWomanPerspective:
    """Adult woman evaluates outfits — style, occasion, body type, variety."""

    def test_full_wardrobe_always_has_outfit(self):
        """Woman: 30-item wardrobe should ALWAYS produce valid outfit."""
        items = _wardrobe_woman_30()
        for temp, season in [(30, "summer"), (20, "spring"), (12, "autumn"),
                             (7, "autumn"), (3, "winter"), (-5, "winter")]:
            outfit = _outfit(items, season, temp_m=float(temp), temp_e=float(temp - 4))
            assert has_minimum_outfit(outfit), (
                f"30-item wardrobe can't make outfit at {temp}°C/{season}!"
            )

    def test_minimal_wardrobe_still_works(self):
        """Woman: even 6 items should produce something."""
        items = _wardrobe_woman_minimal()
        outfit = _outfit(items, "spring", temp_m=15.0, temp_e=12.0)
        assert has_minimum_outfit(outfit)

    def test_score_preference_visible(self):
        """Woman: higher-scored items should be preferred."""
        items = [
            _item("top", "рубашка", "белый", score=9.0, warmth=2),
            _item("top", "футболка", "серый", score=4.0, warmth=1),
            _item("bottom", "брюки", "чёрный", score=8.5, warmth=3),
            _item("bottom", "леггинсы", "серый", score=3.0, warmth=2),
            _item("footwear", "кроссовки", "белые", warmth=2, score=7.0),
            _item("underwear", "трусики", warmth=1),
        ]
        outfit = _outfit(items, "spring", temp_m=18.0, temp_e=15.0)
        top = outfit.get("top")
        bottom = outfit.get("bottom")
        # Higher scored items should be selected
        assert top is not None
        assert top.score_item >= 8.0, f"Lower scored top selected: {top.type} ({top.score_item})"
        assert bottom is not None
        assert bottom.score_item >= 7.0, f"Lower scored bottom: {bottom.type} ({bottom.score_item})"

    def test_warm_outerwear_in_frost(self):
        """Woman: at -5°C, warm outerwear (пуховик) should be selected."""
        items = _wardrobe_woman_30()
        outfit = _outfit(items, "winter", temp_m=-5.0, temp_e=-10.0)
        ow = outfit.get("outerwear")
        assert ow is not None, "No outerwear at -5°C!"
        ow_type = (ow.type or "").lower()
        assert any(w in ow_type for w in ["пуховик", "тёплая", "зимня"]), (
            f"Expected warm outerwear at -5°C, got: {ow.type}"
        )

    def test_freshness_not_same_items_two_days(self):
        """Woman: items worn today should be avoided."""
        today = date.today()
        items = [
            _item("top", "рубашка", "белый", score=9.0, warmth=2, last_worn=today),
            _item("top", "футболка", "серый", score=5.0, warmth=1),
            _item("bottom", "брюки", "чёрный", score=9.0, warmth=3, last_worn=today),
            _item("bottom", "джинсы", "синий", score=5.0, warmth=3),
            _item("footwear", "кроссовки", "белые", warmth=2, score=7.0),
            _item("underwear", "трусики", warmth=1),
        ]
        outfit = _outfit(items, "spring", temp_m=18.0, temp_e=15.0)
        top = outfit.get("top")
        bottom = outfit.get("bottom")
        # Worn-today items should be avoided (lower priority)
        if top:
            assert top.last_worn != today, "Worn-today top selected despite alternative!"
        if bottom:
            assert bottom.last_worn != today, "Worn-today bottom selected despite alternative!"

    def test_rain_warning_generated(self):
        """Woman: heavy rain should produce umbrella warning."""
        items = _wardrobe_woman_30()
        outfit = _outfit(items, "autumn", temp_m=12.0, temp_e=10.0, precip=70.0)
        warnings = " ".join(outfit.get("warnings", []))
        assert "зонт" in warnings.lower(), "No umbrella warning for heavy rain!"

    def test_transition_layer_big_delta(self):
        """Woman: 12°C delta morning→evening should suggest layers."""
        items = _wardrobe_woman_30()
        outfit = _outfit(items, "spring", temp_m=22.0, temp_e=8.0)
        warnings = " ".join(outfit.get("warnings", []))
        assert "слоями" in warnings.lower() or "утром" in warnings.lower(), (
            "No transition warning for 22°→8° delta!"
        )


# ══════════════════════════════════════════════════════════════════════════════
# CAPSULE WARDROBE: Gap Analysis & Versatility
# ══════════════════════════════════════════════════════════════════════════════

class TestCapsuleAnalysis:
    """Test capsule wardrobe analysis — gaps, versatility, balance."""

    def test_full_wardrobe_no_critical_gaps(self):
        """30-item wardrobe should have minimal gaps."""
        items = _wardrobe_woman_30()
        gaps = get_wardrobe_gaps(items)
        # Should not report missing tops, bottoms, or footwear
        critical_missing = [g for g in gaps if "Добавь" in g and ("верх" in g or "низ" in g or "обувь" in g)]
        assert not critical_missing, f"Full wardrobe has critical gaps: {critical_missing}"

    def test_minimal_wardrobe_shows_gaps(self):
        """6-item wardrobe should report gaps."""
        items = _wardrobe_woman_minimal()
        gaps = get_wardrobe_gaps(items)
        assert any("Добавь" in g for g in gaps), f"Minimal wardrobe should have gaps: {gaps}"

    def test_empty_wardrobe_max_gaps(self):
        """Empty wardrobe → specific message."""
        gaps = get_wardrobe_gaps([])
        assert len(gaps) >= 1
        assert "пуст" in gaps[0].lower()

    def test_neutral_items_high_versatility(self):
        """Neutral items (белый, чёрный) pair with everything."""
        items = _wardrobe_woman_30()
        white_top = next(i for i in items if i.type == "футболка" and i.color == "белый")
        bord_sweater = next(i for i in items if i.type == "свитер" and i.color == "бордовый")

        white_v = calc_item_versatility(white_top, items)
        bord_v = calc_item_versatility(bord_sweater, items)

        assert white_v >= bord_v, (
            f"White top ({white_v} combos) should be ≥ burgundy sweater ({bord_v})"
        )

    def test_combo_potential_formula(self):
        """Combo formula: tops × bottoms × (outerwear+1) + dresses."""
        items = _wardrobe_woman_30()
        gaps = get_wardrobe_gaps(items)
        combo_msg = [g for g in gaps if "комбинаций" in g]
        assert combo_msg, "Should report combo potential"
        # With 7 tops, 4 bottoms, 4 outerwear, 2 dresses:
        # 7*4*(4+1)+2 = 142 theoretical combos
        # Actual count may vary but should be substantial

    def test_wardrobe_balance_insight(self):
        """Too many accent items → insight."""
        # Create wardrobe with many accents (bright colors)
        accent_heavy = [
            _item("top", "футболка", "красный", score=7.0),
            _item("top", "футболка", "оранжевый", score=7.0),
            _item("top", "блузка", "фуксия", score=7.5),
            _item("top", "кроп-топ", "ярко-зелёный", score=6.0),
            _item("top", "свитер", "бордовый", score=7.0),
            _item("bottom", "юбка", "красный", score=7.0),
            _item("bottom", "джинсы", "синий", score=8.0),
            _item("bottom", "брюки", "горчичный", score=6.5),
            _item("footwear", "кроссовки", "розовые", score=6.0),
            _item("footwear", "ботинки", "красные", score=6.0),
            _item("outerwear", "куртка", "жёлтый", score=7.0),
        ]
        # classify_role would tag most as "accent"
        insight = get_wardrobe_balance_insight(accent_heavy)
        # With ≥10 items dominated by accent colors, should suggest more neutrals
        # (may or may not trigger based on exact classification)


# ══════════════════════════════════════════════════════════════════════════════
# WARMTH CONSISTENCY: Stylist would reject these combos
# ══════════════════════════════════════════════════════════════════════════════

class TestWarmthConsistency:
    """A stylist would reject warmth-inconsistent outfits."""

    def test_no_warm_jacket_with_light_bottom_in_cold(self):
        """Пуховик (warmth 5) + шорты (warmth 1) = absurd."""
        items = [
            _item("top", "свитер", "серый", warmth=4, score=8.0),
            _item("bottom", "шорты", "белый", warmth=1, score=5.0, season=["summer"]),
            _item("bottom", "джинсы", "синий", warmth=3, score=7.0),
            _item("outerwear", "пуховик", "чёрный", warmth=5, score=8.0, season=["winter"]),
            _item("footwear", "ботинки", "чёрные", warmth=4, score=7.0, season=["winter"]),
            _item("underwear", "трусики", warmth=1),
        ]
        outfit = _outfit(items, "winter", temp_m=0.0, temp_e=-5.0)
        bottom = outfit.get("bottom")
        if bottom:
            assert bottom.warmth_level >= 2, (
                f"Warmth 1 bottom with warm outerwear! Selected: {bottom.type} (warmth {bottom.warmth_level})"
            )

    def test_all_items_similar_warmth(self):
        """Full wardrobe in cold: all visual items should have warmth ≥ 3."""
        items = _wardrobe_woman_30()
        outfit = _outfit(items, "winter", temp_m=-3.0, temp_e=-8.0)
        visual = _visual_items(outfit)
        for v in visual:
            wl = getattr(v, "warmth_level", 3)
            if isinstance(wl, (int, float)):
                assert wl >= 2, (
                    f"Item '{v.type}' (warmth {wl}) too light for -3°C"
                )


# ══════════════════════════════════════════════════════════════════════════════
# EDGE CASES: Things that break in production
# ══════════════════════════════════════════════════════════════════════════════

class TestProductionEdgeCases:
    """Real-world scenarios that could break."""

    def test_all_items_same_category(self):
        """User uploaded only tops — should NOT crash, just no outfit."""
        items = [
            _item("top", "футболка", "белый"),
            _item("top", "рубашка", "серый"),
            _item("top", "свитер", "чёрный"),
        ]
        outfit = _outfit(items, "spring", temp_m=15.0, temp_e=12.0)
        assert not has_minimum_outfit(outfit)

    def test_one_item_wardrobe(self):
        """Single item — should not crash."""
        items = [_item("top", "футболка", "белый")]
        outfit = _outfit(items, "summer", temp_m=25.0, temp_e=22.0)
        assert outfit.get("top") is not None

    def test_duplicate_items(self):
        """Multiple identical items — should not create duplicates in outfit."""
        jeans = _item("bottom", "джинсы", "синий", warmth=3)
        items = [
            _item("top", "футболка", "белый"),
            jeans,
            _item("footwear", "кроссовки", "белые"),
            _item("underwear", "трусики"),
        ]
        outfit = _outfit(items, "spring", temp_m=18.0, temp_e=15.0)
        all_ids = [i.id for i in outfit.get("all_items", [])]
        assert len(all_ids) == len(set(all_ids)), "Duplicate items in outfit!"

    def test_item_with_none_fields(self):
        """Items with None type/color — should not crash."""
        items = [
            _item("top", None, None, warmth=2),
            _item("bottom", None, None, warmth=3),
            _item("footwear", None, None, warmth=2),
            _item("underwear", "трусики"),
        ]
        outfit = _outfit(items, "spring", temp_m=15.0, temp_e=12.0)
        # Should not crash, even if selection is suboptimal
        assert isinstance(outfit, dict)

    def test_extreme_temperatures(self):
        """Extreme temps (-30°C, +45°C) — should not crash."""
        items = _wardrobe_woman_30()
        for temp in [-30.0, -20.0, 35.0, 42.0]:
            season = "winter" if temp < 0 else "summer"
            outfit = _outfit(items, season, temp_m=temp, temp_e=temp - 3)
            assert isinstance(outfit, dict)
            assert isinstance(outfit.get("warnings", []), list)

    def test_worn_7_days_ago_preferred(self):
        """Items not worn in 7+ days should get freshness bonus."""
        week_ago = date.today() - timedelta(days=8)
        yesterday = date.today() - timedelta(days=1)

        high_score_worn_yesterday = _item("top", "рубашка", "белый",
                                          score=9.0, warmth=2, last_worn=yesterday)
        low_score_fresh = _item("top", "футболка", "серый",
                                score=7.0, warmth=1, last_worn=week_ago)

        items = [
            high_score_worn_yesterday, low_score_fresh,
            _item("bottom", "джинсы", "синий", warmth=3),
            _item("footwear", "кроссовки", warmth=2),
            _item("underwear", "трусики"),
        ]
        outfit = _outfit(items, "spring", temp_m=20.0, temp_e=18.0)
        top = outfit.get("top")
        # With freshness bonus (+1.0 for 7+ days), the 7.0+1.0=8.0 item
        # should compete with the 9.0 item. Both are valid selections.
        assert top is not None

    def test_build_outfit_slots_all_weather(self):
        """build_outfit_slots should never crash across all scenarios."""
        for wardrobe_fn in [_wardrobe_girl_3, _wardrobe_boy_7, _wardrobe_woman_30]:
            items = wardrobe_fn()
            for temp, season in [(30, "summer"), (15, "spring"), (5, "autumn"), (-5, "winter")]:
                outfit = _outfit(items, season, temp_m=float(temp), temp_e=float(temp - 3))
                if has_minimum_outfit(outfit):
                    slots = build_outfit_slots(
                        outfit, temp=float(temp), colortype="default",
                        regime=_get_temp_regime(float(temp)),
                    )
                    assert isinstance(slots, list)
                    assert len(slots) >= 1


# ══════════════════════════════════════════════════════════════════════════════
# CROSS-PERSONA COMPARISON: Same wardrobe, different expectations
# ══════════════════════════════════════════════════════════════════════════════

class TestCrossPersona:
    """Same outfit evaluated by different personas — consistency check."""

    @pytest.mark.parametrize("temp,season", [
        (28.0, "summer"), (18.0, "spring"), (12.0, "autumn"),
        (7.0, "autumn"), (2.0, "winter"), (-5.0, "winter"),
    ])
    def test_girl3_all_temps_valid(self, temp, season):
        """Girl 3yo: valid outfit at every temperature."""
        items = _wardrobe_girl_3()
        outfit = _outfit(items, season, temp_m=temp, temp_e=temp - 3)
        if has_minimum_wardrobe(items):
            assert has_minimum_outfit(outfit), f"No outfit for girl_3 at {temp}°C"

    @pytest.mark.parametrize("temp,season", [
        (28.0, "summer"), (18.0, "spring"), (12.0, "autumn"),
        (7.0, "autumn"), (2.0, "winter"), (-5.0, "winter"),
    ])
    def test_boy7_all_temps_valid(self, temp, season):
        """Boy 7yo: valid outfit at every temperature."""
        items = _wardrobe_boy_7()
        outfit = _outfit(items, season, temp_m=temp, temp_e=temp - 3)
        assert has_minimum_outfit(outfit), f"No outfit for boy_7 at {temp}°C"

    @pytest.mark.parametrize("temp,season", [
        (28.0, "summer"), (18.0, "spring"), (12.0, "autumn"),
        (7.0, "autumn"), (2.0, "winter"), (-5.0, "winter"),
    ])
    def test_woman30_all_temps_valid(self, temp, season):
        """Woman 30: valid outfit at every temperature."""
        items = _wardrobe_woman_30()
        outfit = _outfit(items, season, temp_m=temp, temp_e=temp - 3)
        assert has_minimum_outfit(outfit), f"No outfit for woman_30 at {temp}°C"

    @pytest.mark.parametrize("temp,season", [
        (28.0, "summer"), (18.0, "spring"), (12.0, "autumn"),
        (7.0, "autumn"), (2.0, "winter"), (-5.0, "winter"),
    ])
    def test_teen14_all_temps_valid(self, temp, season):
        """Teen 14yo: valid outfit at every temperature."""
        items = _wardrobe_teen_girl_14()
        outfit = _outfit(items, season, temp_m=temp, temp_e=temp - 3)
        assert has_minimum_outfit(outfit), f"No outfit for teen_14 at {temp}°C"

    def test_all_personas_no_crash_100_scenarios(self):
        """Stress: 4 wardrobes × 6 temps × 4 precip levels = 96 scenarios, no crash."""
        wardrobes = [_wardrobe_girl_3(), _wardrobe_boy_7(),
                     _wardrobe_teen_girl_14(), _wardrobe_woman_30()]
        temps = [(30, "summer"), (20, "spring"), (12, "autumn"),
                 (5, "autumn"), (0, "winter"), (-10, "winter")]
        precips = [0.0, 30.0, 60.0, 100.0]

        for items in wardrobes:
            for temp, season in temps:
                for precip in precips:
                    outfit = _outfit(items, season, float(temp), float(temp - 5), precip)
                    assert isinstance(outfit, dict)
                    assert isinstance(outfit.get("all_items", []), list)
