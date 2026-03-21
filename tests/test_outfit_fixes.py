"""Tests for outfit generation fixes (March 2026):
1. Base layer filtering from collage
2. Minimum outfit validation
3. Vision prompt context
4. Post-validation after Vision
5. Adequate Kassi comment based on item count
"""
import uuid
import asyncio
import pytest
from datetime import date
from unittest.mock import MagicMock, AsyncMock, patch

pytest.importorskip("structlog", reason="structlog not installed")


# ── Helpers ──────────────────────────────────────────────────────────────────


def _item(category_group: str, type_: str, color: str = "белый",
          season=None, last_worn=None, show=True, score=7.0):
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
    i.warmth_level = 3
    i.style_tag = "casual"
    i.rain_ok = False
    return i


def _outfit(items, season="spring", temp_m=15.0, temp_e=15.0, precip=0.0):
    from services.outfit_selector import _select_outfit
    return _select_outfit(items, season, date.today(), temp_m, temp_e, precip)


# ══════════════════════════════════════════════════════════════════════════════
# FIX 1: Base layer items filtered from collage visual slots
# ══════════════════════════════════════════════════════════════════════════════


class TestBaseLayerFiltering:
    """Socks, underwear, tights, undershirts must NOT appear as photos in collage."""

    def test_is_base_layer_socks(self):
        from services.outfit_builder import _is_base_layer_item
        item = _item("base_layer", "носки", "белые")
        assert _is_base_layer_item(item) is True

    def test_is_base_layer_underwear_group(self):
        from services.outfit_builder import _is_base_layer_item
        item = _item("underwear", "трусики", "розовые")
        assert _is_base_layer_item(item) is True

    def test_is_base_layer_tights(self):
        from services.outfit_builder import _is_base_layer_item
        item = _item("base_layer", "колготки", "бежевые")
        assert _is_base_layer_item(item) is True

    def test_is_base_layer_undershirt(self):
        from services.outfit_builder import _is_base_layer_item
        item = _item("underwear", "майка", "белая")
        assert _is_base_layer_item(item) is True

    def test_is_base_layer_thermal(self):
        from services.outfit_builder import _is_base_layer_item
        item = _item("underwear", "термобельё", "серое")
        assert _is_base_layer_item(item) is True

    def test_not_base_layer_sweater(self):
        from services.outfit_builder import _is_base_layer_item
        item = _item("top", "свитер", "красный")
        assert _is_base_layer_item(item) is False

    def test_not_base_layer_pants(self):
        from services.outfit_builder import _is_base_layer_item
        item = _item("bottom", "штаны", "синие")
        assert _is_base_layer_item(item) is False

    def test_not_base_layer_shoes(self):
        from services.outfit_builder import _is_base_layer_item
        item = _item("footwear", "кроссовки", "белые")
        assert _is_base_layer_item(item) is False

    def test_socks_misclassified_as_footwear_still_filtered(self):
        """Even if Vision classifies socks as footwear, type check catches it."""
        from services.outfit_builder import _is_base_layer_item
        item = _item("footwear", "носки", "белые")
        assert _is_base_layer_item(item) is True

    def test_build_outfit_slots_excludes_base_layer(self):
        """build_outfit_slots must not include base layer items in visual slots."""
        from services.outfit_builder import build_outfit_slots

        items = [
            _item("top", "кофта", "розовая"),
            _item("bottom", "штаны", "серые"),
            _item("footwear", "кроссовки", "белые"),
        ]
        outfit = _outfit(items, temp_m=10.0, temp_e=8.0)

        # Inject socks into outfit
        socks = _item("base_layer", "носки", "белые")
        outfit["socks"] = socks

        slots = build_outfit_slots(outfit, temp=10.0)

        # Socks should NOT appear in visual slots
        slot_types = [s.get("item_type") for s in slots if s.get("has_item")]
        assert "носки" not in slot_types

    def test_build_outfit_slots_excludes_tights_with_photo(self):
        """Tights with photos should not appear in visual slots."""
        from services.outfit_builder import build_outfit_slots

        items = [
            _item("top", "кофта", "розовая"),
            _item("bottom", "юбка", "синяя"),
            _item("footwear", "ботинки", "коричневые"),
        ]
        outfit = _outfit(items, temp_m=5.0, temp_e=3.0)

        # Inject tights
        tights = _item("base_layer", "колготки", "бежевые")
        outfit["tights"] = tights

        slots = build_outfit_slots(outfit, temp=5.0)

        slot_types = [s.get("item_type") for s in slots if s.get("has_item")]
        assert "колготки" not in slot_types

    def test_build_outfit_slots_keeps_real_clothing(self):
        """Top, bottom, outerwear, footwear should remain in visual slots."""
        from services.outfit_builder import build_outfit_slots

        items = [
            _item("top", "свитер", "серый"),
            _item("bottom", "джинсы", "синие"),
            _item("footwear", "ботинки", "коричневые"),
            _item("outerwear", "куртка", "чёрная"),
        ]
        outfit = _outfit(items, temp_m=5.0, temp_e=3.0)

        slots = build_outfit_slots(outfit, temp=5.0)
        has_item_slots = [s for s in slots if s.get("has_item")]

        assert len(has_item_slots) >= 3  # top, bottom, footwear at minimum


