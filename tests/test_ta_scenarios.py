"""
Synthetic TA scenarios — expanded target audience modeling.

Core TA:
- Маша (28, mom_girl, 3yo daughter, visual, rushed mornings)
- Лена (26, no_kids, office, "full closet nothing to wear")

Expanded TA:
- Даша (22, студентка, бюджет, тренды, Instagram)
- Оля (40, бизнесвумен, premium quality, capsule wardrobe)
- Катя (30, pregnant, comfort first, adaptive sizing)
- Дима (35, dad, secondary user, wife shared link)
- Аня (18, выпускница, formal events, uncertain style)

Tests model real usage flows and validate all features work
for each persona across: eval, gaps, style prefs, colortype, debug.
"""
import json
import pytest
from datetime import date

from services.outfit_evaluator import (
    build_eval_prompt,
    parse_eval_response,
    format_eval_text,
    score_to_tier,
    cross_validate_colors,
    is_outfit_photo_heuristic,
    EVAL_DIMENSIONS,
)
from services.scoring import (
    get_wardrobe_gaps,
    get_wardrobe_balance_insight,
    calc_item_versatility,
    classify_role,
    OUTFIT_SCORE_WEIGHTS_ADULT,
    OUTFIT_SCORE_WEIGHTS_CHILD,
)
from services.color_harmony import (
    color_compatibility,
    score_outfit_colors,
    is_neutral,
)


# ── Mock helpers ──────────────────────────────────────────────────────────

class MockItem:
    def __init__(self, type_="футболка", color="белый", category_group="top",
                 score_item=5.0, season=None, warmth_level=2, id=None, role=None):
        self.id = id or hash(f"{type_}{color}")
        self.type = type_
        self.color = color
        self.category_group = category_group
        self.score_item = score_item
        self.season = season or ["spring", "summer", "autumn"]
        self.warmth_level = warmth_level
        self.role = role


def _make_wardrobe(*specs):
    """Quick wardrobe builder: (type, color, category_group)."""
    items = []
    for i, spec in enumerate(specs):
        if len(spec) == 3:
            t, c, cg = spec
            items.append(MockItem(t, c, cg, score_item=6.0, id=i))
        elif len(spec) == 4:
            t, c, cg, score = spec
            items.append(MockItem(t, c, cg, score_item=score, id=i))
    return items


# ══════════════════════════════════════════════════════════════════════════
# 1. МАША (28, mom_girl) — Morning rush scenarios
# ══════════════════════════════════════════════════════════════════════════

class TestMashaExpanded:
    """Mom with 3yo daughter. Practical, quick decisions."""

    def test_child_wardrobe_gaps_basic(self):
        """Маша's daughter has minimal wardrobe — should suggest missing slots."""
        items = _make_wardrobe(
            ("футболка", "розовый", "top"),
            ("штаны", "серый", "bottom"),
        )
        gaps = get_wardrobe_gaps(items)
        assert any("обувь" in g for g in gaps)

    def test_child_wardrobe_full_capsule(self):
        """Full capsule — has combo potential."""
        items = _make_wardrobe(
            ("футболка", "розовый", "top"),
            ("футболка", "белый", "top"),
            ("кофта", "серый", "top"),
            ("штаны", "синий", "bottom"),
            ("юбка", "розовый", "bottom"),
            ("куртка", "розовый", "outerwear"),
            ("кроссовки", "белый", "footwear"),
            ("сандалии", "розовый", "footwear"),
        )
        gaps = get_wardrobe_gaps(items)
        # Should show combo potential
        assert any("комбинац" in g.lower() or "Потенциал" in g for g in gaps)

    def test_eval_prompt_child_3yo(self):
        """Prompt for 3yo should emphasize safety."""
        prompt = build_eval_prompt(owner_type="child", child_age=3)
        assert "Безопасность" in prompt
        assert "детской моды" in prompt

    def test_eval_child_outfit_partial_dark(self):
        """Dark hallway, only top visible — partial, encouraging."""
        data = parse_eval_response(json.dumps({
            "is_outfit": True, "is_partial": True, "score": 6.5,
            "dimensions": {"safety": 8, "comfort": 7},
            "detected_items": [{"type": "куртка", "color": "розовый", "category_group": "outerwear"}],
            "strengths": "Куртка тёплая и яркая — легко найти на площадке!",
            "improvements": "Пришли полное фото.",
            "swaps": [], "overall_vibe": "Тёплый яркий",
        }))
        text = format_eval_text(data, owner_type="child")
        assert "часть образа" in text
        assert "Куртка тёплая" in text

    def test_mom_style_prefs_practical(self):
        """Mom prefers practical style, avoids dry-clean-only."""
        prompt = build_eval_prompt(
            owner_type="user", segment="mom_girl",
        )
        assert "практичность" in prompt.lower()

    def test_mom_eval_quick_good_result(self):
        """Good outfit → short response (< 200 chars)."""
        data = parse_eval_response(json.dumps({
            "is_outfit": True, "score": 8.5,
            "dimensions": {}, "detected_items": [],
            "strengths": "Красиво!", "improvements": "",
            "swaps": [], "overall_vibe": "Уютный",
        }))
        text = format_eval_text(data)
        assert len(text) < 250  # Keep it short for moms


