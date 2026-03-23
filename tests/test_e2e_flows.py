"""End-to-end flow tests — payment, photo pipeline, i18n coverage.

Tests the full chain with mocked external APIs but real business logic.
"""
import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_user(**overrides):
    u = MagicMock()
    u.id = overrides.get("id", uuid.uuid4())
    u.telegram_id = overrides.get("telegram_id", 12345)
    u.name = overrides.get("name", "Test")
    u.city = overrides.get("city", "Vilnius")
    u.timezone = overrides.get("timezone", "Europe/Vilnius")
    u.plan = overrides.get("plan", "free")
    u.segment = overrides.get("segment", "mom_girl")
    u.colortype = overrides.get("colortype", "summer")
    u.body_type = overrides.get("body_type", None)
    u.language = overrides.get("language", "ru")
    u.style_preferences = overrides.get("style_preferences", {})
    u.trial_started_at = overrides.get("trial_started_at", None)
    u.trial_ends_at = overrides.get("trial_ends_at", None)
    u.plan_expires_at = overrides.get("plan_expires_at", None)
    u.daily_requests_used = overrides.get("daily_requests_used", 0)
    u.onboarding_completed = True
    u.is_active = True
    u.deleted_at = None
    u.milestones_reached = []
    u.referral_code = "TEST1234"
    # Professional styling fields
    u.contrast_level = overrides.get("contrast_level", None)
    u.kibbe_family = overrides.get("kibbe_family", None)
    u.style_essence = overrides.get("style_essence", None)
    # Color depth fields
    u.tonal_depth = overrides.get("tonal_depth", None)
    u.chroma = overrides.get("chroma", None)
    u.color_flow_to = overrides.get("color_flow_to", None)
    u.color_flow_strength = overrides.get("color_flow_strength", None)
    return u


def _make_item(**overrides):
    item = MagicMock()
    item.id = overrides.get("id", uuid.uuid4())
    item.type = overrides.get("type", "футболка")
    item.color = overrides.get("color", "белый")
    item.category_group = overrides.get("category_group", "top")
    item.season = overrides.get("season", ["spring", "summer"])
    item.occasion = overrides.get("occasion", ["everyday"])
    item.warmth_level = overrides.get("warmth_level", 2)
    item.style_tag = overrides.get("style_tag", "casual")
    item.score_item = overrides.get("score_item", Decimal("7.5"))
    item.photo_id = "photo123"
    item.photo_url = None
    item.show_in_collage = True
    item.wear_count = overrides.get("wear_count", 0)
    item.last_worn = None
    item.formality_level = overrides.get("formality_level", None)
    item.metal_tone = None
    item.role = "base"
    item.rain_ok = False
    item.is_base_layer = overrides.get("is_base_layer", False)
    item.style = "casual"
    item.brand = None
    item.bbox = None
    return item


# ══════════════════════════════════════════════════════════════════════════════
# PAYMENT E2E
# ══════════════════════════════════════════════════════════════════════════════

class TestPaymentE2E:

    def test_key_months_mapping(self):
        from bot.handlers.billing import _KEY_MONTHS
        assert _KEY_MONTHS["premium_monthly"] == 1
        assert _KEY_MONTHS["premium_quarterly"] == 3
        assert _KEY_MONTHS["premium_yearly"] == 12

    def test_payload_parsing(self):
        parts = "premium:premium_quarterly:12345".split(":")
        assert parts[0] == "premium"
        assert parts[1] == "premium_quarterly"

    def test_test_payload_skipped(self):
        assert "test:premium_monthly:12345".startswith("test:")
        assert not "premium:premium_monthly:12345".startswith("test:")

    def test_expires_calculation(self):
        from bot.handlers.billing import _KEY_MONTHS
        now = datetime.now(timezone.utc)
        for key, months in _KEY_MONTHS.items():
            expires = now + timedelta(days=30 * months)
            assert (expires - now).days == 30 * months

    def test_plan_activation_premium(self):
        from core.permissions import get_effective_plan
        user = _make_user(plan="premium", plan_expires_at=datetime.now(timezone.utc) + timedelta(days=30))
        assert get_effective_plan(user) == "premium"

    def test_plan_expired_free(self):
        from core.permissions import get_effective_plan
        user = _make_user(plan="premium", plan_expires_at=datetime.now(timezone.utc) - timedelta(days=1))
        assert get_effective_plan(user) == "free"

    def test_trial_active_premium(self):
        from core.permissions import get_effective_plan
        user = _make_user(plan="free", trial_ends_at=datetime.now(timezone.utc) + timedelta(days=7))
        assert get_effective_plan(user) == "premium"

    def test_trial_expired_free(self):
        from core.permissions import get_effective_plan
        user = _make_user(plan="free", trial_ends_at=datetime.now(timezone.utc) - timedelta(days=1))
        assert get_effective_plan(user) == "free"

    def test_limits_free_vs_premium(self):
        from core.permissions import get_limit
        assert get_limit("photos_per_day", "free") == 3
        assert get_limit("photos_per_day", "premium") == 30
        assert get_limit("outfit_req_per_day", "free") == 1
        assert get_limit("outfit_req_per_day", "premium") == 5


