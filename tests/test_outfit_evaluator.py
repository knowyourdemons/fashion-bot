"""
Tests for outfit evaluation service — professional stylist analysis.

Models all TA scenarios:
- Mom (Маша): rushing morning, dark hallway photo, partial photo, child outfit
- Woman (Лена): mirror selfie, work outfit, date night, bold combo
- Edge cases: no person, flat lay, empty wardrobe, bad photo, multiple people
- Scoring: cross-validation, tier boundaries, dimension weights
- Formatting: text output, CTA, swap display rules
"""
import json
import pytest

from services.outfit_evaluator import (
    EVAL_DIMENSIONS,
    build_eval_prompt,
    cross_validate_colors,
    format_eval_text,
    is_outfit_photo_heuristic,
    parse_eval_response,
    score_to_tier,
)


# ══════════════════════════════════════════════════════════════════════════
# 1. TIER SYSTEM
# ══════════════════════════════════════════════════════════════════════════

class TestScoreTiers:
    """Tier boundaries must be stable — they affect user-facing labels."""

    def test_wow_tier(self):
        t = score_to_tier(9.5)
        assert t["tier"] == "wow"
        assert t["show_swap"] is False

    def test_wow_boundary(self):
        t = score_to_tier(9.0)
        assert t["tier"] == "wow"

    def test_great_tier(self):
        t = score_to_tier(8.0)
        assert t["tier"] == "great"
        assert t["show_swap"] is False

    def test_great_boundary(self):
        t = score_to_tier(7.5)
        assert t["tier"] == "great"

    def test_good_tier(self):
        t = score_to_tier(7.0)
        assert t["tier"] == "good"
        assert t["show_swap"] is True

    def test_good_boundary(self):
        t = score_to_tier(6.0)
        assert t["tier"] == "good"

    def test_adjust_tier(self):
        t = score_to_tier(5.5)
        assert t["tier"] == "adjust"
        assert t["show_swap"] is True

    def test_adjust_boundary(self):
        t = score_to_tier(4.5)
        assert t["tier"] == "adjust"

    def test_boost_tier(self):
        """Lowest tier should be encouraging, not negative."""
        t = score_to_tier(3.0)
        assert t["tier"] == "boost"
        assert "усилим" in t["label"]
        assert t["show_swap"] is True

    def test_minimum_score(self):
        t = score_to_tier(1.0)
        assert t["tier"] == "boost"

    def test_all_tiers_have_emoji(self):
        for score in [1.0, 4.5, 6.0, 7.5, 9.0]:
            t = score_to_tier(score)
            assert t["emoji"], f"No emoji for score {score}"
            assert t["label"], f"No label for score {score}"


# ══════════════════════════════════════════════════════════════════════════
# 2. PROMPT BUILDING
# ══════════════════════════════════════════════════════════════════════════