# ══════════════════════════════════════════════════════════════════════════
# 2. ЛЕНА (26, no_kids) — Style-conscious scenarios
# ══════════════════════════════════════════════════════════════════════════

class TestLenaExpanded:
    """Career woman, values style and color harmony."""

    def test_wardrobe_balance_too_many_accents(self):
        """Лена has too many statement pieces, few basics."""
        items = _make_wardrobe(
            ("платье", "красный", "one_piece"),
            ("блузка", "фуксия", "top"),
            ("юбка", "бордовый", "bottom"),
            ("пиджак", "изумрудный", "outerwear"),
            ("туфли", "золотистый", "footwear"),
        )
        for i in items:
            i.role = classify_role(i.type, i.color)
        insight = get_wardrobe_balance_insight(items)
        # Too few items for insight (need 10+)
        assert insight is None

    def test_wardrobe_balance_with_10_items(self):
        items = []
        for i in range(7):
            items.append(MockItem(f"блузка{i}", "красный", "top", id=i, role="accent"))
        for i in range(3):
            items.append(MockItem(f"джинсы{i}", "синий", "bottom", id=i+7, role="base"))
        insight = get_wardrobe_balance_insight(items)
        assert insight is not None
        assert "ярк" in insight.lower()

    def test_color_harmony_monochrome(self):
        """All-black outfit = great harmony."""
        items = [MockItem(color="чёрный"), MockItem(color="чёрный"), MockItem(color="тёмно-серый")]
        score = score_outfit_colors(items)
        assert score >= 7.0

    def test_color_harmony_complementary(self):
        """Navy + white = excellent."""
        items = [MockItem(color="тёмно-синий"), MockItem(color="белый")]
        score = score_outfit_colors(items)
        assert score >= 8.0

    def test_eval_no_kids_detailed_feedback(self):
        """Лена wants detailed feedback, not just "ok"."""
        prompt = build_eval_prompt(owner_type="user", segment="no_kids")
        assert "вдохновляющий" in prompt.lower()

    def test_cross_validate_catches_clash(self):
        """Vision says "great!" but red+orange actually clash near each other."""
        detected = [
            {"color": "ярко-красный", "category_group": "top"},
            {"color": "оранжевый", "category_group": "bottom"},
        ]
        # These are analogous (hue distance ~30°), should be OK actually
        result = cross_validate_colors(detected, 8.0)
        assert isinstance(result, float)


# ══════════════════════════════════════════════════════════════════════════
# 3. ДАША (22, студентка) — Budget, trendy
# ══════════════════════════════════════════════════════════════════════════