# ══════════════════════════════════════════════════════════════════════════════
# FIX 2: Minimum outfit validation
# ══════════════════════════════════════════════════════════════════════════════


class TestMinimumOutfit:
    """Outfit needs top+bottom or one_piece to be displayable."""

    def test_has_minimum_with_top_and_bottom(self):
        from services.outfit_builder import has_minimum_outfit
        outfit = {"top": _item("top", "кофта"), "bottom": _item("bottom", "штаны"), "one_piece": None}
        assert has_minimum_outfit(outfit) is True

    def test_has_minimum_with_one_piece(self):
        from services.outfit_builder import has_minimum_outfit
        outfit = {"top": None, "bottom": None, "one_piece": _item("one_piece", "платье")}
        assert has_minimum_outfit(outfit) is True

    def test_no_minimum_only_bottom(self):
        from services.outfit_builder import has_minimum_outfit
        outfit = {"top": None, "bottom": _item("bottom", "штаны"), "one_piece": None}
        assert has_minimum_outfit(outfit) is False

    def test_no_minimum_only_top(self):
        from services.outfit_builder import has_minimum_outfit
        outfit = {"top": _item("top", "кофта"), "bottom": None, "one_piece": None}
        assert has_minimum_outfit(outfit) is False

    def test_no_minimum_empty(self):
        from services.outfit_builder import has_minimum_outfit
        outfit = {"top": None, "bottom": None, "one_piece": None}
        assert has_minimum_outfit(outfit) is False

    def test_has_minimum_wardrobe_top_and_bottom(self):
        from services.outfit_builder import has_minimum_wardrobe
        items = [
            _item("top", "кофта"),
            _item("bottom", "штаны"),
            _item("base_layer", "носки"),
        ]
        assert has_minimum_wardrobe(items) is True

    def test_has_minimum_wardrobe_one_piece(self):
        from services.outfit_builder import has_minimum_wardrobe
        items = [_item("one_piece", "платье")]
        assert has_minimum_wardrobe(items) is True

    def test_no_minimum_wardrobe_only_socks(self):
        from services.outfit_builder import has_minimum_wardrobe
        items = [
            _item("base_layer", "носки"),
            _item("underwear", "трусики"),
        ]
        assert has_minimum_wardrobe(items) is False

    def test_no_minimum_wardrobe_only_bottom(self):
        from services.outfit_builder import has_minimum_wardrobe
        items = [_item("bottom", "штаны")]
        assert has_minimum_wardrobe(items) is False


# ══════════════════════════════════════════════════════════════════════════════
# FIX 3: Vision prompt with context
# ══════════════════════════════════════════════════════════════════════════════