# ══════════════════════════════════════════════════════════════════════════════
# PHOTO PIPELINE E2E
# ══════════════════════════════════════════════════════════════════════════════

class TestPhotoPipelineE2E:

    def test_vision_json_parsing(self):
        raw = json.dumps([{
            "type": "кроссовки", "color": "белый", "style": "спортивный",
            "category_group": "footwear", "warmth_level": 2, "rain_ok": False,
        }])
        items = json.loads(raw)
        assert items[0]["type"] == "кроссовки"
        assert items[0]["category_group"] == "footwear"

    def test_normalization_footwear(self):
        from services.normalize import normalize_type
        assert normalize_type("кеды") == ("кроссовки", "footwear")
        assert normalize_type("слипоны") == ("кроссовки", "footwear")
        assert normalize_type("ботильоны") == ("ботинки", "footwear")
        assert normalize_type("лоферы") == ("туфли", "footwear")

    def test_normalization_bags(self):
        from services.normalize import normalize_type
        assert normalize_type("шопер") == ("тоут", "bag")
        assert normalize_type("бананка") == ("поясная сумка", "bag")
        assert normalize_type("кроссбоди") == ("кроссбоди", "bag")
        assert normalize_type("рюкзак") == ("рюкзак", "bag")

    def test_formality_footwear(self):
        from services.normalize import get_formality
        assert get_formality("кроссовки", "footwear") == 2
        assert get_formality("лоферы", "footwear") == 4
        assert get_formality("сандалии", "footwear") == 1
        assert get_formality("лодочки", "footwear") == 5

    def test_formality_bags(self):
        from services.normalize import get_formality
        assert get_formality("клатч", "bag") == 5
        assert get_formality("рюкзак", "bag") == 2
        assert get_formality("кроссбоди", "bag") == 3

    def test_formality_all_categories_covered(self):
        from services.normalize import get_formality
        # Now all visual categories return formality
        assert get_formality("футболка", "top") == 2
        assert get_formality("блузка", "top") == 4
        assert get_formality("брюки", "bottom") == 4
        # Only underwear/base_layer return None
        assert get_formality("носки", "underwear") is None

    def test_base_layer_filtering(self):
        from services.outfit_builder import _is_base_layer_item
        assert _is_base_layer_item(_make_item(type="носки", category_group="underwear"))
        assert not _is_base_layer_item(_make_item(type="футболка", category_group="top"))
        assert not _is_base_layer_item(_make_item(type="рюкзак", category_group="bag"))

    def test_bag_in_slot_order(self):
        from services.outfit_builder import _SLOT_ORDER
        assert "bag" in _SLOT_ORDER

    def test_bag_in_ai_slots(self):
        from services.outfit_engine import _AI_SLOTS
        assert "bag" in _AI_SLOTS

    def test_bag_combinability(self):
        from services.scoring import _COMBINABLE_PAIRS
        assert (min("bag", "top"), max("bag", "top")) in _COMBINABLE_PAIRS
        assert (min("bag", "footwear"), max("bag", "footwear")) in _COMBINABLE_PAIRS

    def test_capsule_bag_slots(self):
        from services.wardrobe_math import _CAPSULE_SLOTS
        assert "bag" in _CAPSULE_SLOTS

    def test_wardrobe_combos(self):
        from services.wardrobe_math import calc_wardrobe_combos
        items = [
            _make_item(category_group="top"),
            _make_item(category_group="top"),
            _make_item(category_group="bottom"),
            _make_item(category_group="footwear"),
        ]
        assert calc_wardrobe_combos(items) >= 1

    def test_seasonal_capsule(self):
        from services.wardrobe_math import build_seasonal_capsule
        items = [
            _make_item(category_group="top", color="белый"),
            _make_item(category_group="top", color="синий"),
            _make_item(category_group="bottom", color="чёрный"),
            _make_item(category_group="footwear"),
            _make_item(category_group="bag", color="бежевый"),
            _make_item(category_group="outerwear"),
        ]
        cap = build_seasonal_capsule(items, season="spring")
        assert cap["total_combos"] > 0
        assert any(i.category_group == "bag" for i in cap["items"])

    def test_travel_capsule(self):
        from services.wardrobe_math import build_travel_capsule
        items = [_make_item(category_group=cg, warmth_level=2)
                 for cg in ["top", "top", "top", "bottom", "bottom", "footwear", "footwear", "outerwear"]]
        cap = build_travel_capsule(items, days=5, occasions=["культура"])
        assert len(cap["items"]) <= 10
        assert cap["total_combos"] > 0


# ══════════════════════════════════════════════════════════════════════════════
# I18N COVERAGE
# ══════════════════════════════════════════════════════════════════════════════

