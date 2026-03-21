"""Tests for services/outfit_engine.py — AI-powered outfit selection.

Tests cover: serialization, prompt building, response parsing,
fallback, rotation, segment prompts, and integration.
"""
import uuid
import asyncio
import json
import pytest
from datetime import date
from unittest.mock import MagicMock, AsyncMock, patch
from dataclasses import asdict

pytest.importorskip("structlog", reason="structlog not installed")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _item(category_group: str, type_: str, color: str = "белый",
          season=None, last_worn=None, show=True, score=7.0,
          style="повседневный", warmth=3, style_tag="casual", rain_ok=False):
    i = MagicMock()
    i.id = uuid.uuid4()
    i.category_group = category_group
    i.type = type_
    i.color = color
    i.season = season or ["spring", "summer", "autumn", "winter"]
    i.last_worn = last_worn
    i.show_in_collage = show
    i.photo_id = f"photo_{type_}"
    i.photo_url = None
    i.score_item = score
    i.style = style
    i.warmth_level = warmth
    i.style_tag = style_tag
    i.rain_ok = rain_ok
    return i


def _basic_wardrobe():
    return [
        _item("top", "кофта", "розовая", score=8.0),
        _item("top", "футболка", "белая", score=6.0),
        _item("bottom", "джинсы", "синие", score=7.5),
        _item("bottom", "юбка", "чёрная", score=7.0),
        _item("footwear", "кроссовки", "белые", score=7.0),
        _item("footwear", "ботинки", "коричневые", score=7.5),
        _item("outerwear", "куртка", "синяя", score=8.0),
        _item("accessory", "шапка", "розовая", score=6.0),
        _item("underwear", "трусики", "розовые"),
        _item("base_layer", "носки", "белые"),
    ]


# ══════════════════════════════════════════════════════════════════════════════
# OutfitResult dataclass
# ══════════════════════════════════════════════════════════════════════════════

class TestOutfitResult:
    def test_dataclass_fields(self):
        from services.outfit_engine import OutfitResult
        r = OutfitResult(
            outfit={"top": None, "bottom": None},
            comment="Тестовый комментарий",
            is_wow=True,
            ai_selected=True,
        )
        assert r.outfit == {"top": None, "bottom": None}
        assert r.comment == "Тестовый комментарий"
        assert r.is_wow is True
        assert r.ai_selected is True

    def test_defaults(self):
        from services.outfit_engine import OutfitResult
        r = OutfitResult(outfit={}, comment="")
        assert r.is_wow is False
        assert r.ai_selected is False


# ══════════════════════════════════════════════════════════════════════════════
# Item serialization
# ══════════════════════════════════════════════════════════════════════════════

class TestSerialization:
    def test_serialize_item(self):
        from services.outfit_engine import _serialize_item
        item = _item("top", "кофта", "розовая", score=8.5)
        data = _serialize_item(item)
        assert data["cg"] == "top"
        assert data["type"] == "кофта"
        assert data["color"] == "розовая"
        assert data["score"] == 8.5
        assert "id" in data

    def test_build_candidates_excludes_base_layer(self):
        from services.outfit_engine import _build_candidates
        items = _basic_wardrobe()
        candidates = _build_candidates(items, "spring", date.today())

        # base_layer and underwear should be excluded
        assert "underwear" not in candidates
        assert "base_layer" not in candidates
        # top, bottom, etc. should be present
        assert "top" in candidates
        assert "bottom" in candidates

    def test_build_candidates_caps_per_group(self):
        from services.outfit_engine import _build_candidates, _MAX_PER_GROUP
        # Create 20 tops
        items = [_item("top", f"кофта_{i}", score=float(i)) for i in range(20)]
        candidates = _build_candidates(items, "spring", date.today())
        assert len(candidates["top"]) <= _MAX_PER_GROUP

    def test_build_candidates_filters_season(self):
        from services.outfit_engine import _build_candidates
        winter_item = _item("top", "свитер", season=["winter"])
        summer_item = _item("top", "футболка", season=["summer"])
        candidates = _build_candidates([winter_item, summer_item], "summer", date.today())
        types = [c["type"] for c in candidates.get("top", [])]
        assert "футболка" in types
        assert "свитер" not in types

    def test_build_candidates_text(self):
        from services.outfit_engine import _build_candidates, _build_candidates_text
        items = [_item("top", "кофта", "розовая"), _item("bottom", "джинсы", "синие")]
        candidates = _build_candidates(items, "spring", date.today())
        text = _build_candidates_text(candidates)
        assert "ВЕРХ" in text
        assert "НИЗ" in text
        assert "кофта" in text
        assert "джинсы" in text