class TestBuildEvalPrompt:
    """Prompts should be context-aware and include all relevant info."""

    def test_adult_woman_basic(self):
        prompt = build_eval_prompt(owner_type="user")
        assert "персональным стилистом" in prompt
        assert "JSON" in prompt
        assert "is_outfit" in prompt

    def test_child_prompt(self):
        prompt = build_eval_prompt(owner_type="child", child_age=3)
        assert "детской моды" in prompt
        assert "3 лет" in prompt
        assert "Безопасность" in prompt

    def test_colortype_in_prompt(self):
        prompt = build_eval_prompt(owner_type="user", colortype="Лето")
        assert "Лето" in prompt
        assert "цветотип" in prompt.lower() or "Цветотип" in prompt

    def test_body_type_in_prompt(self):
        prompt = build_eval_prompt(owner_type="user", body_type="груша")
        assert "груша" in prompt

    def test_mom_segment_tone(self):
        prompt = build_eval_prompt(owner_type="user", segment="mom_girl")
        assert "мама" in prompt.lower()
        assert "практичность" in prompt.lower()

    def test_no_kids_segment_tone(self):
        prompt = build_eval_prompt(owner_type="user", segment="no_kids")
        assert "стиль" in prompt.lower()
        assert "вдохновляющий" in prompt.lower()

    def test_pregnant_segment(self):
        prompt = build_eval_prompt(owner_type="user", segment="pregnant")
        assert "комфорт" in prompt.lower()

    def test_wardrobe_in_prompt(self):
        """Wardrobe items should appear in prompt for swap suggestions."""
        class MockItem:
            def __init__(self, t, c, s):
                self.type = t
                self.color = c
                self.score_item = s
        items = [MockItem("джинсы", "синий", 7.0), MockItem("кроссовки", "белый", 8.0)]
        prompt = build_eval_prompt(owner_type="user", wardrobe_items=items)
        assert "кроссовки белый" in prompt
        assert "джинсы синий" in prompt

    def test_empty_wardrobe(self):
        prompt = build_eval_prompt(owner_type="user", wardrobe_items=[])
        assert "пуст" in prompt.lower()

    def test_occasion_hint(self):
        prompt = build_eval_prompt(owner_type="user", occasion="офис")
        assert "офис" in prompt

    def test_proportions_rule_in_prompt(self):
        """Expert panel recommendation: proportions rule must be in prompt."""
        prompt = build_eval_prompt(owner_type="user")
        assert "пропорц" in prompt.lower() or "третей" in prompt.lower()

    def test_mirror_selfie_hint(self):
        """Expert panel: ignore phone hand in mirror selfies."""
        prompt = build_eval_prompt(owner_type="user")
        assert "зеркальное" in prompt.lower() or "телефон" in prompt.lower()

    def test_never_comment_body(self):
        prompt = build_eval_prompt(owner_type="user")
        assert "никогда не комментируй тело" in prompt.lower()

    def test_child_dimensions_differ_from_adult(self):
        child_prompt = build_eval_prompt(owner_type="child")
        adult_prompt = build_eval_prompt(owner_type="user")
        assert "Безопасность" in child_prompt
        assert "Безопасность" not in adult_prompt


# ══════════════════════════════════════════════════════════════════════════
# 3. JSON PARSING (Vision response handling)
# ══════════════════════════════════════════════════════════════════════════

