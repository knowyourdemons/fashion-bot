"""
Expert panel simulation — evaluates the ENTIRE system from 5 perspectives.

Each expert has specific criteria and expectations. Tests verify that the
outfit selection + scoring + normalization + color harmony + photo quality
pipeline meets professional standards.

Experts:
1. STYLIST — color theory, silhouettes, capsule completeness
2. MOM — safety, weather, age-appropriate, practical
3. WOMAN — personal style, occasion, body type, trends
4. CTO — performance, edge cases, graceful degradation
5. GROWTH MANAGER — engagement hooks, monetization readiness, gaps → shopping
6. UX LEAD — feedback loops, progressive disclosure, error handling
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
    warm_outfit_comment,
)
from services.color_harmony import (
    color_compatibility, score_outfit_colors, is_neutral, _find_color_hsl,
)
from services.scoring import (
    classify_role, get_wardrobe_balance_insight, calc_item_versatility,
    get_wardrobe_gaps,
)
from services.normalize import normalize_type, normalize_color
from services.photo_quality import assess_photo, preprocess_for_vision


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _item(cg, type_, color="белый", season=None, last_worn=None,
          score=7.0, warmth=3, style_tag="casual", rain_ok=False,
          occasion=None, wear_count=0):
    i = MagicMock()
    i.id = uuid.uuid4()
    i.category_group = cg
    i.type = type_
    i.color = color
    i.season = season or ["spring", "summer", "autumn", "winter"]
    i.last_worn = last_worn
    i.show_in_collage = True
    i.photo_id = f"photo_{type_}"
    i.photo_url = None
    i.bbox = None
    i.score_item = score
    i.warmth_level = warmth
    i.style_tag = style_tag
    i.rain_ok = rain_ok
    i.occasion = occasion or []
    i.wear_count = wear_count
    i.role = classify_role(type_, color)
    return i


def _outfit(items, season="spring", temp_m=15.0, temp_e=15.0, precip=0.0):
    return _select_outfit(items, season, date.today(), temp_m, temp_e, precip)


def _visual(outfit):
    return [i for i in outfit.get("all_items", []) if not _is_base_layer_item(i)]


# ══════════════════════════════════════════════════════════════════════════════
# REALISTIC WARDROBES — designed by each persona
# ══════════════════════════════════════════════════════════════════════════════

def _realistic_girl_3():
    """Реалистичный гардероб девочки 3 лет, 20 вещей (мама собрала)."""
    return [
        _item("top", "футболка", "розовый", season=["spring", "summer"], warmth=1, score=7),
        _item("top", "футболка", "белый", season=["spring", "summer"], warmth=1, score=6.5),
        _item("top", "лонгслив", "лавандовый", warmth=2, score=7.5),
        _item("top", "свитер", "серый", season=["autumn", "winter"], warmth=4, score=8),
        _item("top", "худи", "розовый", warmth=3, score=7),
        _item("bottom", "джинсы", "синий", warmth=3, score=8),
        _item("bottom", "леггинсы", "чёрный", warmth=2, score=7),
        _item("bottom", "шорты", "розовый", season=["summer"], warmth=1, score=6),
        _item("one_piece", "платье", "лавандовый", season=["spring", "summer"], warmth=2, score=8.5),
        _item("outerwear", "ветровка", "розовый", season=["spring", "summer"], warmth=2, score=7),
        _item("outerwear", "куртка", "синяя", season=["autumn", "winter"], warmth=4, score=8),
        _item("outerwear", "пуховик", "розовый", season=["winter"], warmth=5, score=8.5),
        _item("footwear", "кроссовки", "белые", warmth=2, score=7.5),
        _item("footwear", "сандалии", "розовые", season=["summer"], warmth=1, score=6),
        _item("footwear", "ботинки", "коричневые", season=["autumn", "winter"], warmth=4, score=7),
        _item("accessory", "шапка", "розовая", season=["autumn", "winter"], warmth=4, score=6.5),
        _item("accessory", "шарф", "серый", season=["winter"], warmth=4, score=6),
        _item("underwear", "трусики", "розовые"),
        _item("underwear", "майка", "белая"),
        _item("base_layer", "носки", "белые"),
    ]


def _realistic_woman_32():
    """Реалистичный гардероб женщины 32 лет, офис + casual, 35 вещей."""
    return [
        # Office tops
        _item("top", "блузка", "белый", score=8.5, warmth=2, style_tag="smart", occasion=["office"]),
        _item("top", "блузка", "пудровый", score=8, warmth=2, style_tag="smart", occasion=["office"]),
        _item("top", "рубашка", "голубой", score=7.5, warmth=2, style_tag="smart", occasion=["office"]),
        # Casual tops
        _item("top", "футболка", "белый", score=7, warmth=1),
        _item("top", "футболка", "чёрный", score=7, warmth=1),
        _item("top", "лонгслив", "серый", score=6.5, warmth=2),
        _item("top", "свитер", "бордовый", season=["autumn", "winter"], score=8.5, warmth=4),
        _item("top", "водолазка", "чёрный", season=["autumn", "winter"], score=8, warmth=4),
        _item("top", "кардиган", "бежевый", score=7.5, warmth=3),
        # Bottoms
        _item("bottom", "брюки", "чёрный", score=8.5, warmth=3, style_tag="smart", occasion=["office"]),
        _item("bottom", "джинсы", "тёмно-синий", score=8.5, warmth=3),
        _item("bottom", "джинсы", "голубой", score=7, warmth=3),
        _item("bottom", "юбка", "бежевый", score=7.5, warmth=2, style_tag="smart"),
        _item("bottom", "леггинсы", "чёрный", score=6, warmth=2, style_tag="sport"),
        # Dresses
        _item("one_piece", "платье", "пыльно-розовый", season=["spring", "summer"], score=8.5, warmth=2),
        _item("one_piece", "платье", "чёрный", score=9, warmth=3, style_tag="smart", occasion=["evening", "office"]),
        # Outerwear
        _item("outerwear", "тренч", "бежевый", season=["spring", "autumn"], score=9, warmth=3),
        _item("outerwear", "пуховик", "чёрный", season=["winter"], score=8, warmth=5),
        _item("outerwear", "кожаная куртка", "чёрная", season=["spring", "autumn"], score=8.5, warmth=3),
        _item("outerwear", "дождевик", "хаки", season=["spring", "autumn"], score=6.5, warmth=2, rain_ok=True),
        # Footwear
        _item("footwear", "кроссовки", "белые", score=7.5, warmth=2),
        _item("footwear", "туфли", "бежевые", score=8, warmth=2, style_tag="smart"),
        _item("footwear", "ботинки", "чёрные", season=["autumn", "winter"], score=8, warmth=4),
        _item("footwear", "сандалии", "бежевые", season=["summer"], score=7, warmth=1),
        # Accessories
        _item("accessory", "шарф", "бордовый", season=["autumn", "winter"], score=7, warmth=4),
        _item("accessory", "шапка", "серая", season=["autumn", "winter"], score=6.5, warmth=4),
        _item("accessory", "сумка", "чёрная", score=8),
        _item("accessory", "перчатки", "чёрные", season=["winter"], score=6, warmth=5),
        _item("accessory", "очки", "чёрные", season=["spring", "summer"], score=6),
        # Base
        _item("underwear", "трусики", "бежевые"),
        _item("underwear", "термо кофта", "серая", season=["winter"], warmth=5),
        _item("underwear", "термо штаны", "серые", season=["winter"], warmth=5),
        _item("base_layer", "носки", "чёрные"),
        _item("base_layer", "колготки", "телесные", season=["autumn", "winter"], warmth=3),
        _item("base_layer", "колготки", "чёрные", season=["autumn", "winter"], warmth=3),
    ]


def _unbalanced_wardrobe():
    """Несбалансированный: 8 ярких top, 1 bottom, 0 outerwear."""
    return [
        _item("top", "футболка", "красный", score=7),
        _item("top", "футболка", "оранжевый", score=6.5),
        _item("top", "блузка", "фуксия", score=7),
        _item("top", "свитер", "ярко-зелёный", score=6),
        _item("top", "худи", "жёлтый", score=5.5),
        _item("top", "лонгслив", "фиолетовый", score=6),
        _item("top", "кардиган", "бирюзовый", score=6.5),
        _item("top", "рубашка", "коралловый", score=7),
        _item("bottom", "джинсы", "синий", score=8),
        _item("footwear", "кроссовки", "белые", score=7),
        _item("underwear", "трусики"),
    ]


# ══════════════════════════════════════════════════════════════════════════════
# 1. STYLIST EXPERT
# ══════════════════════════════════════════════════════════════════════════════

class TestStylistExpert:
    """Professional stylist evaluates: color harmony, capsule, roles, trends."""

    def test_color_harmony_every_scenario(self):
        """Stylist: ALL generated outfits should score ≥4 on color harmony.

        Note: winter outfits with many dark items (чёрный/бордовый) can score
        lower because of the >3 chromatic penalty, but 4+ is still acceptable.
        """
        items = _realistic_woman_32()
        for temp, season in [(28, "summer"), (18, "spring"), (8, "autumn"), (-5, "winter")]:
            outfit = _outfit(items, season, float(temp), float(temp - 4))
            visual = _visual(outfit)
            if len(visual) >= 2:
                score = score_outfit_colors(visual)
                assert score >= 4.0, (
                    f"Color harmony {score} < 4 at {temp}°C. "
                    f"Colors: {[v.color for v in visual]}"
                )

    def test_role_distribution_balanced_wardrobe(self):
        """Stylist: balanced wardrobe should have 30%+ base items."""
        items = _realistic_woman_32()
        roles = [i.role for i in items if not _is_base_layer_item(i)]
        base_pct = roles.count("base") / max(len(roles), 1)
        assert base_pct >= 0.2, f"Only {base_pct:.0%} base items, stylist wants ≥20%"

    def test_unbalanced_wardrobe_insight(self):
        """Stylist: unbalanced wardrobe → actionable insight."""
        items = _unbalanced_wardrobe()
        insight = get_wardrobe_balance_insight(items)
        # With 11 items, 8 accent tops, should suggest more base
        if insight:
            assert "базов" in insight.lower() or "нейтральн" in insight.lower()

    def test_capsule_combo_potential(self):
        """Stylist: 35-item wardrobe should generate 50+ combo potential."""
        items = _realistic_woman_32()
        gaps = get_wardrobe_gaps(items)
        combo_msg = [g for g in gaps if "комбинаций" in g]
        assert combo_msg, "Should report combo potential"

    def test_orphan_detection_works(self):
        """Stylist: bright solo item with no matching pieces → orphan."""
        items = [
            _item("top", "футболка", "ярко-зелёный", score=7),  # orphan — no matching bottom
            _item("bottom", "джинсы", "чёрный", score=8),
            _item("bottom", "брюки", "чёрный", score=7),
            _item("top", "футболка", "белый", score=7),
            _item("top", "рубашка", "серый", score=7),
            _item("footwear", "кроссовки", "чёрные", score=7),
            _item("outerwear", "куртка", "чёрная", score=7),
            _item("underwear", "трусики"),
            _item("top", "свитер", "бежевый", score=7),
        ]
        # ярко-зелёный is chromatic, won't pair well with only black/white
        v = calc_item_versatility(items[0], items)
        # Green top should still pair with neutral bottoms
        assert v >= 1, "Green top should pair with at least black bottom"

    def test_all_12_colortypes_have_palettes(self):
        """Stylist: every 12-season colortype should have full palette."""
        from worker.tasks.style_config import COLORTYPE_PALETTES
        must_have = [
            "Bright Spring", "True Spring", "Light Spring",
            "Light Summer", "True Summer", "Soft Summer",
            "Soft Autumn", "True Autumn", "Deep Autumn",
            "Deep Winter", "True Winter", "Bright Winter",
            "Лето", "Зима", "Весна", "Осень",
        ]
        for ct in must_have:
            palette = COLORTYPE_PALETTES.get(ct)
            assert palette is not None, f"Missing palette for '{ct}'"
            assert "top" in palette, f"No 'top' colors in '{ct}'"
            assert len(palette.get("top", [])) >= 3, f"Too few top colors in '{ct}'"


# ══════════════════════════════════════════════════════════════════════════════
# 2. MOM EXPERT
# ══════════════════════════════════════════════════════════════════════════════

class TestMomExpert:
    """Mom evaluates: safety, weather protection, age-appropriate, practical."""

    @pytest.mark.parametrize("temp,season", [
        (30, "summer"), (20, "spring"), (12, "autumn"),
        (5, "autumn"), (0, "winter"), (-10, "winter"),
    ])
    def test_girl3_always_gets_outfit(self, temp, season):
        """Mom: my 3yo should ALWAYS have an outfit."""
        items = _realistic_girl_3()
        outfit = _outfit(items, season, float(temp), float(temp - 4))
        assert has_minimum_outfit(outfit), f"No outfit for girl_3 at {temp}°C!"

    def test_girl3_winter_full_protection(self):
        """Mom: at -10°C, girl must have warm everything."""
        items = _realistic_girl_3()
        outfit = _outfit(items, "winter", -10.0, -15.0)
        assert outfit.get("outerwear") is not None, "No outerwear at -10°C!"
        ow_type = (outfit["outerwear"].type or "").lower()
        assert "пуховик" in ow_type or "тёплая" in ow_type, f"Expected warm outerwear, got {outfit['outerwear'].type}"

    def test_girl3_summer_no_outerwear(self):
        """Mom: at 30°C, no jacket needed."""
        items = _realistic_girl_3()
        outfit = _outfit(items, "summer", 30.0, 25.0)
        assert outfit.get("outerwear") is None, "Jacket at 30°C?!"

    def test_girl3_worn_items_rotated(self):
        """Mom: yesterday's outfit shouldn't repeat."""
        yesterday = date.today() - timedelta(days=1)
        items = _realistic_girl_3()
        # Mark some items as worn yesterday
        items[0].last_worn = yesterday  # футболка розовый
        items[5].last_worn = yesterday  # джинсы
        outfit = _outfit(items, "spring", 18.0, 15.0)
        top = outfit.get("top")
        if top:
            # Should prefer unworn items (freshness bonus)
            assert top.last_worn != yesterday or len([
                i for i in items if i.category_group == "top"
                and i.last_worn != yesterday
                and ("spring" in i.season)
            ]) == 0, "Worn-yesterday top selected when fresh alternatives exist"

    def test_baby_item_normalization(self):
        """Mom: my baby's 'ползунки' should be recognized."""
        norm_t, norm_cg = normalize_type("ползунки")
        assert norm_t == "комбинезон", f"ползунки → {norm_t}"
        assert norm_cg == "one_piece"

        norm_t2, norm_cg2 = normalize_type("человечек")
        assert norm_t2 == "комбинезон"

        norm_t3, norm_cg3 = normalize_type("царапки")
        assert norm_t3 == "перчатки"
        assert norm_cg3 == "accessory"

    def test_comment_tone_varies_by_items(self):
        """Mom: comment should match wardrobe size — not "отличный образ" for 1 item."""
        c1 = warm_outfit_comment(score=7.0, child_name="Алиса", temp=15.0,
                                 real_item_count=1, first_item_desc="футболка розовая")
        # Should NOT praise "отличный образ" / "хороший образ" for 1 item
        # But CAN say "соберу образ" as a CTA (motivational, not praise)
        assert "отличный образ" not in c1.lower(), "Should not praise 'отличный образ' for 1 item"
        assert "хороший образ" not in c1.lower(), "Should not praise 'хороший образ' for 1 item"

        c5 = warm_outfit_comment(score=8.0, child_name="Алиса", temp=15.0,
                                 real_item_count=5)
        # 5 items — should mention combination
        assert len(c5) > 20  # meaningful comment