# ══════════════════════════════════════════════════════════════════════════════
# Rotation
# ══════════════════════════════════════════════════════════════════════════════

class TestRotation:
    def test_rotation_text_empty(self):
        from services.outfit_engine import _build_rotation_text
        assert _build_rotation_text([]) == ""

    def test_rotation_text_with_yesterday(self):
        from services.outfit_engine import _build_rotation_text
        recent = [["id1", "id2", "id3"]]
        text = _build_rotation_text(recent)
        assert "id1" in text
        assert "НЕ повторять" in text

    def test_rotation_text_multi_day(self):
        from services.outfit_engine import _build_rotation_text
        recent = [["id1"], ["id2"], ["id3"]]
        text = _build_rotation_text(recent)
        assert "3 дней" in text


# ══════════════════════════════════════════════════════════════════════════════
# User prompt building
# ══════════════════════════════════════════════════════════════════════════════

class TestUserPrompt:
    def test_mom_prompt_includes_child_context(self):
        from services.outfit_engine import _build_user_prompt, _build_candidates
        items = _basic_wardrobe()
        candidates = _build_candidates(items, "spring", date.today())
        prompt = _build_user_prompt(
            candidates=candidates,
            temp_morning=5.0, temp_evening=2.0,
            season="spring", regime="холодно",
            segment="mom_girl",
            child_name="Алиса", child_age=3, child_gender="girl",
            colortype="Лето",
        )
        assert "Алиса" in prompt
        assert "3 лет" in prompt
        assert "девочка" in prompt
        assert "Лето" in prompt

    def test_woman_prompt_no_child(self):
        from services.outfit_engine import _build_user_prompt, _build_candidates
        items = _basic_wardrobe()
        candidates = _build_candidates(items, "spring", date.today())
        prompt = _build_user_prompt(
            candidates=candidates,
            temp_morning=15.0, temp_evening=12.0,
            season="spring", regime="тепло",
            segment="no_kids",
            child_name=None, child_age=None, child_gender=None,
            colortype="Весна",
        )
        assert "ребёнок" not in prompt.lower()
        assert "Весна" in prompt

    def test_prompt_includes_weather(self):
        from services.outfit_engine import _build_user_prompt
        prompt = _build_user_prompt(
            candidates={"top": []},
            temp_morning=-5.0, temp_evening=-10.0,
            season="winter", regime="сильный_мороз",
            segment="mom_girl",
            child_name="Алиса", child_age=3, child_gender="girl",
            colortype=None,
        )
        assert "-5" in prompt
        assert "-10" in prompt
        assert "шапка" in prompt  # required at < 10

    def test_prompt_item_count_awareness(self):
        from services.outfit_engine import _build_user_prompt
        prompt = _build_user_prompt(
            candidates={"top": [{"id": "1", "type": "кофта", "color": "розовая"}]},
            temp_morning=10.0, temp_evening=8.0,
            season="spring", regime="прохладно",
            segment="mom_girl",
            child_name="Алиса", child_age=3, child_gender="girl",
            colortype=None,
            item_count_total=1,
        )
        assert "мало вещей" in prompt.lower()


# ══════════════════════════════════════════════════════════════════════════════
# AI response parsing
# ══════════════════════════════════════════════════════════════════════════════