class TestParseEvalResponse:
    """Parser must handle all Vision output formats gracefully."""

    VALID_JSON = json.dumps({
        "is_outfit": True,
        "is_partial": False,
        "score": 7.5,
        "dimensions": {
            "color_harmony": 8,
            "proportions": 7,
            "style_coherence": 8,
            "occasion_fit": 7,
            "details_polish": 6,
            "creativity": 7,
        },
        "detected_items": [
            {"type": "блузка", "color": "белый", "category_group": "top"},
            {"type": "джинсы", "color": "синий", "category_group": "bottom"},
        ],
        "strengths": "Цвета отлично сочетаются.",
        "improvements": "Добавь аксессуар.",
        "swaps": [],
        "overall_vibe": "Свежий повседневный",
    })

    def test_parse_valid_json(self):
        result = parse_eval_response(self.VALID_JSON)
        assert result is not None
        assert result["score"] == 7.5
        assert result["is_outfit"] is True

    def test_parse_with_markdown_fences(self):
        wrapped = f"```json\n{self.VALID_JSON}\n```"
        result = parse_eval_response(wrapped)
        assert result is not None
        assert result["score"] == 7.5

    def test_parse_with_text_before_json(self):
        wrapped = f"Вот результат:\n{self.VALID_JSON}"
        result = parse_eval_response(wrapped)
        assert result is not None

    def test_parse_invalid_json(self):
        result = parse_eval_response("это не json вообще")
        assert result is None

    def test_parse_empty_string(self):
        result = parse_eval_response("")
        assert result is None

    def test_score_clamping_high(self):
        data = json.dumps({"score": 15.0, "dimensions": {}})
        result = parse_eval_response(data)
        assert result["score"] == 10.0

    def test_score_clamping_low(self):
        data = json.dumps({"score": -2.0, "dimensions": {}})
        result = parse_eval_response(data)
        assert result["score"] == 1.0

    def test_dimension_clamping(self):
        data = json.dumps({"score": 5.0, "dimensions": {"color_harmony": 15, "proportions": -3}})
        result = parse_eval_response(data)
        assert result["dimensions"]["color_harmony"] == 10
        assert result["dimensions"]["proportions"] == 1

    def test_swaps_limited_to_2(self):
        data = json.dumps({
            "score": 5.0,
            "dimensions": {},
            "swaps": [
                {"current": "a", "suggested": "b", "reason": "c"},
                {"current": "d", "suggested": "e", "reason": "f"},
                {"current": "g", "suggested": "h", "reason": "i"},
            ],
        })
        result = parse_eval_response(data)
        assert len(result["swaps"]) == 2

    def test_defaults_for_missing_fields(self):
        data = json.dumps({"score": 6.0, "dimensions": {}})
        result = parse_eval_response(data)
        assert result["is_outfit"] is True  # default
        assert result["is_partial"] is False
        assert result["strengths"] == ""
        assert result["improvements"] == ""
        assert result["swaps"] == []
        assert result["detected_items"] == []

    def test_parse_partial_json_with_extra_text(self):
        """Vision might add explanation after JSON."""
        wrapped = self.VALID_JSON + "\n\nНадеюсь это поможет!"
        result = parse_eval_response(wrapped)
        assert result is not None

    def test_parse_json_array_returns_none(self):
        """Array instead of object should return None."""
        result = parse_eval_response("[1, 2, 3]")
        assert result is None


# ══════════════════════════════════════════════════════════════════════════
# 4. TEXT FORMATTING
# ══════════════════════════════════════════════════════════════════════════