class TestVisionContext:
    """Vision prompt should include age, season, temperature context."""

    def test_call_vision_accepts_context_params(self):
        """_call_vision should accept context kwargs without error."""
        from services.vision import _call_vision
        import inspect
        sig = inspect.signature(_call_vision)
        params = set(sig.parameters.keys())
        assert "owner_type" in params
        assert "age" in params
        assert "season" in params
        assert "temp" in params
        assert "city" in params

    def test_call_vision_builds_context_message(self):
        """Verify context is included in the user message sent to Vision."""
        from services.vision import _call_vision

        mock_pool = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='[]')]
        mock_pool.create_message = AsyncMock(return_value=mock_response)

        with patch("services.vision.get_anthropic_pool", return_value=mock_pool):
            result = asyncio.run(_call_vision(
                b"fake_photo_bytes",
                owner_type="child",
                age=3,
                season="winter",
                temp=-5.0,
                city="Vilnius",
            ))

        call_args = mock_pool.create_message.call_args
        messages = call_args.kwargs.get("messages") or call_args[1].get("messages")
        user_content = messages[0]["content"]
        text_parts = [c["text"] for c in user_content if c["type"] == "text"]
        user_text = " ".join(text_parts)

        assert "ребёнка 3 лет" in user_text
        assert "зима" in user_text
        assert "-5" in user_text

    def test_call_vision_adult_context(self):
        """Adult context should mention 'взрослая женщина'."""
        from services.vision import _call_vision

        mock_pool = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='[]')]
        mock_pool.create_message = AsyncMock(return_value=mock_response)

        with patch("services.vision.get_anthropic_pool", return_value=mock_pool):
            result = asyncio.run(_call_vision(
                b"fake_photo_bytes",
                owner_type="user",
                season="spring",
                temp=15.0,
            ))

        call_args = mock_pool.create_message.call_args
        messages = call_args.kwargs.get("messages") or call_args[1].get("messages")
        user_content = messages[0]["content"]
        text_parts = [c["text"] for c in user_content if c["type"] == "text"]
        user_text = " ".join(text_parts)

        assert "взрослой женщины" in user_text

    def test_call_vision_no_context_still_works(self):
        """Without context, should still work with basic prompt."""
        from services.vision import _call_vision

        mock_pool = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='[{"type":"кофта","color":"красная","category_group":"top","category_code":"top.sweater","style":"повседневный","season":["spring"],"occasion":["everyday"],"brand":null,"bbox":{"x":0,"y":0,"w":1,"h":1},"score_breakdown":{"safety":2,"practicality":2,"durability":2,"age_authenticity":2,"ease_of_care":2,"colortype":2,"comfort":2,"versatility":2,"condition":2,"size_fit_score":2,"seasonality":2}}]')]
        mock_pool.create_message = AsyncMock(return_value=mock_response)

        with patch("services.vision.get_anthropic_pool", return_value=mock_pool):
            result = asyncio.run(_call_vision(b"fake_photo_bytes"))

        assert len(result) == 1
        assert result[0]["type"] == "кофта"


# ══════════════════════════════════════════════════════════════════════════════
# FIX 4: Post-validation after Vision
# ══════════════════════════════════════════════════════════════════════════════


class TestPostValidation:
    """Vision results should be corrected based on weather context."""

    def test_shorts_reclassified_at_cold_temp(self):
        from services.vision import _post_validate_vision
        items = [{"type": "шорты", "color": "синие", "category_group": "bottom", "season": ["summer"]}]
        result = _post_validate_vision(items, temp=2.0)
        assert result[0]["type"] == "штаны"

    def test_shorts_kept_at_warm_temp(self):
        from services.vision import _post_validate_vision
        items = [{"type": "шорты", "color": "синие", "category_group": "bottom", "season": ["summer"]}]
        result = _post_validate_vision(items, temp=25.0)
        assert result[0]["type"] == "шорты"

    def test_shorts_boundary_at_10(self):
        """Exactly 10°C should NOT reclassify (threshold is < 10)."""
        from services.vision import _post_validate_vision
        items = [{"type": "шорты", "color": "синие", "category_group": "bottom", "season": ["summer"]}]
        result = _post_validate_vision(items, temp=10.0)
        assert result[0]["type"] == "шорты"

    def test_shorts_reclassified_at_9(self):
        from services.vision import _post_validate_vision
        items = [{"type": "шорты", "color": "синие", "category_group": "bottom", "season": ["summer"]}]
        result = _post_validate_vision(items, temp=9.0)
        assert result[0]["type"] == "штаны"

    def test_sandals_reclassified_at_freezing(self):
        from services.vision import _post_validate_vision
        items = [{"type": "сандалии", "color": "коричневые", "category_group": "footwear", "season": ["summer"]}]
        result = _post_validate_vision(items, temp=0.0)
        assert result[0]["type"] == "кроссовки"

    def test_sandals_kept_at_warm_temp(self):
        from services.vision import _post_validate_vision
        items = [{"type": "сандалии", "color": "коричневые", "category_group": "footwear", "season": ["summer"]}]
        result = _post_validate_vision(items, temp=20.0)
        assert result[0]["type"] == "сандалии"

    def test_no_temp_no_change(self):
        """Without temperature context, no reclassification should happen."""
        from services.vision import _post_validate_vision
        items = [{"type": "шорты", "color": "синие", "category_group": "bottom"}]
        result = _post_validate_vision(items, temp=None)
        assert result[0]["type"] == "шорты"

    def test_non_shorts_bottom_unchanged(self):
        """Regular pants should not be reclassified."""
        from services.vision import _post_validate_vision
        items = [{"type": "штаны", "color": "серые", "category_group": "bottom"}]
        result = _post_validate_vision(items, temp=2.0)
        assert result[0]["type"] == "штаны"

    def test_multiple_items_selective(self):
        """Only problematic items should be reclassified."""
        from services.vision import _post_validate_vision
        items = [
            {"type": "шорты", "color": "синие", "category_group": "bottom", "season": ["summer"]},
            {"type": "кофта", "color": "красная", "category_group": "top"},
            {"type": "сандалии", "color": "белые", "category_group": "footwear", "season": ["summer"]},
        ]
        result = _post_validate_vision(items, temp=0.0)
        assert result[0]["type"] == "штаны"
        assert result[1]["type"] == "кофта"  # unchanged
        assert result[2]["type"] == "кроссовки"

    def test_reclassified_shorts_get_all_seasons(self):
        """After reclassifying shorts→pants, season should include winter."""
        from services.vision import _post_validate_vision
        items = [{"type": "шорты", "color": "синие", "category_group": "bottom", "season": ["summer"]}]
        result = _post_validate_vision(items, temp=2.0)
        assert "winter" in result[0]["season"]