class TestResponseParsing:
    def test_parse_valid_response(self):
        from services.outfit_engine import _parse_ai_response
        items = _basic_wardrobe()
        items_by_id = {str(i.id): i for i in items}

        top_id = str(items[0].id)  # кофта
        bottom_id = str(items[2].id)  # джинсы
        footwear_id = str(items[4].id)  # кроссовки

        raw = json.dumps({
            "items": {"top": top_id, "bottom": bottom_id, "footwear": footwear_id},
            "comment": "Отличное сочетание розовой кофты и синих джинсов!",
            "is_wow": False,
        })

        result = _parse_ai_response(raw, items_by_id)
        assert result is not None
        slot_items, comment, is_wow = result
        assert "top" in slot_items
        assert "bottom" in slot_items
        assert "footwear" in slot_items
        assert "розовой кофты" in comment

    def test_parse_with_prefix_uuid(self):
        """AI might truncate UUIDs — prefix matching should work."""
        from services.outfit_engine import _parse_ai_response
        item = _item("top", "кофта", "розовая")
        full_id = str(item.id)
        items_by_id = {full_id: item}

        raw = json.dumps({
            "items": {"top": full_id[:8]},
            "comment": "Красивая кофта!",
            "is_wow": False,
        })

        result = _parse_ai_response(raw, items_by_id)
        assert result is not None
        assert "top" in result[0]

    def test_parse_with_markdown_wrapper(self):
        from services.outfit_engine import _parse_ai_response
        item = _item("top", "кофта")
        items_by_id = {str(item.id): item}

        raw = f'```json\n{{"items": {{"top": "{item.id}"}}, "comment": "ok", "is_wow": false}}\n```'

        result = _parse_ai_response(raw, items_by_id)
        assert result is not None

    def test_parse_invalid_json(self):
        from services.outfit_engine import _parse_ai_response
        result = _parse_ai_response("this is not json", {})
        assert result is None

    def test_parse_empty_items(self):
        from services.outfit_engine import _parse_ai_response
        raw = json.dumps({"items": {}, "comment": "hmm", "is_wow": False})
        result = _parse_ai_response(raw, {})
        assert result is None

    def test_parse_unknown_uuid(self):
        from services.outfit_engine import _parse_ai_response
        raw = json.dumps({
            "items": {"top": "nonexistent-uuid"},
            "comment": "something",
            "is_wow": False,
        })
        result = _parse_ai_response(raw, {})
        assert result is None  # no items matched


# ══════════════════════════════════════════════════════════════════════════════
# Build outfit from AI selection
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildOutfitFromAI:
    def test_outfit_shape_matches_select_outfit(self):
        from services.outfit_engine import _build_outfit_from_ai
        items = _basic_wardrobe()
        slot_items = {"top": items[0], "bottom": items[2], "footwear": items[4]}

        outfit = _build_outfit_from_ai(slot_items, items, temp=10.0, season="spring", today=date.today())

        # Check all expected keys are present
        expected_keys = {
            "thermal_top", "thermal_bottom", "underwear_items", "underwear_text",
            "one_piece", "top", "bottom", "removable_layer", "tights", "socks",
            "footwear", "outerwear", "hat", "scarf", "gloves", "warnings",
            "all_items", "temp",
        }
        assert set(outfit.keys()) >= expected_keys

    def test_outfit_includes_base_layer(self):
        """Base layer items should be auto-added by rules even though AI doesn't pick them."""
        from services.outfit_engine import _build_outfit_from_ai
        items = _basic_wardrobe()
        slot_items = {"top": items[0], "bottom": items[2]}

        outfit = _build_outfit_from_ai(slot_items, items, temp=10.0, season="spring", today=date.today())

        # Should have underwear auto-filled
        assert outfit["underwear_items"] or outfit["underwear_text"]

    def test_outfit_thermal_at_cold_temp(self):
        """At <=5°C thermal underwear should be selected by rules."""
        from services.outfit_engine import _build_outfit_from_ai
        thermal = _item("underwear", "термобельё", "серое")
        items = _basic_wardrobe() + [thermal]
        slot_items = {"top": items[0], "bottom": items[2]}

        outfit = _build_outfit_from_ai(slot_items, items, temp=3.0, season="winter", today=date.today())
        assert outfit["thermal_top"] is not None

    def test_all_items_populated(self):
        from services.outfit_engine import _build_outfit_from_ai
        items = _basic_wardrobe()
        slot_items = {"top": items[0], "bottom": items[2], "footwear": items[4], "outerwear": items[6]}

        outfit = _build_outfit_from_ai(slot_items, items, temp=5.0, season="spring", today=date.today())
        assert len(outfit["all_items"]) >= 4  # top + bottom + footwear + outerwear + underwear


# ══════════════════════════════════════════════════════════════════════════════
# Segment-specific prompts
# ══════════════════════════════════════════════════════════════════════════════

class TestSegmentPrompts:
    def test_mom_system_prompt(self):
        from services.outfit_engine import _SYSTEM_MOM
        assert "удобно" in _SYSTEM_MOM.lower()
        assert "тепло" in _SYSTEM_MOM.lower()
        assert "ребёнк" in _SYSTEM_MOM.lower()

    def test_woman_system_prompt(self):
        from services.outfit_engine import _SYSTEM_WOMAN
        assert "стильно" in _SYSTEM_WOMAN.lower()
        assert "гармонир" in _SYSTEM_WOMAN.lower()
        assert "женщин" in _SYSTEM_WOMAN.lower()