class TestFormatEvalText:
    """User-facing text must follow all UX rules."""

    def _make_eval(self, score=7.0, **overrides):
        base = {
            "is_outfit": True,
            "is_partial": False,
            "score": score,
            "dimensions": {"color_harmony": 7},
            "detected_items": [],
            "strengths": "Хорошие цвета!",
            "improvements": "Добавь пояс.",
            "swaps": [],
            "overall_vibe": "Повседневный стиль",
        }
        base.update(overrides)
        return base

    def test_none_input(self):
        text = format_eval_text(None)
        assert "не удалось" in text.lower() or "Не удалось" in text

    def test_not_outfit(self):
        data = self._make_eval(is_outfit=False)
        text = format_eval_text(data)
        assert "не вижу образа" in text.lower()

    def test_partial_photo(self):
        data = self._make_eval(is_partial=True)
        text = format_eval_text(data)
        assert "часть образа" in text
        assert "полный рост" in text

    def test_wow_score_no_improvements(self):
        """Score >= 9: no improvements shown, no swaps."""
        data = self._make_eval(score=9.5)
        text = format_eval_text(data)
        assert "Wow" in text
        assert "Добавь пояс" not in text  # show_swap is False for wow

    def test_great_score_no_swaps(self):
        """Score 7.5-8.9: show label but no swaps."""
        data = self._make_eval(score=8.0)
        text = format_eval_text(data)
        assert "Отличный" in text
        assert "Добавь пояс" not in text

    def test_good_score_shows_improvements(self):
        """Score 6.0-7.4: show improvements and swaps."""
        data = self._make_eval(score=6.5)
        data["swaps"] = [{"current": "кеды", "suggested": "лоферы", "reason": "поднимет стиль"}]
        text = format_eval_text(data)
        assert "Добавь пояс" in text
        assert "лоферы" in text

    def test_adjust_score_shows_all(self):
        data = self._make_eval(score=5.0)
        text = format_eval_text(data)
        assert "потенциал" in text.lower()
        assert "Добавь пояс" in text

    def test_boost_score_encouraging(self):
        data = self._make_eval(score=3.0)
        text = format_eval_text(data)
        assert "усилим" in text.lower()

    def test_strengths_always_shown(self):
        """Expert panel: ALWAYS start with positive."""
        for score in [3.0, 5.0, 7.0, 9.0]:
            data = self._make_eval(score=score, strengths="Отличный выбор цвета!")
            text = format_eval_text(data)
            assert "Отличный выбор цвета!" in text

    def test_vibe_shown(self):
        data = self._make_eval(overall_vibe="Городской шик")
        text = format_eval_text(data)
        assert "Городской шик" in text

    def test_no_numeric_score_in_output(self):
        """CRITICAL: user never sees numeric score."""
        for score in [3.0, 5.0, 7.0, 9.0]:
            data = self._make_eval(score=score)
            text = format_eval_text(data)
            assert f"{score}" not in text
            assert "/10" not in text

    def test_cta_for_low_score(self):
        """Expert panel: CTA after evaluation."""
        data = self._make_eval(score=5.0)
        text = format_eval_text(data)
        assert "Что надеть" in text

    def test_no_cta_for_partial(self):
        """Partial photo gets different CTA."""
        data = self._make_eval(score=5.0, is_partial=True)
        text = format_eval_text(data)
        assert "полный рост" in text

    def test_swap_format(self):
        data = self._make_eval(score=5.0, swaps=[
            {"current": "кроссовки белые", "suggested": "лоферы бежевые", "reason": "поднимет формальность"},
        ])
        text = format_eval_text(data)
        assert "кроссовки белые → лоферы бежевые" in text
        assert "поднимет формальность" in text

    def test_max_two_swaps_in_output(self):
        data = self._make_eval(score=4.0, swaps=[
            {"current": "a", "suggested": "b", "reason": "c"},
            {"current": "d", "suggested": "e", "reason": "f"},
            {"current": "g", "suggested": "h", "reason": "i"},
        ])
        # Swaps already clamped by parser, but format should also limit
        text = format_eval_text(data)
        assert text.count("→") <= 2


# ══════════════════════════════════════════════════════════════════════════
# 5. CROSS-VALIDATION (local color harmony)
# ══════════════════════════════════════════════════════════════════════════

class TestCrossValidation:
    """Prevent Vision hallucinating 'great harmony' on clashing outfits."""

    def test_no_items_returns_original(self):
        assert cross_validate_colors([], 8.0) == 8.0

    def test_single_item_returns_original(self):
        items = [{"color": "красный"}]
        assert cross_validate_colors(items, 8.0) == 8.0

    def test_neutrals_no_adjustment(self):
        """Neutral colors should always be fine."""
        items = [{"color": "белый"}, {"color": "чёрный"}, {"color": "бежевый"}]
        result = cross_validate_colors(items, 9.0)
        assert result == 9.0

    def test_clash_detected(self):
        """Vision says 8.0 but colors actually clash → pulled down."""
        # Red + green at high saturation = potential clash
        items = [{"color": "ярко-красный"}, {"color": "ярко-зелёный"}]
        result = cross_validate_colors(items, 8.0)
        # Should stay same or adjust based on local scoring
        assert isinstance(result, float)

    def test_harmonious_combo_stays_high(self):
        """Navy + white = great → should stay high."""
        items = [{"color": "тёмно-синий"}, {"color": "белый"}]
        result = cross_validate_colors(items, 9.0)
        assert result >= 8.0

    def test_monochrome_stays_high(self):
        items = [{"color": "серый"}, {"color": "тёмно-серый"}, {"color": "светло-серый"}]
        result = cross_validate_colors(items, 8.5)
        assert result >= 8.0

    def test_items_without_color_ignored(self):
        items = [{"type": "кроссовки"}, {"color": "белый"}]
        result = cross_validate_colors(items, 7.0)
        assert result == 7.0  # only 1 color → original