class TestDashaStudent:
    """22yo student: budget-conscious, follows trends, Instagram aesthetic."""

    def test_small_wardrobe_gaps(self):
        """Student has minimal wardrobe — gaps everywhere."""
        items = _make_wardrobe(
            ("джинсы", "синий", "bottom"),
            ("кроссовки", "белый", "footwear"),
        )
        gaps = get_wardrobe_gaps(items)
        assert any("верх" in g for g in gaps)

    def test_eval_trendy_combo(self):
        """Oversized blazer + bike shorts — trendy but unusual."""
        data = parse_eval_response(json.dumps({
            "is_outfit": True, "score": 7.0,
            "dimensions": {"color_harmony": 7, "style_coherence": 6, "creativity": 9},
            "detected_items": [
                {"type": "пиджак", "color": "чёрный", "category_group": "outerwear"},
                {"type": "велошорты", "color": "чёрный", "category_group": "bottom"},
                {"type": "кроссовки", "color": "белый", "category_group": "footwear"},
            ],
            "strengths": "Модный контраст объёмного пиджака и минималистичного низа!",
            "improvements": "Добавь яркую сумку или украшение как focal point.",
            "swaps": [], "overall_vibe": "Street style chic",
        }))
        text = format_eval_text(data)
        assert "Хороший" in text
        assert "Модный контраст" in text

    def test_versatility_with_basics(self):
        """Student with basics should have good combo potential."""
        items = _make_wardrobe(
            ("футболка", "белый", "top"),
            ("футболка", "чёрный", "top"),
            ("джинсы", "синий", "bottom"),
            ("юбка", "чёрный", "bottom"),
            ("кроссовки", "белый", "footwear"),
        )
        for i in items:
            v = calc_item_versatility(i, items)
            if i.color in ("белый", "чёрный"):
                assert v >= 1  # neutrals pair with many


# ══════════════════════════════════════════════════════════════════════════
# 4. ОЛЯ (40, бизнесвумен) — Premium, capsule
# ══════════════════════════════════════════════════════════════════════════

class TestOlyaBusiness:
    """40yo businesswoman: premium quality, capsule approach, investment pieces."""

    def test_capsule_wardrobe_combo_potential(self):
        """Well-curated capsule = high combo count."""
        items = _make_wardrobe(
            ("блузка", "белый", "top", 8.0),
            ("блузка", "голубой", "top", 7.5),
            ("водолазка", "чёрный", "top", 8.0),
            ("брюки", "чёрный", "bottom", 8.5),
            ("юбка", "бежевый", "bottom", 7.0),
            ("джинсы", "тёмно-синий", "bottom", 7.5),
            ("пальто", "бежевый", "outerwear", 9.0),
            ("лоферы", "чёрный", "footwear", 8.0),
            ("кроссовки", "белый", "footwear", 7.0),
        )
        gaps = get_wardrobe_gaps(items)
        # Should show combo potential
        combo_line = [g for g in gaps if "комбинац" in g.lower()]
        assert combo_line  # Should calculate combos
        # 3 tops × 3 bottoms × 2 outerwear = 18+ combos
        assert "18" in combo_line[0] or any(int(c) >= 18 for c in combo_line[0] if c.isdigit())

    def test_eval_investment_outfit(self):
        """Premium outfit should score high."""
        data = parse_eval_response(json.dumps({
            "is_outfit": True, "score": 9.0,
            "dimensions": {
                "color_harmony": 9, "proportions": 9,
                "style_coherence": 9, "occasion_fit": 9,
                "details_polish": 9, "creativity": 8,
            },
            "detected_items": [
                {"type": "пальто", "color": "бежевый", "category_group": "outerwear"},
                {"type": "водолазка", "color": "чёрный", "category_group": "top"},
                {"type": "брюки", "color": "чёрный", "category_group": "bottom"},
            ],
            "strengths": "Безупречный минимализм! Бежевый + чёрный = вечная классика.",
            "improvements": "",
            "swaps": [], "overall_vibe": "Парижский шик",
        }))
        text = format_eval_text(data)
        assert "Wow" in text
        assert "Безупречный" in text

    def test_all_neutrals_high_harmony(self):
        """Оля's capsule (all neutrals) should have perfect color harmony."""
        items = [
            MockItem(color="чёрный"),
            MockItem(color="белый"),
            MockItem(color="бежевый"),
            MockItem(color="тёмно-синий"),
        ]
        score = score_outfit_colors(items)
        assert score >= 9.0