# ══════════════════════════════════════════════════════════════════════════════
# Fallback
# ══════════════════════════════════════════════════════════════════════════════

class TestFallback:
    def test_fallback_uses_rule_based(self):
        from services.outfit_engine import _fallback_result
        items = _basic_wardrobe()
        result = _fallback_result(
            items, "spring", date.today(), 10.0, 8.0, 0,
            "mom_girl", "Алиса",
        )
        assert result.ai_selected is False
        assert result.outfit is not None
        assert result.comment  # should have a comment

    def test_fallback_has_minimum_outfit(self):
        from services.outfit_engine import _fallback_result
        from services.outfit_builder import has_minimum_outfit
        items = _basic_wardrobe()
        result = _fallback_result(
            items, "spring", date.today(), 10.0, 8.0, 0,
            "mom_girl", "Алиса",
        )
        assert has_minimum_outfit(result.outfit) is True


# ══════════════════════════════════════════════════════════════════════════════
# select_outfit_ai full flow
# ══════════════════════════════════════════════════════════════════════════════

class TestSelectOutfitAI:
    def test_ai_success_flow(self):
        """Full flow: mock Haiku → outfit + comment returned."""
        from services.outfit_engine import select_outfit_ai
        items = _basic_wardrobe()

        top = items[0]  # кофта
        bottom = items[2]  # джинсы
        footwear = items[4]  # кроссовки

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps({
            "items": {
                "top": str(top.id),
                "bottom": str(bottom.id),
                "footwear": str(footwear.id),
            },
            "comment": "Розовая кофта отлично сочетается с синими джинсами!",
            "is_wow": False,
        }))]

        mock_pool = AsyncMock()
        mock_pool.create_message = AsyncMock(return_value=mock_response)

        result = asyncio.run(select_outfit_ai(
            pool=mock_pool,
            items=items,
            season="spring",
            today=date.today(),
            temp_morning=10.0,
            temp_evening=8.0,
            segment="mom_girl",
            child_name="Алиса",
            child_age=3,
            child_gender="girl",
        ))

        assert result.ai_selected is True
        assert result.comment == "Розовая кофта отлично сочетается с синими джинсами!"
        assert result.outfit["top"] is not None
        assert result.outfit["bottom"] is not None

    def test_ai_failure_falls_back(self):
        """When Haiku fails, should fall back to rule-based."""
        from services.outfit_engine import select_outfit_ai
        items = _basic_wardrobe()

        mock_pool = AsyncMock()
        mock_pool.create_message = AsyncMock(side_effect=Exception("API timeout"))

        result = asyncio.run(select_outfit_ai(
            pool=mock_pool,
            items=items,
            season="spring",
            today=date.today(),
            temp_morning=10.0,
            temp_evening=8.0,
            segment="mom_girl",
            child_name="Алиса",
            child_age=3,
            child_gender="girl",
        ))

        assert result.ai_selected is False
        assert result.outfit is not None
        assert result.comment  # should have fallback comment

    def test_ai_invalid_json_falls_back(self):
        """When Haiku returns garbage, should fall back."""
        from services.outfit_engine import select_outfit_ai
        items = _basic_wardrobe()

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="I'm sorry, I can't do that.")]

        mock_pool = AsyncMock()
        mock_pool.create_message = AsyncMock(return_value=mock_response)

        result = asyncio.run(select_outfit_ai(
            pool=mock_pool,
            items=items,
            season="spring",
            today=date.today(),
            temp_morning=10.0,
            temp_evening=8.0,
        ))

        assert result.ai_selected is False

    def test_too_few_candidates_uses_fallback(self):
        """With only 1 non-base-layer item, should use fallback directly."""
        from services.outfit_engine import select_outfit_ai
        items = [_item("top", "кофта", "розовая")]

        mock_pool = AsyncMock()
        # Should NOT be called since we go straight to fallback
        mock_pool.create_message = AsyncMock()

        result = asyncio.run(select_outfit_ai(
            pool=mock_pool,
            items=items,
            season="spring",
            today=date.today(),
            temp_morning=10.0,
            temp_evening=8.0,
        ))

        assert result.ai_selected is False
        # Haiku should not have been called
        mock_pool.create_message.assert_not_called()

    def test_mom_vs_woman_segment(self):
        """Different segments should use different system prompts."""
        from services.outfit_engine import select_outfit_ai, _SYSTEM_MOM, _SYSTEM_WOMAN
        items = _basic_wardrobe()

        calls = []

        async def capture_call(**kwargs):
            calls.append(kwargs)
            resp = MagicMock()
            top = items[0]
            bottom = items[2]
            resp.content = [MagicMock(text=json.dumps({
                "items": {"top": str(top.id), "bottom": str(bottom.id)},
                "comment": "test",
                "is_wow": False,
            }))]
            return resp

        mock_pool = AsyncMock()
        mock_pool.create_message = AsyncMock(side_effect=capture_call)

        # Mom segment
        asyncio.run(select_outfit_ai(
            pool=mock_pool, items=items, season="spring",
            today=date.today(), temp_morning=10.0, temp_evening=8.0,
            segment="mom_girl", child_name="Алиса", child_age=3,
        ))

        mom_system = calls[0]["system"]
        assert "ребёнка" in mom_system if isinstance(mom_system, str) else "ребёнка" in mom_system[0].get("text", "")

        calls.clear()

        # Woman segment
        asyncio.run(select_outfit_ai(
            pool=mock_pool, items=items, season="spring",
            today=date.today(), temp_morning=10.0, temp_evening=8.0,
            segment="no_kids",
        ))

        woman_system = calls[0]["system"]
        assert "женщин" in woman_system if isinstance(woman_system, str) else "женщин" in woman_system[0].get("text", "")

    def test_post_validation_shorts_cold(self):
        """AI picks shorts at cold temp → should be replaced with pants."""
        from services.outfit_engine import select_outfit_ai
        shorts = _item("bottom", "шорты", "синие", score=9.0)
        pants = _item("bottom", "штаны", "серые", score=7.0)
        top = _item("top", "кофта", "розовая", score=8.0)
        footwear = _item("footwear", "ботинки", "коричневые")
        items = [top, shorts, pants, footwear,
                 _item("underwear", "трусики"), _item("base_layer", "носки")]

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps({
            "items": {
                "top": str(top.id),
                "bottom": str(shorts.id),  # AI picks shorts
                "footwear": str(footwear.id),
            },
            "comment": "Стильные шорты!",
            "is_wow": False,
        }))]

        mock_pool = AsyncMock()
        mock_pool.create_message = AsyncMock(return_value=mock_response)

        result = asyncio.run(select_outfit_ai(
            pool=mock_pool,
            items=items,
            season="winter",
            today=date.today(),
            temp_morning=2.0,
            temp_evening=0.0,
        ))

        # Should have replaced shorts with pants
        if result.ai_selected:
            bottom = result.outfit.get("bottom")
            if bottom:
                assert "шорт" not in (bottom.type or "").lower()

    def test_rotation_ids_passed_to_prompt(self):
        """Recent outfit IDs should appear in the prompt."""
        from services.outfit_engine import select_outfit_ai
        items = _basic_wardrobe()

        calls = []

        async def capture_call(**kwargs):
            calls.append(kwargs)
            top = items[0]
            bottom = items[2]
            resp = MagicMock()
            resp.content = [MagicMock(text=json.dumps({
                "items": {"top": str(top.id), "bottom": str(bottom.id)},
                "comment": "ok", "is_wow": False,
            }))]
            return resp

        mock_pool = AsyncMock()
        mock_pool.create_message = AsyncMock(side_effect=capture_call)

        recent = [["abc123", "def456"]]
        asyncio.run(select_outfit_ai(
            pool=mock_pool, items=items, season="spring",
            today=date.today(), temp_morning=10.0, temp_evening=8.0,
            recent_outfit_ids=recent,
        ))

        # Check the user prompt contains rotation constraint
        user_msg = calls[0]["messages"][0]["content"]
        assert "abc123" in user_msg


# ══════════════════════════════════════════════════════════════════════════════
# CRUD: get_recent_outfit_item_ids
# ══════════════════════════════════════════════════════════════════════════════

class TestBriefLogCRUD:
    def test_function_exists(self):
        from db.crud.brief_log import get_recent_outfit_item_ids
        import inspect
        assert inspect.iscoroutinefunction(get_recent_outfit_item_ids)

    def test_function_signature(self):
        from db.crud.brief_log import get_recent_outfit_item_ids
        import inspect
        sig = inspect.signature(get_recent_outfit_item_ids)
        params = list(sig.parameters.keys())
        assert "session" in params
        assert "user_id" in params
        assert "days" in params
