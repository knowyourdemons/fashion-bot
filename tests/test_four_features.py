"""Tests for Style Challenge, Gap Analysis, Style Diary, Ask Friend."""
import pytest
import json
from unittest.mock import MagicMock, AsyncMock
from datetime import date, timedelta
from collections import Counter


def _item(cat="top", type_name="футболка", color="белый", score=5.0, warmth=2, wear_count=0, last_worn=None):
    m = MagicMock()
    m.id = str(id(m))
    m.category_group = cat
    m.type = type_name
    m.color = color
    m.score_item = score
    m.warmth_level = warmth
    m.wear_count = wear_count
    m.last_worn = last_worn
    m.season = ["spring", "summer", "autumn", "winter"]
    return m


# ── Style Challenge ──────────────────────────────────────────────────────────

class TestCapsuleSelection:

    def test_select_15_items(self):
        from bot.handlers.challenge import select_capsule
        items = (
            [_item("top", f"top{i}", c) for i, c in enumerate(["белый", "синий", "красный", "чёрный", "бежевый"])]
            + [_item("bottom", f"bot{i}", c) for i, c in enumerate(["серый", "синий", "чёрный"])]
            + [_item("outerwear", f"ow{i}", c) for i, c in enumerate(["чёрный", "бежевый", "серый"])]
            + [_item("footwear", f"fw{i}", c) for i, c in enumerate(["белый", "чёрный", "коричневый"])]
            + [_item("one_piece", f"op{i}", c) for i, c in enumerate(["красный", "синий", "бежевый"])]
            + [_item("accessory", f"acc{i}", c) for i, c in enumerate(["чёрный", "серый", "красный"])]
        )
        capsule = select_capsule(items, 15)
        assert len(capsule) <= 15

    def test_color_diversity(self):
        """Max 2 items of same color."""
        from bot.handlers.challenge import select_capsule
        items = [_item("top", f"top{i}", "красный") for i in range(10)]
        items += [_item("bottom", f"bot{i}", "красный") for i in range(5)]
        items += [_item("footwear", "fw1", "красный")]
        capsule = select_capsule(items, 15)
        color_counts = Counter(getattr(i, "color", "") for i in capsule)
        for color, count in color_counts.items():
            assert count <= 2, f"Color '{color}' appears {count} times (max 2)"

    def test_all_categories_present(self):
        from bot.handlers.challenge import select_capsule
        colors = ["белый", "чёрный", "синий", "серый", "бежевый"]
        items = (
            [_item("top", f"t{i}", colors[i % 5]) for i in range(5)]
            + [_item("bottom", f"b{i}", colors[i % 5]) for i in range(4)]
            + [_item("outerwear", f"o{i}", colors[i % 5]) for i in range(3)]
            + [_item("footwear", f"f{i}", colors[i % 5]) for i in range(3)]
            + [_item("one_piece", f"p{i}", colors[i % 5]) for i in range(3)]
            + [_item("accessory", f"a{i}", colors[i % 5]) for i in range(3)]
        )
        capsule = select_capsule(items, 15)
        categories = {getattr(i, "category_group", "") for i in capsule}
        assert "top" in categories
        assert "bottom" in categories

    def test_empty_wardrobe(self):
        from bot.handlers.challenge import select_capsule
        assert select_capsule([], 15) == []


class TestChallengeState:

    def test_challenge_data_structure(self):
        data = {
            "capsule_ids": ["id1", "id2"],
            "completed": 0,
            "outfits_shown": [],
            "started_at": date.today().isoformat(),
            "deadline": (date.today() + timedelta(days=10)).isoformat(),
        }
        assert json.loads(json.dumps(data)) == data

    def test_deadline_10_days(self):
        deadline = date.today() + timedelta(days=10)
        assert (deadline - date.today()).days == 10

    @pytest.mark.asyncio
    async def test_get_challenge_filter_no_redis(self):
        from bot.handlers.challenge import get_challenge_outfit_filter
        result = await get_challenge_outfit_filter("user1", None)
        assert result is None


# ── Gap Analysis ─────────────────────────────────────────────────────────────

class TestGapAnalysis:

    def test_gap_impact_formula(self):
        from services.wardrobe_math import calc_wardrobe_combos
        items = [_item("top")] * 3 + [_item("bottom")] * 2 + [_item("footwear")]
        base = calc_wardrobe_combos(items)
        # Add 1 outerwear
        items_plus = items + [_item("outerwear")]
        new = calc_wardrobe_combos(items_plus)
        impact = new - base
        assert impact > 0, "Adding outerwear should increase combos"

    def test_gap_analysis_exists(self):
        from services.scoring import get_wardrobe_gaps
        items = [_item("top")] * 2 + [_item("bottom")]
        gaps = get_wardrobe_gaps(items)
        assert isinstance(gaps, list)
        # Should suggest footwear
        assert any("обувь" in g for g in gaps)