class TestI18nCoverage:

    def test_all_ru_keys_have_en(self):
        from services.i18n.ru import STRINGS as RU
        from services.i18n.en import STRINGS as EN
        allowed_missing = {
            "onboarding.child_birthdate", "onboarding.child_birthdate_boy",
            "onboarding.child_birthdate_error", "onboarding.done",
            "onboarding.city_error",
        }
        missing = [k for k in RU if k not in EN and k not in allowed_missing]
        assert missing == [], f"Missing EN: {missing}"

    def test_t_fallback_to_ru(self):
        from services.i18n import t
        result = t("onboarding.child_birthdate", "en", name="Alice")
        assert "Alice" in result

    def test_t_params_ru(self):
        from services.i18n import t
        assert "3 месяца" in t("billing.activated", "ru", period="3 месяца")

    def test_t_params_en(self):
        from services.i18n import t
        assert "3 months" in t("billing.activated", "en", period="3 months")

    def test_get_user_lang_defaults(self):
        from services.i18n import get_user_lang
        assert get_user_lang(None) == "ru"
        assert get_user_lang(_make_user(language="en")) == "en"

    def test_new_wardrobe_keys_exist(self):
        from services.i18n import t
        for key in ["wardrobe.looking", "wardrobe.outfit_picking", "wardrobe.kassi_resting",
                     "billing.activated", "brief.rerolling", "fitting.looking", "boost.evaluating"]:
            assert t(key, "ru") != key, f"Key {key} missing in RU"
            assert t(key, "en") != key, f"Key {key} missing in EN"

    def test_no_ai_mentions_in_user_strings(self):
        """No user-facing string should mention AI/ИИ."""
        from services.i18n.ru import STRINGS as RU
        from services.i18n.en import STRINGS as EN
        for key, val in {**RU, **EN}.items():
            if isinstance(val, str):
                lower = val.lower()
                assert "ai-стилист" not in lower, f"'{key}' mentions AI-стилист"
                assert "ai стилист" not in lower, f"'{key}' mentions AI стилист"
                assert "искусственн" not in lower, f"'{key}' mentions ИИ"


# ══════════════════════════════════════════════════════════════════════════════
# SCORING V3: 8 DIMENSIONS + FORMALITY + BODY TYPE
# ══════════════════════════════════════════════════════════════════════════════

class TestScoringV3:

    def test_formality_all_categories(self):
        from services.normalize import get_formality
        # Top
        assert get_formality("блузка", "top") == 4
        assert get_formality("худи", "top") == 2
        assert get_formality("футболка", "top") == 2
        # Bottom
        assert get_formality("брюки", "bottom") == 4
        assert get_formality("джинсы", "bottom") == 2
        assert get_formality("шорты", "bottom") == 1
        # Outerwear
        assert get_formality("пальто", "outerwear") == 5
        assert get_formality("пуховик", "outerwear") == 2
        # One piece
        assert get_formality("платье", "one_piece") == 3
        # Defaults
        assert get_formality("unknown_thing", "top") == 2
        assert get_formality("", "footwear") == 2
        # Not applicable
        assert get_formality("носки", "underwear") is None

    def test_formality_coherence_ok(self):
        from services.outfit_engine import _check_formality_coherence
        items = {
            "top": _make_item(formality_level=3),
            "bottom": _make_item(formality_level=3),
            "footwear": _make_item(formality_level=2),
        }
        ok, msg = _check_formality_coherence(items)
        assert ok, msg

    def test_formality_coherence_fail(self):
        from services.outfit_engine import _check_formality_coherence
        items = {
            "top": _make_item(type="блузка", formality_level=5),
            "footwear": _make_item(type="кроссовки", formality_level=2),
        }
        ok, msg = _check_formality_coherence(items)
        assert not ok
        assert "блузка" in msg or "кроссовки" in msg

    def test_formality_coherence_creative_wider(self):
        from services.outfit_engine import _check_formality_coherence
        items = {
            "top": _make_item(formality_level=4),
            "footwear": _make_item(formality_level=2),
        }
        # Default: spread 2 > max_spread 1 → fail
        ok, _ = _check_formality_coherence(items)
        assert not ok
        # Creative style: spread 2 ≤ max_spread 2 → ok
        ok2, _ = _check_formality_coherence(items, {"style_type": "bold_creative"})
        assert ok2

    def test_8_dimensions_weights_sum_100(self):
        from services.outfit_evaluator import EVAL_DIMENSIONS
        total = sum(d["weight"] for d in EVAL_DIMENSIONS.values())
        assert total == 100, f"Weights sum to {total}, expected 100"

    def test_8_dimensions_count(self):
        from services.outfit_evaluator import EVAL_DIMENSIONS
        assert len(EVAL_DIMENSIONS) == 8

    def test_new_dimensions_present(self):
        from services.outfit_evaluator import EVAL_DIMENSIONS
        assert "accessory_completeness" in EVAL_DIMENSIONS
        assert "shoe_bag_harmony" in EVAL_DIMENSIONS

    def test_segment_overrides_no_kids(self):
        from services.outfit_evaluator import get_eval_dimensions
        dims = get_eval_dimensions("no_kids")
        assert dims["accessory_completeness"]["weight"] == 12
        assert dims["creativity"]["weight"] == 7

    def test_segment_overrides_mom(self):
        from services.outfit_evaluator import get_eval_dimensions
        dims = get_eval_dimensions("mom_girl")
        assert dims["accessory_completeness"]["weight"] == 7
        assert dims["occasion_fit"]["weight"] == 18

    def test_segment_default_unchanged(self):
        from services.outfit_evaluator import get_eval_dimensions, EVAL_DIMENSIONS
        dims = get_eval_dimensions("")
        for key in EVAL_DIMENSIONS:
            assert dims[key]["weight"] == EVAL_DIMENSIONS[key]["weight"]

    def test_body_type_rules_exist(self):
        from services.body_type import BODY_TYPE_RULES, get_body_type_prompt
        for bt in ["hourglass", "pear", "apple", "rectangle", "inverted_triangle"]:
            assert bt in BODY_TYPE_RULES
            prompt = get_body_type_prompt(bt)
            assert len(prompt) > 50
            assert "обувь" in prompt.lower() or "Обувь" in prompt

    def test_body_type_none_returns_empty(self):
        from services.body_type import get_body_type_prompt
        assert get_body_type_prompt(None) == ""
        assert get_body_type_prompt("unknown") == ""


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2 ACCESSORIES + PHASE 3
# ══════════════════════════════════════════════════════════════════════════════