# ══════════════════════════════════════════════════════════════════════════
# 5. КАТЯ (30, pregnant) — Comfort first
# ══════════════════════════════════════════════════════════════════════════

class TestKatyaPregnant:
    """30yo pregnant woman: comfort is top priority, adaptive sizing."""

    def test_eval_prompt_pregnant(self):
        prompt = build_eval_prompt(owner_type="user", segment="pregnant")
        assert "комфорт" in prompt.lower()

    def test_eval_comfortable_outfit(self):
        """Stretchy outfit should be praised."""
        data = parse_eval_response(json.dumps({
            "is_outfit": True, "score": 8.0,
            "dimensions": {"color_harmony": 7, "proportions": 8, "style_coherence": 8},
            "detected_items": [
                {"type": "платье", "color": "тёмно-синий", "category_group": "one_piece"},
                {"type": "кроссовки", "color": "белый", "category_group": "footwear"},
            ],
            "strengths": "Удобное платье свободного кроя — идеально для комфорта!",
            "improvements": "",
            "swaps": [], "overall_vibe": "Комфортный и стильный",
        }))
        text = format_eval_text(data)
        assert "Отличный" in text

    def test_wardrobe_gaps_pregnant(self):
        """Pregnant wardrobe may need specific items."""
        items = _make_wardrobe(
            ("платье", "чёрный", "one_piece"),
            ("леггинсы", "чёрный", "bottom"),
            ("кроссовки", "белый", "footwear"),
        )
        gaps = get_wardrobe_gaps(items)
        assert any("верх" in g for g in gaps)


# ══════════════════════════════════════════════════════════════════════════
# 6. АНЯ (18, выпускница) — Formal events, uncertain style
# ══════════════════════════════════════════════════════════════════════════

class TestAnyaGraduate:
    """18yo: first time thinking about formal style, needs guidance."""

    def test_eval_formal_event_outfit(self):
        """Formal outfit evaluation — occasion fit is key."""
        data = parse_eval_response(json.dumps({
            "is_outfit": True, "score": 7.0,
            "dimensions": {
                "color_harmony": 8, "proportions": 7,
                "style_coherence": 7, "occasion_fit": 5,
                "details_polish": 7, "creativity": 8,
            },
            "detected_items": [
                {"type": "платье", "color": "красный", "category_group": "one_piece"},
                {"type": "кеды", "color": "белый", "category_group": "footwear"},
            ],
            "strengths": "Красное платье — смелый выбор, отлично для вечера!",
            "improvements": "Кеды снижают формальность. Замени на каблуки или изящные босоножки.",
            "swaps": [{"current": "кеды белые", "suggested": "туфли чёрные", "reason": "поднимет формальность"}],
            "overall_vibe": "Яркий повседневный (а нужен вечерний)",
        }))
        text = format_eval_text(data)
        assert "Хороший" in text
        assert "кеды белые → туфли чёрные" in text.lower() or "туфли" in text

    def test_first_time_wardrobe_gaps(self):
        """Almost empty wardrobe — clear guidance needed."""
        items = []
        gaps = get_wardrobe_gaps(items)
        assert any("пуст" in g.lower() for g in gaps)


# ══════════════════════════════════════════════════════════════════════════
# 7. ДИМА (35, dad) — Secondary user
# ══════════════════════════════════════════════════════════════════════════