# ══════════════════════════════════════════════════════════════════════════════
# FIX 5: Adequate Kassi comment based on item count
# ══════════════════════════════════════════════════════════════════════════════


class TestCommentItemCount:
    """Kassi comments should be appropriate for the number of items."""

    def test_generate_outfit_comment_accepts_item_count(self):
        """generate_outfit_comment should accept item_count parameter."""
        from services.scoring_comment import generate_outfit_comment
        import inspect
        sig = inspect.signature(generate_outfit_comment)
        assert "item_count" in sig.parameters

    def test_comment_few_items_no_образ(self):
        """With 1-2 items, comment should not praise an 'образ'."""
        from services.scoring_comment import generate_outfit_comment

        mock_pool = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Тёплые штанишки — хорошая основа!")]
        mock_pool.create_message = AsyncMock(return_value=mock_response)

        # Verify the system prompt contains item-count instruction
        result = asyncio.run(generate_outfit_comment(
            pool=mock_pool,
            outfit_items=["штаны серые"],
            weather="+2°C",
            context="садик",
            score=6.0,
            is_wow=False,
            child_name="Алиса",
            gender="girl",
            age=3,
            tone="",
            wow_messages=[],
            item_count=1,
        ))

        call_args = mock_pool.create_message.call_args
        system_prompt = call_args.kwargs.get("system") or call_args[1].get("system")
        assert "НЕ говори слово" in system_prompt or "мало вещей" in system_prompt

    def test_comment_medium_items_mentions_combination(self):
        """With 3-5 items, comment should mention combinations."""
        from services.scoring_comment import generate_outfit_comment

        mock_pool = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Хорошее сочетание!")]
        mock_pool.create_message = AsyncMock(return_value=mock_response)

        result = asyncio.run(generate_outfit_comment(
            pool=mock_pool,
            outfit_items=["кофта розовая", "штаны серые", "ботинки коричневые"],
            weather="+5°C",
            context="садик",
            score=7.0,
            is_wow=False,
            child_name="Алиса",
            gender="girl",
            age=3,
            tone="",
            wow_messages=[],
            item_count=3,
        ))

        call_args = mock_pool.create_message.call_args
        system_prompt = call_args.kwargs.get("system") or call_args[1].get("system")
        assert "сочетание" in system_prompt

    def test_comment_many_items_no_restriction(self):
        """With 6+ items, no special restriction on 'образ'."""
        from services.scoring_comment import generate_outfit_comment

        mock_pool = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Отличный образ!")]
        mock_pool.create_message = AsyncMock(return_value=mock_response)

        result = asyncio.run(generate_outfit_comment(
            pool=mock_pool,
            outfit_items=["кофта", "штаны", "ботинки", "куртка", "шапка", "шарф"],
            weather="+2°C",
            context="садик",
            score=8.0,
            is_wow=False,
            child_name="Алиса",
            gender="girl",
            age=3,
            tone="",
            wow_messages=[],
            item_count=6,
        ))

        call_args = mock_pool.create_message.call_args
        system_prompt = call_args.kwargs.get("system") or call_args[1].get("system")
        # No item-count restriction for 6+ items
        assert "мало вещей" not in system_prompt

    def test_warm_outfit_comment_single_item(self):
        """warm_outfit_comment with 1 item should not use word 'образ' in praise."""
        from services.outfit_builder import warm_outfit_comment
        comment = warm_outfit_comment(
            score=7.0,
            child_name="Алиса",
            temp=5.0,
            real_item_count=1,
            first_item_desc="штаны серые",
        )
        # Single-item comments should mention "вещь" or the item desc, not "образ" as first word
        low = comment.lower()
        assert "вещь" in low or "выбор" in low or "штаны" in low or "люблю" in low

    def test_warm_outfit_comment_multiple_items(self):
        """warm_outfit_comment with many items should NOT use single-item templates."""
        from services.outfit_builder import warm_outfit_comment
        comment = warm_outfit_comment(
            score=8.5,
            child_name="Алиса",
            real_item_count=5,
        )
        # With 5 items and no first_item_desc, should NOT use single-item templates
        assert "добавь ещё пару" not in comment.lower()
        assert "сфоткай ещё" not in comment.lower()