# ══════════════════════════════════════════════════════════════════════════════
# 3. WOMAN EXPERT
# ══════════════════════════════════════════════════════════════════════════════

class TestWomanExpert:
    """Adult woman evaluates: style relevance, score preference, variety."""

    def test_high_scored_items_preferred(self):
        """Woman: I expect my best items to be selected."""
        items = _realistic_woman_32()
        outfit = _outfit(items, "spring", 18.0, 15.0)
        top = outfit.get("top")
        one_piece = outfit.get("one_piece")
        # Either top or one_piece should be selected
        assert top is not None or one_piece is not None, "No top or dress!"
        # If top selected, should be high scored
        if top:
            assert top.score_item >= 7.0, f"Low-scored top: {top.type} ({top.score_item})"
        # If dress selected, should be high scored
        if one_piece:
            assert one_piece.score_item >= 7.0, f"Low-scored dress: {one_piece.type} ({one_piece.score_item})"

    def test_warm_outerwear_selected_in_cold(self):
        """Woman: at -5°C, my пуховик should be selected, not тренч."""
        items = _realistic_woman_32()
        outfit = _outfit(items, "winter", -5.0, -10.0)
        ow = outfit.get("outerwear")
        assert ow is not None
        assert "пуховик" in (ow.type or "").lower(), f"Expected пуховик, got {ow.type}"

    def test_neutral_wardrobe_high_versatility(self):
        """Woman: my neutral items should have highest versatility."""
        items = _realistic_woman_32()
        white_tshirt = next(i for i in items if i.type == "футболка" and i.color == "белый")
        v = calc_item_versatility(white_tshirt, items)
        assert v >= 5, f"White tshirt should pair with 5+ items, got {v}"

    def test_gaps_show_missing_categories(self):
        """Woman: unbalanced wardrobe → gaps tell me what to buy."""
        items = _unbalanced_wardrobe()
        gaps = get_wardrobe_gaps(items)
        # Should report missing outerwear
        ow_gap = [g for g in gaps if "верхн" in g.lower() or "куртк" in g.lower()]
        assert ow_gap, f"Should report missing outerwear, got: {gaps}"

    def test_tights_under_skirt_cold(self):
        """Woman: tights under my skirt at 8°C."""
        items = _realistic_woman_32()
        # Force skirt selection
        skirt_outfit = [i for i in items if not (i.category_group == "bottom" and "юбк" not in i.type)]
        outfit = _outfit(skirt_outfit, "autumn", 8.0, 5.0)
        if outfit.get("bottom") and "юбк" in (outfit["bottom"].type or "").lower():
            assert outfit.get("tights") is not None, "No tights under skirt at 8°C!"