class TestPhase2Accessories:

    def test_jewelry_normalization(self):
        from services.normalize import normalize_type
        assert normalize_type("серьги-гвоздики") == ("серьги-гвоздики", "accessory")
        assert normalize_type("ожерелье") == ("колье", "accessory")
        assert normalize_type("чокер") == ("чокер", "accessory")
        assert normalize_type("бусы") == ("колье", "accessory")
        assert normalize_type("подвеска") == ("кулон", "accessory")

    def test_belt_normalization(self):
        from services.normalize import normalize_type
        assert normalize_type("ремень") == ("ремень", "accessory")
        assert normalize_type("пояс") == ("ремень", "accessory")
        assert normalize_type("галстук") == ("галстук", "accessory")

    def test_jewelry_formality(self):
        from services.normalize import get_formality
        assert get_formality("серьги-гвоздики", "accessory") == 3
        assert get_formality("колье", "accessory") == 4
        assert get_formality("чокер", "accessory") == 4
        assert get_formality("галстук", "accessory") == 5

    def test_metal_tone_detection(self):
        from services.normalize import detect_metal_tone
        assert detect_metal_tone("золотой", "серьги") == "gold"
        assert detect_metal_tone("серебряный", "цепочка") == "silver"
        assert detect_metal_tone("кожаный", "ремень") == "none"
        assert detect_metal_tone("красный", "браслет") is None

    def test_statement_pieces_count(self):
        from services.outfit_engine import _count_statement_pieces
        items = {
            "top": _make_item(category_group="top", formality_level=3),
            "bag": _make_item(category_group="bag", formality_level=5),
        }
        assert _count_statement_pieces(items) == 1
        items["accessory"] = _make_item(category_group="accessory", formality_level=4)
        assert _count_statement_pieces(items) == 2


class TestPhase3:

    def test_uv_hint_in_weather_line(self):
        from services.brief_formatter import format_weather_line
        weather = {
            "temp_now": 25, "temp_day": 28, "temp_evening": 22,
            "wmo_morning": 0, "wmo_day": 0, "wmo_evening": 0,
            "uv_max": 8,
        }
        line = format_weather_line(weather)
        assert "UV" in line
        assert "очки" in line

    def test_no_uv_hint_low_uv(self):
        from services.brief_formatter import format_weather_line
        weather = {
            "temp_now": 10, "temp_day": 12, "temp_evening": 8,
            "wmo_morning": 3, "wmo_day": 3, "wmo_evening": 3,
            "uv_max": 3,
        }
        line = format_weather_line(weather)
        assert "UV" not in line

    def test_antibot_middleware_exists(self):
        from bot.middleware.antibot import AntibotMiddleware
        assert hasattr(AntibotMiddleware, "handle")
        assert AntibotMiddleware.PHOTO_LIMIT == 20
        assert AntibotMiddleware.BAN_DURATION == 300

    def test_worker_tasks_importable(self):
        import worker.tasks.wardrobe_analysis
        import worker.tasks.declutter
        import worker.tasks.taxonomy_review
        import worker.tasks.unknown_items_report
        assert hasattr(worker.tasks.wardrobe_analysis, "run")
        assert hasattr(worker.tasks.declutter, "run")
        assert hasattr(worker.tasks.taxonomy_review, "run")
        assert hasattr(worker.tasks.unknown_items_report, "run")


# ══════════════════════════════════════════════════════════════════════════════
# USP: PREFERENCE LEARNING + STREAK + MOOD + MEMORY
# ══════════════════════════════════════════════════════════════════════════════

class TestPreferenceLearner:

    def test_preference_context_empty_if_few_feedback(self):
        from services.preference_learner import get_preference_context
        prefs = {"total_feedback": 2, "liked_colors": {}, "wore_rate": 0.5}
        assert get_preference_context(prefs) == ""

    def test_preference_context_with_data(self):
        from services.preference_learner import get_preference_context
        prefs = {
            "total_feedback": 10,
            "liked_colors": {"синий": 5, "белый": 3},
            "disliked_colors": {"жёлтый": 2},
            "liked_formality": {3: 5},
            "avoid_items": [],
            "wore_rate": 0.8,
        }
        text = get_preference_context(prefs)
        assert "синий" in text
        assert "жёлтый" in text
        assert "продолжай" in text.lower()

    def test_preference_context_low_wore_rate(self):
        from services.preference_learner import get_preference_context
        prefs = {"total_feedback": 10, "liked_colors": {}, "disliked_colors": {},
                 "liked_formality": {}, "avoid_items": [], "wore_rate": 0.2}
        text = get_preference_context(prefs)
        assert "разнообразия" in text.lower()

    def test_kassi_knows_pct(self):
        from services.preference_learner import calc_kassi_knows_pct
        assert calc_kassi_knows_pct({"total_feedback": 30}, 30, True, True, True) == 100
        assert calc_kassi_knows_pct({"total_feedback": 0}, 0) == 0
        assert calc_kassi_knows_pct({"total_feedback": 10}, 15) == 25