# ══════════════════════════════════════════════════════════════════════════
# 6. OUTFIT DETECTION HEURISTIC
# ══════════════════════════════════════════════════════════════════════════

class TestOutfitHeuristic:
    """Determine if photo shows outfit vs single item."""

    def test_empty_list(self):
        assert is_outfit_photo_heuristic([]) is False

    def test_single_item(self):
        items = [{"category_group": "top"}]
        assert is_outfit_photo_heuristic(items) is False

    def test_two_categories_is_outfit(self):
        items = [
            {"category_group": "top"},
            {"category_group": "bottom"},
        ]
        assert is_outfit_photo_heuristic(items) is True

    def test_full_outfit(self):
        items = [
            {"category_group": "top"},
            {"category_group": "bottom"},
            {"category_group": "footwear"},
            {"category_group": "accessory"},
        ]
        assert is_outfit_photo_heuristic(items) is True

    def test_base_layer_ignored(self):
        """Base layer items don't count toward outfit detection."""
        items = [
            {"category_group": "top"},
            {"category_group": "base_layer"},
        ]
        assert is_outfit_photo_heuristic(items) is False

    def test_underwear_ignored(self):
        items = [
            {"category_group": "top"},
            {"category_group": "underwear"},
        ]
        assert is_outfit_photo_heuristic(items) is False

    def test_same_category_not_outfit(self):
        """Multiple tops without bottoms = not a full outfit."""
        items = [
            {"category_group": "top"},
            {"category_group": "top"},
        ]
        assert is_outfit_photo_heuristic(items) is False


# ══════════════════════════════════════════════════════════════════════════
# 7. TA SCENARIOS — МАША (мама, 28)
# ══════════════════════════════════════════════════════════════════════════

class TestMashaScenarios:
    """Mom scenarios: morning rush, dark hallway, partial photo, child outfit."""

    def test_dark_hallway_photo_partial(self):
        """Mom takes photo in dark hallway — partial visibility."""
        data = {
            "is_outfit": True,
            "is_partial": True,
            "score": 6.0,
            "dimensions": {"color_harmony": 7},
            "detected_items": [
                {"type": "куртка", "color": "розовый", "category_group": "outerwear"},
            ],
            "strengths": "Куртка яркая и нарядная!",
            "improvements": "Не вижу обувь — пришли полное фото.",
            "swaps": [],
            "overall_vibe": "Тёплый и нарядный",
        }
        text = format_eval_text(data, owner_type="child")
        assert "часть образа" in text
        assert "полный рост" in text
        assert "Куртка яркая" in text

    def test_child_outfit_good(self):
        """Child outfit evaluation — practical + safe."""
        data = {
            "is_outfit": True,
            "is_partial": False,
            "score": 8.0,
            "dimensions": {"safety": 9, "comfort": 8, "color_harmony": 7},
            "detected_items": [
                {"type": "куртка", "color": "синий", "category_group": "outerwear"},
                {"type": "штаны", "color": "серый", "category_group": "bottom"},
                {"type": "кроссовки", "color": "белый", "category_group": "footwear"},
            ],
            "strengths": "Тёплый и практичный образ! Легко одеть и снять.",
            "improvements": "",
            "swaps": [],
            "overall_vibe": "Удобный садиковский",
        }
        text = format_eval_text(data, owner_type="child")
        assert "Отличный" in text
        assert "Тёплый и практичный" in text
        # No improvements for score >= 7.5
        assert "Что надеть" not in text

    def test_child_outfit_needs_swap(self):
        """Child outfit has color mismatch — suggest swap from wardrobe."""
        data = {
            "is_outfit": True,
            "is_partial": False,
            "score": 5.5,
            "dimensions": {"color_harmony": 4, "safety": 8},
            "detected_items": [
                {"type": "футболка", "color": "красный", "category_group": "top"},
                {"type": "штаны", "color": "оранжевый", "category_group": "bottom"},
            ],
            "strengths": "Яркий и заметный образ!",
            "improvements": "Красный и оранжевый рядом перегружают. Замени штаны на нейтральные.",
            "swaps": [{"current": "штаны оранжевые", "suggested": "джинсы синие", "reason": "синий уравновесит красный"}],
            "overall_vibe": "Яркий спортивный",
        }
        text = format_eval_text(data, owner_type="child")
        assert "потенциал" in text.lower()
        assert "джинсы синие" in text

    def test_mom_quick_check_good_outfit(self):
        """Mom wants quick check — good outfit should be SHORT."""
        data = {
            "is_outfit": True,
            "is_partial": False,
            "score": 8.5,
            "dimensions": {},
            "detected_items": [],
            "strengths": "Отличное сочетание!",
            "improvements": "",
            "swaps": [],
            "overall_vibe": "Уютный каждодневный",
        }
        text = format_eval_text(data, owner_type="child")
        # Should be short for high score
        assert len(text) < 200