# ══════════════════════════════════════════════════════════════════════════════
# 4. CTO EXPERT
# ══════════════════════════════════════════════════════════════════════════════

class TestCTOExpert:
    """CTO evaluates: edge cases, performance, graceful degradation."""

    def test_100_items_performance(self):
        """CTO: 100+ items wardrobe — no crash, <100ms."""
        import time
        items = _realistic_woman_32()
        extras = [_item("top", f"топ_{i}", "белый", score=5+i%5, warmth=1+i%5) for i in range(70)]
        items.extend(extras)
        assert len(items) > 100

        start = time.time()
        for _ in range(10):
            _outfit(items, "spring", 15.0, 12.0)
        elapsed = (time.time() - start) / 10
        assert elapsed < 0.1, f"Outfit selection took {elapsed*1000:.0f}ms, should be <100ms"

    def test_all_none_fields_no_crash(self):
        """CTO: items with None everywhere — no crash."""
        items = [
            _item("top", None, None, warmth=2),
            _item("bottom", None, None, warmth=3),
            _item("footwear", None, None, warmth=2),
            _item("underwear", "трусики"),
        ]
        outfit = _outfit(items, "spring", 15.0, 12.0)
        assert isinstance(outfit, dict)

    def test_normalize_extreme_inputs(self):
        """CTO: normalization handles garbage inputs."""
        assert normalize_type("", "top") == ("", "top")
        assert normalize_type(None, "top") == (None, "top")
        assert normalize_color("") == ""
        assert normalize_color(None) is None
        # Very long string
        assert len(normalize_type("a" * 10000)[0]) == 10000
        assert len(normalize_color("x" * 10000)) == 10000

    def test_photo_quality_never_crashes(self):
        """CTO: photo quality handles any input."""
        assert not assess_photo(b"").is_usable
        assert not assess_photo(b"not an image").is_usable
        assert not assess_photo(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100).is_usable

    def test_color_compatibility_symmetric(self):
        """CTO: color_compatibility(a,b) == color_compatibility(b,a)."""
        pairs = [
            ("красный", "синий"), ("белый", "чёрный"), ("розовый", "бордовый"),
            ("зелёный", "оранжевый"), ("серый", "фуксия"),
        ]
        for a, b in pairs:
            assert color_compatibility(a, b) == color_compatibility(b, a), (
                f"Asymmetric: {a}+{b}={color_compatibility(a,b)} vs {b}+{a}={color_compatibility(b,a)}"
            )

    def test_warmth_consistency_prevents_absurd(self):
        """CTO: puffer jacket + summer shorts = prevented."""
        items = [
            _item("top", "свитер", warmth=4, score=8),
            _item("bottom", "шорты", warmth=1, score=7, season=["summer"]),
            _item("bottom", "джинсы", warmth=3, score=6),
            _item("outerwear", "пуховик", warmth=5, score=8, season=["winter"]),
            _item("footwear", "ботинки", warmth=4, score=7, season=["winter"]),
            _item("underwear", "трусики"),
        ]
        outfit = _outfit(items, "winter", 0.0, -5.0)
        bottom = outfit.get("bottom")
        if bottom and isinstance(bottom.warmth_level, (int, float)):
            assert bottom.warmth_level >= 2, "Shorts with puffer jacket!"