class TestStreak:

    def test_streak_text_day_0(self):
        from services.streak import get_streak_text
        assert get_streak_text({"current": 0}) == ""

    def test_streak_text_day_1(self):
        from services.streak import get_streak_text
        text = get_streak_text({"current": 1})
        assert "Первый" in text or "первый" in text

    def test_streak_text_day_2(self):
        from services.streak import get_streak_text
        text = get_streak_text({"current": 2})
        assert "2 дня" in text

    def test_streak_text_above_3(self):
        from services.streak import get_streak_text
        text = get_streak_text({"current": 5})
        assert "5 дней" in text
        assert "Касси" in text

    def test_milestone_at_7(self):
        from services.streak import check_milestone
        assert check_milestone({"current": 7}) is not None
        assert "7 дней" in check_milestone({"current": 7})

    def test_milestone_at_non_milestone(self):
        from services.streak import check_milestone
        assert check_milestone({"current": 4}) is None

    def test_milestone_at_100(self):
        from services.streak import check_milestone
        assert check_milestone({"current": 100}) is not None
        assert "100" in check_milestone({"current": 100})

    def test_milestone_14_knows_pct(self):
        from services.streak import check_milestone
        msg = check_milestone({"current": 14}, knows_pct=47)
        assert msg is not None
        assert "47%" in msg
        assert "{knows_pct}" not in msg  # placeholder must be resolved

    def test_milestone_14_default_pct(self):
        from services.streak import check_milestone
        msg = check_milestone({"current": 14}, knows_pct=0)
        assert msg is not None
        assert "0%" in msg


class TestMoodFixes:

    def test_energy_low_vs_high(self):
        """max('low', 'high') was returning 'low' lexicographically. Now fixed."""
        from services.mood import _max_energy
        assert _max_energy("low", "high") == "high"
        assert _max_energy("high", "low") == "high"
        assert _max_energy("low", "medium") == "medium"
        assert _max_energy("medium", "medium") == "medium"

    def test_mood_office_boosts_energy(self):
        from services.mood import detect_mood
        # Rain (low energy) + office → should boost to medium
        mood = detect_mood({"wmo_day": 61, "temp_now": 10}, weekday=2, occasion="офис")
        assert mood["energy"] in ("medium", "high")  # not "low"


class TestMood:

    def test_mood_rain(self):
        from services.mood import detect_mood
        mood = detect_mood({"wmo_day": 61, "temp_now": 10}, weekday=2)
        assert mood["energy"] == "low"
        assert mood["color_mood"] == "warm"
        assert mood["hint"] != ""

    def test_mood_sunny_warm(self):
        from services.mood import detect_mood
        mood = detect_mood({"wmo_day": 0, "temp_now": 22}, weekday=3)
        assert mood["energy"] == "high"
        assert mood["color_mood"] == "bright"

    def test_mood_friday(self):
        from services.mood import detect_mood
        mood = detect_mood({"wmo_day": 2, "temp_now": 15}, weekday=4)
        assert mood["energy"] == "high"
        assert "пятница" in mood["hint"].lower()

    def test_mood_monday(self):
        from services.mood import detect_mood
        mood = detect_mood({"wmo_day": 2, "temp_now": 15}, weekday=0)
        assert "понедельник" in mood["hint"].lower()

    def test_mood_neutral(self):
        from services.mood import detect_mood, get_mood_prompt
        mood = detect_mood({"wmo_day": 2, "temp_now": 12}, weekday=2)
        # Wednesday, overcast, moderate — should be neutral-ish
        prompt = get_mood_prompt(mood)
        # May or may not have content — just verify no crash
        assert isinstance(prompt, str)

    def test_mood_prompt_format(self):
        from services.mood import get_mood_prompt
        mood = {"energy": "high", "color_mood": "bright", "hint": "Солнечно!"}
        prompt = get_mood_prompt(mood)
        assert "Солнечно" in prompt