# ══════════════════════════════════════════════════════════════════════════════
# INTEGRATION: Full pipeline checks
# ══════════════════════════════════════════════════════════════════════════════


class TestOutfitPipelineIntegration:
    """Integration tests combining multiple fixes."""

    def test_socks_only_wardrobe_no_outfit(self):
        """Wardrobe with only socks/underwear → no minimum outfit."""
        from services.outfit_builder import has_minimum_wardrobe
        items = [
            _item("base_layer", "носки", "белые"),
            _item("underwear", "трусики", "розовые"),
            _item("underwear", "майка", "белая"),
        ]
        assert has_minimum_wardrobe(items) is False

    def test_pants_only_no_minimum(self):
        """Only pants → no minimum outfit (missing top)."""
        from services.outfit_builder import has_minimum_outfit
        items = [_item("bottom", "штаны", "серые")]
        outfit = _outfit(items, temp_m=10.0)
        assert has_minimum_outfit(outfit) is False

    def test_full_wardrobe_base_layer_excluded(self):
        """Full wardrobe outfit should not show socks/underwear in slots."""
        from services.outfit_builder import build_outfit_slots

        items = [
            _item("top", "кофта", "розовая"),
            _item("bottom", "штаны", "серые"),
            _item("footwear", "кроссовки", "белые"),
            _item("outerwear", "куртка", "синяя"),
            _item("base_layer", "носки", "белые"),
            _item("underwear", "трусики", "розовые"),
        ]
        outfit = _outfit(items, temp_m=5.0, temp_e=3.0)

        assert has_minimum_outfit(outfit) is True

        slots = build_outfit_slots(outfit, temp=5.0)
        visual_types = [s.get("item_type", "").lower() for s in slots if s.get("has_item")]

        assert "носки" not in visual_types
        assert "трусики" not in visual_types
        assert any("кофт" in t for t in visual_types)
        assert any("штан" in t for t in visual_types)

    def test_shorts_at_cold_temp_reclassified_in_pipeline(self):
        """Post-validation changes shorts to pants at cold temperatures."""
        from services.vision import _post_validate_vision
        items = [
            {"type": "шорты", "color": "серые", "category_group": "bottom", "season": ["summer"]},
            {"type": "кофта", "color": "розовая", "category_group": "top"},
        ]
        validated = _post_validate_vision(items, temp=2.0, season="winter")
        assert validated[0]["type"] == "штаны"
        assert validated[1]["type"] == "кофта"


def has_minimum_outfit(outfit):
    """Local import helper for integration tests."""
    from services.outfit_builder import has_minimum_outfit
    return has_minimum_outfit(outfit)