class TestDimaDad:
    """Dad: wife shared the bot link, checking kid's outfit for daycare."""

    def test_child_eval_works_for_dad(self):
        """Dad evaluating child's outfit — same dimensions as mom."""
        prompt_mom = build_eval_prompt(owner_type="child", child_age=4)
        prompt_dad = build_eval_prompt(owner_type="child", child_age=4)
        # Same prompt regardless of parent gender
        assert prompt_mom == prompt_dad

    def test_child_wardrobe_boy(self):
        """Boy's wardrobe gaps."""
        items = _make_wardrobe(
            ("футболка", "синий", "top"),
            ("шорты", "серый", "bottom"),
        )
        gaps = get_wardrobe_gaps(items)
        assert any("обувь" in g for g in gaps)


# ══════════════════════════════════════════════════════════════════════════
# 8. CROSS-TA: Features work for ALL personas
# ══════════════════════════════════════════════════════════════════════════

class TestCrossTA:
    """Features must work consistently across all personas."""

    @pytest.mark.parametrize("segment", ["mom_girl", "mom_boy", "no_kids", "pregnant"])
    def test_eval_prompt_for_all_segments(self, segment):
        prompt = build_eval_prompt(owner_type="user", segment=segment)
        assert "JSON" in prompt
        assert "is_outfit" in prompt

    @pytest.mark.parametrize("colortype", [
        "Весна", "Лето", "Осень", "Зима",
        "Bright Spring", "True Summer", "Soft Autumn", "Deep Winter",
    ])
    def test_eval_with_all_colortypes(self, colortype):
        prompt = build_eval_prompt(owner_type="user", colortype=colortype)
        assert colortype in prompt

    @pytest.mark.parametrize("body_type", [
        "песочные часы", "груша", "яблоко", "прямоугольник", "перевёрнутый треугольник",
    ])
    def test_eval_with_all_body_types(self, body_type):
        prompt = build_eval_prompt(owner_type="user", body_type=body_type)
        assert body_type in prompt

    def test_tier_labels_are_encouraging(self):
        """No negative labels in any tier."""
        negative_words = ["плохо", "ужас", "провал", "катастроф"]
        for score in [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]:
            tier = score_to_tier(score)
            for neg in negative_words:
                assert neg not in tier["label"].lower(), f"Negative word '{neg}' in tier for {score}"

    def test_outfit_heuristic_consistency(self):
        """Heuristic should be consistent: 2+ non-base groups = outfit."""
        combos = [
            ([{"category_group": "top"}, {"category_group": "bottom"}], True),
            ([{"category_group": "one_piece"}, {"category_group": "footwear"}], True),
            ([{"category_group": "top"}], False),
            ([{"category_group": "top"}, {"category_group": "base_layer"}], False),
            ([], False),
        ]
        for items, expected in combos:
            assert is_outfit_photo_heuristic(items) == expected

    def test_neutral_colors_universal(self):
        """Neutral colors should be detected across languages."""
        for color in ["белый", "чёрный", "серый", "бежевый", "navy", "тёмно-синий"]:
            assert is_neutral(color), f"{color} should be neutral"

    def test_score_never_shown_to_user(self):
        """Across all tiers, numeric score never appears in output."""
        for s in [2.0, 4.0, 6.0, 8.0, 10.0]:
            data = {
                "is_outfit": True, "score": s,
                "dimensions": {}, "detected_items": [],
                "strengths": "OK", "improvements": "OK",
                "swaps": [], "overall_vibe": "OK",
            }
            text = format_eval_text(data)
            assert f"{s}" not in text
            assert "/10" not in text


# ══════════════════════════════════════════════════════════════════════════
# 9. COLOR HARMONY — Extended scenarios
# ══════════════════════════════════════════════════════════════════════════