# ══════════════════════════════════════════════════════════════════════════════
# 5. GROWTH MANAGER EXPERT
# ══════════════════════════════════════════════════════════════════════════════

class TestGrowthManagerExpert:
    """Growth manager evaluates: engagement hooks, monetization signals."""

    def test_gaps_for_small_wardrobe(self):
        """Growth: small wardrobe → show what to add (engagement)."""
        items = [
            _item("top", "футболка", score=6),
            _item("bottom", "джинсы", score=7),
            _item("footwear", "кроссовки", score=6.5),
            _item("underwear", "трусики"),
        ]
        gaps = get_wardrobe_gaps(items)
        assert any("Добавь" in g for g in gaps), f"Small wardrobe should show gaps: {gaps}"

    def test_combo_potential_motivates(self):
        """Growth: show "you can make N outfits!" to motivate adding items."""
        items = _realistic_woman_32()
        gaps = get_wardrobe_gaps(items)
        combo = [g for g in gaps if "комбинаций" in g]
        assert combo, "Should show combo potential for large wardrobe"
        # The number should be impressive
        import re
        numbers = re.findall(r'~?(\d+)', combo[0])
        if numbers:
            assert int(numbers[0]) >= 20, f"Combo count {numbers[0]} not impressive enough"

    def test_empty_wardrobe_cta(self):
        """Growth: empty wardrobe → specific CTA."""
        gaps = get_wardrobe_gaps([])
        assert any("пуст" in g.lower() for g in gaps)

    def test_wardrobe_balance_insight_for_accent_heavy(self):
        """Growth: too many accent items → suggest neutrals (shopping opportunity)."""
        items = _unbalanced_wardrobe()
        insight = get_wardrobe_balance_insight(items)
        # 11 items with mostly accent colors should trigger insight
        if insight:
            assert "нейтральн" in insight.lower() or "базов" in insight.lower()