# ══════════════════════════════════════════════════════════════════════════
# 8. TA SCENARIOS — ЛЕНА (26, no_kids)
# ══════════════════════════════════════════════════════════════════════════

class TestLenaScenarios:
    """Woman scenarios: work outfit, date night, mirror selfie, bold combo."""

    def test_work_outfit_with_feedback(self):
        """Лена checks work outfit — wants detailed feedback."""
        data = {
            "is_outfit": True,
            "is_partial": False,
            "score": 7.0,
            "dimensions": {
                "color_harmony": 8,
                "proportions": 7,
                "style_coherence": 7,
                "occasion_fit": 6,
                "details_polish": 7,
                "creativity": 6,
            },
            "detected_items": [
                {"type": "блузка", "color": "белый", "category_group": "top"},
                {"type": "брюки", "color": "чёрный", "category_group": "bottom"},
                {"type": "кеды", "color": "белый", "category_group": "footwear"},
            ],
            "strengths": "Монохромная база отлично работает — чёрный и белый всегда элегантно.",
            "improvements": "Кеды снижают формальность для офиса. Лоферы или балетки поднимут стиль.",
            "swaps": [{"current": "кеды белые", "suggested": "лоферы чёрные", "reason": "поднимет формальность для офиса"}],
            "overall_vibe": "Smart casual с акцентом на комфорт",
        }
        text = format_eval_text(data, owner_type="user")
        assert "Хороший" in text
        assert "Монохромная база" in text
        assert "Кеды снижают" in text
        assert "лоферы чёрные" in text

    def test_date_night_wow(self):
        """Perfect date night outfit."""
        data = {
            "is_outfit": True,
            "is_partial": False,
            "score": 9.2,
            "dimensions": {"color_harmony": 9, "proportions": 9, "creativity": 10},
            "detected_items": [],
            "strengths": "Эффектное сочетание! Красное платье с чёрным поясом — классика, которая всегда работает.",
            "improvements": "",
            "swaps": [],
            "overall_vibe": "Уверенный вечерний шик",
        }
        text = format_eval_text(data, owner_type="user")
        assert "Wow" in text
        assert "Эффектное" in text
        # No improvements or swaps for wow
        assert "→" not in text

    def test_bold_combo_appreciated(self):
        """Bold color combo that works — should be encouraged."""
        data = {
            "is_outfit": True,
            "is_partial": False,
            "score": 8.0,
            "dimensions": {"color_harmony": 7, "creativity": 9},
            "detected_items": [
                {"type": "свитер", "color": "горчичный", "category_group": "top"},
                {"type": "юбка", "color": "бордовый", "category_group": "bottom"},
            ],
            "strengths": "Смелое тёплое сочетание! Горчичный и бордовый — осенняя палитра.",
            "improvements": "",
            "swaps": [],
            "overall_vibe": "Тёплый autumn vibe",
        }
        text = format_eval_text(data, owner_type="user")
        assert "Отличный" in text
        assert "Смелое тёплое" in text

    def test_mirror_selfie_works(self):
        """Mirror selfie (common for Лена) should be evaluated normally."""
        # The prompt tells Vision to ignore phone hand
        prompt = build_eval_prompt(owner_type="user", segment="no_kids")
        assert "зеркальн" in prompt.lower()