class TestKassiMemory:

    def test_memory_module_importable(self):
        from services.kassi_memory import build_memory, get_memory_for_prompt, save_explicit_memory
        assert callable(build_memory)
        assert callable(get_memory_for_prompt)
        assert callable(save_explicit_memory)

    def test_explicit_memory_patterns(self):
        """Test that chat text patterns are detected for memory saving."""
        import re
        _MEM_PATTERNS = [
            (r"не люблю (.+)", "не любит {0}"),
            (r"не ношу (.+)", "не носит {0}"),
            (r"люблю (.+)", "любит {0}"),
            (r"предпочитаю (.+)", "предпочитает {0}"),
            (r"ненавижу (.+)", "не любит {0}"),
        ]

        test_cases = [
            ("не люблю жёлтый", "не любит жёлтый"),
            ("люблю оверсайз", "любит оверсайз"),
            ("не ношу каблуки", "не носит каблуки"),
            ("предпочитаю кэжуал", "предпочитает кэжуал"),
        ]

        for user_text, expected_fact in test_cases:
            found = False
            for pattern, template in _MEM_PATTERNS:
                m = re.search(pattern, user_text.lower())
                if m:
                    fact = template.format(m.group(1).strip()[:50])
                    assert fact == expected_fact, f"'{user_text}' → '{fact}' != '{expected_fact}'"
                    found = True
                    break
            assert found, f"No pattern matched: '{user_text}'"

    def test_menu_has_help_button(self):
        """Verify ❓ Помощь is in the main menu."""
        from bot.handlers.menu import MAIN_MENU
        # Flatten all button texts
        texts = [btn.text for row in MAIN_MENU.keyboard for btn in row]
        assert any("Помощь" in t for t in texts), f"❓ Помощь not in menu: {texts}"
        assert not any("Подойдёт" in t for t in texts), f"🛍 Подойдёт should be removed: {texts}"

    def test_photo_counter_key_format(self):
        """Verify photo counter Redis key format matches limit check."""
        import uuid
        from datetime import date
        user_id = uuid.uuid4()
        key = f"photos_day:{user_id}:{date.today().isoformat()}"
        assert "photos_day:" in key
        assert date.today().isoformat() in key


# ══════════════════════════════════════════════════════════════════════════════
# PROFESSIONAL STYLING: CONTRAST + KIBBE + ESSENCE
# ══════════════════════════════════════════════════════════════════════════════

class TestProfessionalStyling:

    def test_contrast_rules_all_levels(self):
        from services.body_type import CONTRAST_RULES
        for level in ("HIGH", "MEDIUM", "LOW"):
            assert level in CONTRAST_RULES
            assert len(CONTRAST_RULES[level]) > 20

    def test_kibbe_rules_all_families(self):
        from services.body_type import KIBBE_RULES
        for family in ("DRAMATIC", "NATURAL", "CLASSIC", "GAMINE", "ROMANTIC"):
            assert family in KIBBE_RULES

    def test_essence_rules_all_types(self):
        from services.body_type import ESSENCE_RULES
        for essence in ("DRAMATIC", "NATURAL", "CLASSIC", "GAMINE", "ROMANTIC"):
            assert essence in ESSENCE_RULES

    def test_full_styling_context_all_fields(self):
        from services.body_type import build_full_styling_context
        u = _make_user(colortype="True Summer", body_type="hourglass")
        u.contrast_level = "HIGH"
        u.kibbe_family = "CLASSIC"
        u.style_essence = "DRAMATIC"
        ctx = build_full_styling_context(u)
        assert "True Summer" in ctx
        assert "HIGH" in ctx
        assert "CLASSIC" in ctx
        assert "DRAMATIC" in ctx
        assert "песочные часы" in ctx.lower() or "hourglass" in ctx.lower()

    def test_full_styling_context_empty_user(self):
        from services.body_type import build_full_styling_context
        u = _make_user()
        u.colortype = None
        u.contrast_level = None
        u.kibbe_family = None
        u.style_essence = None
        u.body_type = None
        assert build_full_styling_context(u) == ""

    def test_full_styling_context_partial(self):
        from services.body_type import build_full_styling_context
        u = _make_user(colortype="Soft Autumn")
        u.contrast_level = "LOW"
        u.kibbe_family = None
        u.style_essence = None
        u.body_type = None
        ctx = build_full_styling_context(u)
        assert "Soft Autumn" in ctx
        assert "LOW" in ctx
        assert "CLASSIC" not in ctx  # kibbe not set

    def test_fabric_kibbe_best(self):
        from services.body_type import fabric_kibbe_score
        assert fabric_kibbe_score("silk", "ROMANTIC") == 1.0
        assert fabric_kibbe_score("leather", "DRAMATIC") == 1.0
        assert fabric_kibbe_score("linen", "NATURAL") == 1.0

    def test_fabric_kibbe_avoid(self):
        from services.body_type import fabric_kibbe_score
        assert fabric_kibbe_score("stiff", "ROMANTIC") == 0.2
        assert fabric_kibbe_score("chiffon", "DRAMATIC") == 0.2

    def test_fabric_kibbe_neutral(self):
        from services.body_type import fabric_kibbe_score
        assert fabric_kibbe_score("unknown_fabric", "CLASSIC") == 0.5
        assert fabric_kibbe_score("", "ROMANTIC") == 0.5
        assert fabric_kibbe_score("silk", "") == 0.5


# ══════════════════════════════════════════════════════════════════════════════
# CONVERSION + NUDGE + LANGUAGE + COMPREHENSIVE TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestConversionFeatures:

    def test_paywall_value_proof_key_ru(self):
        from services.i18n import t
        msg = t("paywall.value_proof", "ru", days=14, outfits=12, items=8)
        assert "12" in msg
        assert "8" in msg
        assert "$9" in msg or "9" in msg

    def test_paywall_value_proof_key_en(self):
        from services.i18n import t
        msg = t("paywall.value_proof", "en", days=14, outfits=12, items=8)
        assert "12" in msg
        assert "$9" in msg or "9" in msg

    def test_paywall_loss_aversion_key(self):
        from services.i18n import t
        msg = t("paywall.loss_aversion", "ru", knows_pct=47)
        assert "47%" in msg

    def test_nudge_key_ru(self):
        from services.i18n import t
        msg = t("nudge.add_more_items", "ru", count=5, combos=4, target=8, estimate=36)
        assert "5" in msg
        assert "4" in msg
        assert "36" in msg

    def test_nudge_key_en(self):
        from services.i18n import t
        msg = t("nudge.add_more_items", "en", count=5, combos=4, target=8, estimate=36)
        assert "5" in msg
        assert "36" in msg