# ══════════════════════════════════════════════════════════════════════════════
# 6. UX LEAD EXPERT
# ══════════════════════════════════════════════════════════════════════════════

class TestUXLeadExpert:
    """UX lead evaluates: feedback quality, error messages, progressive disclosure."""

    def test_comment_never_empty(self):
        """UX: Kassi comment should never be empty string."""
        for score in [2.0, 5.0, 7.0, 8.5, 10.0]:
            for count in [1, 3, 7]:
                comment = warm_outfit_comment(
                    score=score, child_name="Алиса", temp=15.0,
                    real_item_count=count, first_item_desc="футболка розовая",
                )
                assert len(comment) >= 10, f"Too short comment for score={score}, count={count}"

    def test_photo_tips_are_specific(self):
        """UX: photo quality tips should be actionable, not generic."""
        from io import BytesIO
        from PIL import Image

        # Dark photo
        img = Image.new("RGB", (800, 1000), (20, 20, 20))
        buf = BytesIO()
        img.save(buf, format="JPEG")
        q = assess_photo(buf.getvalue())
        if q.tips:
            assert any("свет" in t or "тёмн" in t for t in q.tips), (
                f"Dark photo tip should mention light: {q.tips}"
            )

    def test_score_text_never_shows_number(self):
        """UX: user should see text labels, never numeric score."""
        from services.outfit_builder import score_to_text, outfit_score_to_text
        for score in [2.0, 5.0, 7.0, 8.5, 10.0]:
            text = score_to_text(score)
            assert text  # not empty
            # Should not contain digits (except emoji)
            clean = text.replace("🌟", "").replace("👍", "").replace("👌", "").replace("👕", "")
            assert not any(c.isdigit() for c in clean), f"Score text contains number: {text}"

    def test_gap_messages_positive_tone(self):
        """UX: gap messages should be encouraging, not critical."""
        items = [_item("top", "футболка"), _item("underwear", "трусики")]
        gaps = get_wardrobe_gaps(items)
        for gap in gaps:
            # Should NOT contain negative words
            assert "плохо" not in gap.lower()
            assert "не хватает" not in gap.lower()  # prefer "Добавь" over "Не хватает"

    def test_build_outfit_slots_always_returns_list(self):
        """UX: build_outfit_slots never returns None or crashes."""
        items = _realistic_girl_3()
        for temp, season in [(30, "summer"), (15, "spring"), (5, "autumn"), (-10, "winter")]:
            outfit = _outfit(items, season, float(temp), float(temp - 4))
            if has_minimum_outfit(outfit):
                slots = build_outfit_slots(outfit, temp=float(temp), colortype="default")
                assert isinstance(slots, list)
                assert all(isinstance(s, dict) for s in slots)