# ── Style Diary ──────────────────────────────────────────────────────────────

class TestStyleDiary:

    @pytest.mark.asyncio
    async def test_wear_insights_colors(self):
        from services.style_diary import get_wear_insights
        items = [
            _item("top", "футболка", "синий", wear_count=5),
            _item("top", "свитер", "синий", wear_count=3),
            _item("bottom", "джинсы", "чёрный", wear_count=2),
        ]
        insights = await get_wear_insights("user1", items)
        assert insights["top_color"] == "синий"
        assert insights["top_color_pct"] > 50

    @pytest.mark.asyncio
    async def test_wear_insights_favorites(self):
        from services.style_diary import get_wear_insights
        items = [_item("top", "свитер", "красный", wear_count=5)]
        insights = await get_wear_insights("user1", items)
        assert len(insights["favorites"]) >= 1

    @pytest.mark.asyncio
    async def test_wear_insights_orphans(self):
        from services.style_diary import get_wear_insights
        items = [_item("top", "блузка", "белый", wear_count=0, last_worn=None)]
        insights = await get_wear_insights("user1", items)
        assert len(insights["orphans"]) >= 1

    def test_insight_rotation_4_types(self):
        from services.style_diary import format_weekly_insight
        insights = {
            "top_color": "синий", "top_color_pct": 60,
            "total_wears": 20, "unique_worn": 8, "total_visual": 15,
            "usage_pct": 53,
            "favorites": [_item("top", "свитер", "красный")],
            "orphans": [_item("top", "блузка", "белый")],
        }
        results = set()
        for week in range(4):
            r = format_weekly_insight(insights, week)
            if r:
                results.add(r[:10])  # first 10 chars differ
        assert len(results) >= 3, "Should have at least 3 different insight types"

    def test_insight_min_data(self):
        from services.style_diary import format_weekly_insight
        insights = {"total_wears": 2}
        assert format_weekly_insight(insights, 0) is None


# ── Ask Friend ───────────────────────────────────────────────────────────────

class TestAskFriend:

    def test_module_exists(self):
        from bot.handlers.ask_friend import create_vote_link, handle_vote_start, handle_vote_callback
        assert callable(create_vote_link)

    @pytest.mark.asyncio
    async def test_vote_link_creation(self):
        from bot.handlers.ask_friend import create_vote_link
        redis = AsyncMock()
        redis.set = AsyncMock()
        link = await create_vote_link("user1", "photo1", "Outfit", redis, "fashion_castle_bot")
        assert "t.me/fashion_castle_bot" in link
        assert "vote_" in link
        redis.set.assert_called_once()

    def test_vote_data_structure(self):
        data = {
            "user_id": "123",
            "photo_id": "abc",
            "description": "Outfit",
            "votes": {},
            "created_at": "2026-03-22T12:00:00",
        }
        assert json.loads(json.dumps(data)) == data

    def test_ask_friend_in_brief_buttons(self):
        """Brief buttons for 8+ photos should have 'Подругу'."""
        with open("services/brief_card.py") as f:
            source = f.read()
        assert "ask_friend:" in source
        assert "Подругу" in source

    def test_vote_deep_link_in_onboarding(self):
        """start.py should handle vote_ deep links."""
        with open("bot/handlers/onboarding.py") as f:
            source = f.read()
        assert "vote_" in source
        assert "handle_vote_start" in source

    def test_vote_callback_registered(self):
        with open("bot/app.py") as f:
            source = f.read()
        assert "vote:" in source
        assert "handle_vote_callback" in source


# ── Integration ──────────────────────────────────────────────────────────────

class TestIntegration:

    def test_challenge_registered_in_app(self):
        with open("bot/app.py") as f:
            source = f.read()
        assert "challenge_start" in source
        assert "challenge_later" in source

    def test_style_diary_module(self):
        from services.style_diary import get_wear_insights, format_weekly_insight
        assert callable(get_wear_insights)
        assert callable(format_weekly_insight)

    def test_contrast_colors_dict(self):
        from services.style_diary import _CONTRAST_COLORS
        assert len(_CONTRAST_COLORS) >= 5
        assert "синий" in _CONTRAST_COLORS