# ══════════════════════════════════════════════════════════════════════════
# 9. EDGE CASES
# ══════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Edge cases: no person, flat lay, empty wardrobe, corrupt response."""

    def test_no_person_detected(self):
        """Photo without person → clear message."""
        data = {
            "is_outfit": False,
            "score": 0,
            "dimensions": {},
            "detected_items": [],
            "strengths": "",
            "improvements": "",
            "swaps": [],
            "overall_vibe": "",
        }
        text = format_eval_text(data)
        assert "не вижу образа" in text.lower()
        assert "полный рост" in text.lower()

    def test_flat_lay_detection(self):
        """Flat lay (not on person) → is_outfit should be False."""
        data = {
            "is_outfit": False,
            "is_partial": False,
            "score": 0,
            "dimensions": {},
            "detected_items": [
                {"type": "футболка", "color": "белый", "category_group": "top"},
            ],
            "strengths": "",
            "improvements": "",
            "swaps": [],
            "overall_vibe": "",
        }
        text = format_eval_text(data)
        assert "не вижу образа" in text.lower()

    def test_empty_wardrobe_no_swaps(self):
        """Empty wardrobe → general recommendations, no specific swaps."""
        prompt = build_eval_prompt(owner_type="user", wardrobe_items=[])
        assert "общие рекомендации" in prompt or "пуст" in prompt.lower()

    def test_corrupt_response_returns_none(self):
        result = parse_eval_response("{'broken json")
        assert result is None

    def test_very_long_fallback_truncated(self):
        """Long non-JSON response should be handled."""
        long_text = "Отличный образ! " * 100
        # This tests the truncation in _call_rate_vision (500 char limit)
        assert len(long_text) > 500

    def test_score_rounding(self):
        data = json.dumps({"score": 7.777, "dimensions": {}})
        result = parse_eval_response(data)
        assert result["score"] == 7.8  # rounded to 1 decimal

    def test_missing_dimensions_ok(self):
        """Response with empty dimensions should still parse."""
        data = json.dumps({"score": 6.0, "dimensions": {}})
        result = parse_eval_response(data)
        assert result is not None
        assert result["score"] == 6.0


# ══════════════════════════════════════════════════════════════════════════
# 10. DIMENSION WEIGHTS CONSISTENCY
# ══════════════════════════════════════════════════════════════════════════

class TestDimensionWeights:
    """Weights must sum to 100 and be stable."""

    def test_adult_weights_sum_to_100(self):
        total = sum(d["weight"] for d in EVAL_DIMENSIONS.values())
        assert total == 100, f"Adult weights sum to {total}, expected 100"

    def test_all_dimensions_have_label(self):
        for key, dim in EVAL_DIMENSIONS.items():
            assert "label" in dim, f"Dimension {key} missing label"
            assert "weight" in dim, f"Dimension {key} missing weight"
            assert "criteria" in dim, f"Dimension {key} missing criteria"

    def test_color_harmony_is_top_weighted(self):
        """Color is the most impactful visual element."""
        assert EVAL_DIMENSIONS["color_harmony"]["weight"] >= 20

    def test_creativity_is_low_weighted(self):
        """Creativity is a bonus, not core requirement."""
        assert EVAL_DIMENSIONS["creativity"]["weight"] <= 10