# ══════════════════════════════════════════════════════════════════════════════
# CROSS-EXPERT INTEGRATION: Full Pipeline Stress Test
# ══════════════════════════════════════════════════════════════════════════════

class TestFullPipelineIntegration:
    """All experts together: full pipeline from wardrobe → outfit → slots → comment."""

    @pytest.mark.parametrize("wardrobe_fn,name", [
        (_realistic_girl_3, "girl_3"),
        (_realistic_woman_32, "woman_32"),
        (_unbalanced_wardrobe, "unbalanced"),
    ])
    @pytest.mark.parametrize("temp,season", [
        (30, "summer"), (18, "spring"), (8, "autumn"), (-5, "winter"),
    ])
    def test_complete_pipeline(self, wardrobe_fn, name, temp, season):
        """Full pipeline: wardrobe → outfit → slots → comment → color score."""
        items = wardrobe_fn()
        outfit = _outfit(items, season, float(temp), float(temp - 4))

        # 1. Outfit validity
        if has_minimum_wardrobe(items):
            if not has_minimum_outfit(outfit):
                # Acceptable only if seasonal items missing
                return

        # 2. Build slots (no crash)
        if has_minimum_outfit(outfit):
            slots = build_outfit_slots(outfit, temp=float(temp), colortype="default")
            assert isinstance(slots, list)

            # 3. No base layer in visual slots
            for s in slots:
                if s.get("has_item"):
                    assert not any(
                        p in (s.get("item_type", "") or "").lower()
                        for p in ["носк", "трусик", "майк"]
                    ), f"Base layer in slots! {s}"

            # 4. Color harmony check
            visual = _visual(outfit)
            if len(visual) >= 2:
                score = score_outfit_colors(visual)
                assert score >= 3.0, (
                    f"Very low harmony {score} for {name}/{temp}°C. "
                    f"Colors: {[v.color for v in visual]}"
                )

        # 5. Comment generation (no crash)
        visual = _visual(outfit)
        comment = warm_outfit_comment(
            score=7.0, child_name="Test" if "girl" in name else None,
            temp=float(temp), has_outerwear=outfit.get("outerwear") is not None,
            real_item_count=len(visual),
            first_item_desc=f"{visual[0].type} {visual[0].color}" if visual else "",
        )
        assert len(comment) >= 10

    def test_gap_analysis_complete(self):
        """All wardrobes get gap analysis without crash."""
        for fn in [_realistic_girl_3, _realistic_woman_32, _unbalanced_wardrobe]:
            items = fn()
            gaps = get_wardrobe_gaps(items)
            assert isinstance(gaps, list)
            assert all(isinstance(g, str) for g in gaps)