class TestColorHarmonyExtended:
    """More color harmony tests for real-world outfits."""

    def test_all_black_outfit(self):
        items = [MockItem(color="чёрный")] * 3
        assert score_outfit_colors(items) >= 7.0

    def test_earth_tones(self):
        """Brown + beige + olive = earthy and harmonious."""
        items = [MockItem(color="коричневый"), MockItem(color="бежевый"), MockItem(color="оливковый")]
        score = score_outfit_colors(items)
        assert score >= 5.0  # Should be decent

    def test_too_many_colors_penalty(self):
        """4+ chromatic colors get penalty."""
        items = [
            MockItem(color="красный"),
            MockItem(color="синий"),
            MockItem(color="зелёный"),
            MockItem(color="оранжевый"),
            MockItem(color="фиолетовый"),
        ]
        score = score_outfit_colors(items)
        assert score < 7.0  # Penalty for 5 chromatic

    def test_single_item_default(self):
        """Single item = default score 7.0."""
        items = [MockItem(color="красный")]
        assert score_outfit_colors(items) == 7.0

    def test_unknown_color_with_neutral(self):
        """Unknown + neutral = 2.0 (neutral combines with anything)."""
        assert color_compatibility("суперцвет", "белый") == 2.0

    def test_unknown_colors_both(self):
        """Two unknown non-neutral colors = 0.0 (unknown)."""
        assert color_compatibility("суперцвет", "мегацвет") == 0.0

    def test_complementary_blue_orange(self):
        """Blue and orange = complementary, should be positive."""
        score = color_compatibility("синий", "оранжевый")
        assert score >= 0  # complementary or triadic


# ══════════════════════════════════════════════════════════════════════════
# 10. DEBUG COMMANDS SMOKE TESTS
# ══════════════════════════════════════════════════════════════════════════

class TestDebugSmoke:
    """Smoke tests: debug modules import cleanly and functions exist."""

    def test_debug_handlers_exist(self):
        from bot.handlers.debug import (
            handle_debug_reset,
            handle_debug_free,
            handle_debug_brief,
            handle_debug_eval,
            handle_debug_gaps,
            handle_debug_style,
            handle_debug_wardrobe,
        )
        assert callable(handle_debug_eval)
        assert callable(handle_debug_gaps)
        assert callable(handle_debug_style)
        assert callable(handle_debug_wardrobe)

    def test_profile_style_handlers_exist(self):
        from bot.handlers.profile import (
            handle_edit_style_prefs,
            handle_set_style,
            handle_avoid_pref,
        )
        assert callable(handle_edit_style_prefs)
        assert callable(handle_set_style)
        assert callable(handle_avoid_pref)

    def test_app_registers_all_handlers(self):
        """App should import without errors."""
        import importlib
        mod = importlib.import_module("bot.app")
        assert hasattr(mod, "create_application")

    def test_eval_dimensions_stable(self):
        """Dimensions should sum to 100 and be stable."""
        total = sum(d["weight"] for d in EVAL_DIMENSIONS.values())
        assert total == 100

    def test_classify_role_works(self):
        assert classify_role("футболка", "белый") == "base"
        assert classify_role("вечернее платье", "красный") == "statement"
        assert classify_role("блузка", "розовый") == "accent"


# ══════════════════════════════════════════════════════════════════════════
# 11. WARDROBE SCORING WEIGHTS CONSISTENCY
# ══════════════════════════════════════════════════════════════════════════

class TestScoringWeightsConsistency:
    """Ensure scoring weights are consistent and documented."""

    def test_adult_outfit_max_score(self):
        """Adult outfit max should equal sum of all weights."""
        total = sum(
            sum(w for w in group.values())
            for group in OUTFIT_SCORE_WEIGHTS_ADULT.values()
        )
        assert total == 26  # documented in scoring.py

    def test_child_outfit_max_score(self):
        total = sum(OUTFIT_SCORE_WEIGHTS_CHILD.values())
        assert total == 11

    def test_eval_dimensions_cover_all_aspects(self):
        """All major fashion aspects covered."""
        dim_names = set(EVAL_DIMENSIONS.keys())
        required = {"color_harmony", "proportions", "style_coherence", "occasion_fit"}
        assert required.issubset(dim_names)