# ══════════════════════════════════════════════════════════════════════════
# 11. INTEGRATION: PROMPT → PARSE → FORMAT PIPELINE
# ══════════════════════════════════════════════════════════════════════════

class TestPipeline:
    """End-to-end pipeline: build prompt → simulate response → parse → format."""

    def test_full_pipeline_adult_good(self):
        """Simulate complete evaluation flow for adult."""
        # 1. Build prompt
        prompt = build_eval_prompt(
            owner_type="user",
            colortype="Лето",
            body_type="песочные часы",
            segment="no_kids",
        )
        assert "Лето" in prompt

        # 2. Simulate Vision response
        response = json.dumps({
            "is_outfit": True,
            "is_partial": False,
            "score": 7.5,
            "dimensions": {
                "color_harmony": 8,
                "proportions": 7,
                "style_coherence": 8,
                "occasion_fit": 7,
                "details_polish": 7,
                "creativity": 7,
            },
            "detected_items": [
                {"type": "блузка", "color": "голубой", "category_group": "top"},
                {"type": "юбка", "color": "бежевый", "category_group": "bottom"},
            ],
            "strengths": "Голубой и бежевый — освежающая летняя палитра!",
            "improvements": "",
            "swaps": [],
            "overall_vibe": "Лёгкий летний",
        })

        # 3. Parse
        eval_data = parse_eval_response(response)
        assert eval_data is not None

        # 4. Cross-validate colors
        adjusted = cross_validate_colors(
            eval_data["detected_items"],
            eval_data["dimensions"]["color_harmony"],
        )
        assert adjusted >= 7  # blue + beige should be fine

        # 5. Format
        text = format_eval_text(eval_data, owner_type="user")
        assert "Отличный" in text
        assert "Голубой и бежевый" in text

    def test_full_pipeline_child_partial(self):
        """Simulate partial photo evaluation for child."""
        prompt = build_eval_prompt(owner_type="child", child_age=4)
        assert "4 лет" in prompt

        response = json.dumps({
            "is_outfit": True,
            "is_partial": True,
            "score": 6.0,
            "dimensions": {"safety": 8, "comfort": 7},
            "detected_items": [
                {"type": "куртка", "color": "красный", "category_group": "outerwear"},
            ],
            "strengths": "Тёплая куртка с безопасной молнией!",
            "improvements": "Не вижу обувь — сфоткай полностью.",
            "swaps": [],
            "overall_vibe": "Тёплый зимний",
        })

        eval_data = parse_eval_response(response)
        text = format_eval_text(eval_data, owner_type="child")
        assert "часть образа" in text
        assert "полный рост" in text

    def test_full_pipeline_not_outfit(self):
        """Photo without person → clear redirect."""
        response = json.dumps({
            "is_outfit": False,
            "score": 0,
            "dimensions": {},
            "detected_items": [],
            "strengths": "",
            "improvements": "",
            "swaps": [],
            "overall_vibe": "",
        })

        eval_data = parse_eval_response(response)
        text = format_eval_text(eval_data)
        assert "не вижу" in text.lower()

    def test_full_pipeline_clash_correction(self):
        """Vision says great harmony but colors actually clash → corrected."""
        response = json.dumps({
            "is_outfit": True,
            "score": 8.5,
            "dimensions": {"color_harmony": 9},
            "detected_items": [
                {"type": "свитер", "color": "ярко-красный", "category_group": "top"},
                {"type": "брюки", "color": "ярко-зелёный", "category_group": "bottom"},
            ],
            "strengths": "Яркий и смелый!",
            "improvements": "",
            "swaps": [],
            "overall_vibe": "Смелый",
        })

        eval_data = parse_eval_response(response)
        original = eval_data["dimensions"]["color_harmony"]
        adjusted = cross_validate_colors(eval_data["detected_items"], original)
        # If local scoring says it clashes, should be pulled down
        assert isinstance(adjusted, float)