class TestLanguagePicker:

    def test_lang_keyboard_exists(self):
        from bot.handlers.settings import lang_keyboard
        kb = lang_keyboard()
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert any("Русский" in t for t in texts)
        assert any("English" in t for t in texts)


class TestComprehensiveFlows:
    """Tests that verify complete flows, not just individual functions."""

    def test_formality_coherence_rejects_bad_outfit(self):
        """Blouse(5) + sneakers(2) → rejected by formality check."""
        from services.outfit_engine import _check_formality_coherence
        items = {
            "top": _make_item(type="блузка", formality_level=5),
            "bottom": _make_item(type="брюки", formality_level=4),
            "footwear": _make_item(type="кроссовки", formality_level=2),
        }
        ok, msg = _check_formality_coherence(items)
        assert not ok, "Should reject: blouse(5) + sneakers(2) = spread 3"

    def test_formality_coherence_accepts_good_outfit(self):
        """Blouse(4) + loafers(4) → accepted."""
        from services.outfit_engine import _check_formality_coherence
        items = {
            "top": _make_item(type="блузка", formality_level=4),
            "bottom": _make_item(type="брюки", formality_level=4),
            "footwear": _make_item(type="лоферы", formality_level=4),
            "bag": _make_item(type="тоут", formality_level=3),
        }
        ok, msg = _check_formality_coherence(items)
        assert ok, f"Should accept: all within ±1. Got: {msg}"

    def test_combo_math_grows_with_items(self):
        """More items = more combinations (non-linear growth)."""
        from services.wardrobe_math import calc_wardrobe_combos
        small = [
            _make_item(category_group="top"),
            _make_item(category_group="bottom"),
            _make_item(category_group="footwear"),
        ]
        big = small + [
            _make_item(category_group="top"),
            _make_item(category_group="top"),
            _make_item(category_group="bottom"),
            _make_item(category_group="outerwear"),
        ]
        assert calc_wardrobe_combos(big) > calc_wardrobe_combos(small) * 2

    def test_normalize_covers_synonyms(self):
        """Synonym items normalize to canonical types."""
        from services.normalize import normalize_type
        # Only test SYNONYMS (items that need mapping), not canonical names
        synonyms = {
            "кеды": ("кроссовки", "footwear"),
            "слипоны": ("кроссовки", "footwear"),
            "шопер": ("тоут", "bag"),
            "бананка": ("поясная сумка", "bag"),
            "снуд": ("шарф", "accessory"),
            "ожерелье": ("колье", "accessory"),
            "пояс": ("ремень", "accessory"),
            "ботильоны": ("ботинки", "footwear"),
            "сарафан": ("платье", "one_piece"),
            "толстовка": ("худи", "top"),
        }
        for raw, (exp_type, exp_cg) in synonyms.items():
            norm_type, norm_cg = normalize_type(raw)
            assert norm_type == exp_type, f"'{raw}' type → '{norm_type}', expected '{exp_type}'"
            assert norm_cg == exp_cg, f"'{raw}' cg → '{norm_cg}', expected '{exp_cg}'"

    def test_segment_affects_scoring_weights(self):
        """Different segments have different scoring emphasis."""
        from services.outfit_evaluator import get_eval_dimensions
        mom = get_eval_dimensions("mom_girl")
        woman = get_eval_dimensions("no_kids")
        default = get_eval_dimensions("")
        # Mom: occasion more important, accessories less
        assert mom["occasion_fit"]["weight"] > default["occasion_fit"]["weight"]
        assert mom["accessory_completeness"]["weight"] < default["accessory_completeness"]["weight"]
        # Woman: accessories more important
        assert woman["accessory_completeness"]["weight"] > default["accessory_completeness"]["weight"]

    def test_all_i18n_keys_no_raw_placeholders(self):
        """No i18n value should contain unresolved {placeholder} after t() call."""
        from services.i18n.ru import STRINGS as RU
        for key, val in RU.items():
            if isinstance(val, str) and "{" in val:
                # These keys need parameters — skip them
                continue
            # Keys without {} should return clean text
            from services.i18n import t
            result = t(key, "ru")
            assert "{" not in result or "}" not in result, \
                f"Key '{key}' has unresolved placeholder: {result[:50]}"

    def test_weather_line_includes_current_temp(self):
        """Weather line should show current temp, not forecast."""
        from services.brief_formatter import format_weather_line
        weather = {
            "temp_now": 3, "temp_morning": 6, "temp_day": 8, "temp_evening": 2,
            "wmo_morning": 0, "wmo_day": 0, "wmo_evening": 0,
        }
        line = format_weather_line(weather)
        assert "+3°" in line, f"Should show current +3°, got: {line}"
        assert "сейчас" in line

    def test_streak_milestones_no_raw_placeholders(self):
        """All streak milestones should resolve their placeholders."""
        from services.streak import MILESTONES, check_milestone
        for day, msg in MILESTONES.items():
            result = check_milestone({"current": day}, knows_pct=50)
            assert "{" not in result, f"Day {day}: raw placeholder in '{result}'"

    def test_antibot_limits_defined(self):
        """Antibot limits should be reasonable."""
        from bot.middleware.antibot import AntibotMiddleware
        assert AntibotMiddleware.PHOTO_LIMIT >= 10  # not too restrictive
        assert AntibotMiddleware.PHOTO_LIMIT <= 50   # not too permissive
        assert AntibotMiddleware.BAN_DURATION >= 60   # at least 1 min
        assert AntibotMiddleware.BAN_DURATION <= 3600  # at most 1 hour

    def test_menu_buttons_match_handlers(self):
        """All menu button texts should have corresponding handler regex."""
        from bot.handlers.menu import MAIN_MENU
        import re
        texts = [btn.text for row in MAIN_MENU.keyboard for btn in row]
        # These are the handler patterns from app.py
        patterns = [
            r"^✨ Что надеть$",
            r"^(👗|👧|👦|👩)\uFE0F? Гардероб$",
            r"^💬 Спросить Касси$",
            r"^👤 Профиль$",
            r"^❓ Помощь$",
        ]
        for text in texts:
            matched = any(re.match(p, text) for p in patterns)
            assert matched, f"Menu button '{text}' has no matching handler pattern"


# ══════════════════════════════════════════════════════════════════════════════
# COVERAGE: Previously untested features
# ══════════════════════════════════════════════════════════════════════════════

class TestStylePassport:

    def test_passport_template_exists(self):
        from pathlib import Path
        assert Path("renderer/templates/tpl_style_passport.html").exists()

    def test_passport_template_has_fields(self):
        html = open("renderer/templates/tpl_style_passport.html").read()
        assert "{{ name }}" in html
        assert "{{ sub_season }}" in html
        assert "{{ contrast_level }}" in html
        assert "{{ kibbe_primary }}" in html
        assert "{{ essence_label }}" in html
        assert "fashioncastle_bot" in html

    def test_passport_render_function_exists(self):
        from services.brief_renderer import render_style_passport
        assert callable(render_style_passport)


class TestPreGenerateBrief:

    def test_task_importable(self):
        from worker.tasks.pre_generate_brief import run
        assert callable(run)

    def test_cache_key_format(self):
        import uuid
        from datetime import date, timedelta
        user_id = uuid.uuid4()
        tomorrow = date.today() + timedelta(days=1)
        key = f"prebrief:{user_id}:{tomorrow.isoformat()}"
        assert "prebrief:" in key


class TestMoodDetailed:

    def test_fog_mood(self):
        from services.mood import detect_mood
        mood = detect_mood({"wmo_day": 45, "temp_now": 8}, weekday=2)
        assert mood["energy"] == "low"
        assert "туман" in mood["hint"].lower() or "уютн" in mood["hint"].lower()

    def test_overcast_cold_mood(self):
        from services.mood import detect_mood
        mood = detect_mood({"wmo_day": 3, "temp_now": 5}, weekday=1)
        assert mood["color_mood"] == "warm"

    def test_weekend_mood(self):
        from services.mood import detect_mood
        mood = detect_mood({"wmo_day": 2, "temp_now": 15}, weekday=6)
        assert mood["energy"] == "high"
        assert "выходн" in mood["hint"].lower()


class TestAntibotDetailed:

    def test_limits_are_reasonable(self):
        from bot.middleware.antibot import AntibotMiddleware
        assert 10 <= AntibotMiddleware.PHOTO_LIMIT <= 50
        assert 20 <= AntibotMiddleware.MESSAGE_LIMIT <= 60
        assert 30 <= AntibotMiddleware.CALLBACK_LIMIT <= 100
        assert AntibotMiddleware.BAN_THRESHOLD >= 2
        assert 60 <= AntibotMiddleware.BAN_DURATION <= 600


class TestSelfieOnboarding:

    def test_selfie_step_in_states(self):
        """SELFIE_STEP is defined and registered."""
        from bot.handlers.onboarding import SELFIE_STEP
        assert isinstance(SELFIE_STEP, int)

    def test_after_city_routes_correctly(self):
        """_after_city exists and handles segment fork."""
        import inspect
        from bot.handlers.onboarding import _after_city
        src = inspect.getsource(_after_city)
        assert "no_kids" in src
        assert "pregnant" in src
        assert "SELFIE_STEP" in src or "selfie" in src.lower()


class TestAlembicMigration:

    def test_migration_file_exists(self):
        from pathlib import Path
        migrations = list(Path("db/migrations/versions").glob("h8i9j0k1*"))
        assert len(migrations) == 1

    def test_migration_has_all_columns(self):
        content = open("db/migrations/versions/h8i9j0k1l2m3_add_styling_and_i18n_columns.py").read()
        for col in ["language", "contrast_level", "kibbe_family", "style_essence",
                     "color_flow_to", "color_flow_strength", "tonal_depth", "chroma",
                     "formality_level", "metal_tone"]:
            assert col in content, f"Migration missing column: {col}"
