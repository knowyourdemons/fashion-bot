"""Tests for services/vision.py — pure helpers + API call error handling."""
import io
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from PIL import Image


# ── Pure helper tests ──────────────────────────────────────────────────────


class TestDedupKey:
    def test_normal(self):
        from services.vision import _dedup_key
        data = {"type": "Свитшот", "color": "Розовый", "category_group": "top"}
        assert _dedup_key(data) == ("свитшот", "розовый", "top")

    def test_strips_whitespace(self):
        from services.vision import _dedup_key
        data = {"type": "  кофта  ", "color": " синий ", "category_group": "top"}
        assert _dedup_key(data) == ("кофта", "синий", "top")

    def test_missing_fields(self):
        from services.vision import _dedup_key
        assert _dedup_key({}) == ("", "", "top")

    def test_none_values(self):
        from services.vision import _dedup_key
        data = {"type": None, "color": None, "category_group": None}
        assert _dedup_key(data) == ("", "", "top")


class TestItemLabel:
    def test_normal(self):
        from services.vision import _item_label
        assert _item_label({"color": "розовый", "type": "свитшот"}) == "розовый свитшот"

    def test_missing_color(self):
        from services.vision import _item_label
        assert _item_label({"type": "кофта"}) == "кофта"

    def test_empty(self):
        from services.vision import _item_label
        assert _item_label({}) == "вещь"


class TestColorSimilar:
    def test_identical(self):
        from services.vision import _color_similar
        assert _color_similar("розовый", "розовый") is True

    def test_case_insensitive(self):
        from services.vision import _color_similar
        assert _color_similar("Розовый", "розовый") is True

    def test_different(self):
        from services.vision import _color_similar
        assert _color_similar("розовый", "синий") is False

    def test_whitespace(self):
        from services.vision import _color_similar
        assert _color_similar("  розовый  ", "розовый") is True


class TestFixBbox:
    def test_normal_bbox_unchanged(self):
        from services.vision import _fix_bbox
        data = {
            "type": "кофта", "category_group": "top",
            "bbox": {"x": 0.2, "y": 0.2, "w": 0.4, "h": 0.4},
        }
        result = _fix_bbox(data)
        assert result["bbox"]["w"] == 0.4

    def test_oversized_bbox_shrunk(self):
        from services.vision import _fix_bbox
        data = {
            "type": "кофта", "category_group": "top",
            "bbox": {"x": 0.0, "y": 0.0, "w": 0.9, "h": 0.9},
        }
        result = _fix_bbox(data)
        assert result["bbox"]["w"] < 0.55

    def test_no_bbox(self):
        from services.vision import _fix_bbox
        data = {"type": "кофта"}
        result = _fix_bbox(data)
        assert "bbox" not in result

    def test_small_item_stricter_limit(self):
        from services.vision import _fix_bbox
        data = {
            "type": "носки", "category_group": "base_layer",
            "bbox": {"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5},
        }
        result = _fix_bbox(data)
        # base_layer max_dim=0.25, so 0.5 is oversized
        assert result["bbox"]["w"] < 0.25

    def test_outerwear_lenient_limit(self):
        from services.vision import _fix_bbox
        data = {
            "type": "куртка", "category_group": "outerwear",
            "bbox": {"x": 0.05, "y": 0.05, "w": 0.7, "h": 0.7},
        }
        result = _fix_bbox(data)
        # outerwear max_dim=0.75, so 0.7 is fine
        assert result["bbox"]["w"] == 0.7


class TestDefaultScore:
    def test_returns_breakdown_and_total(self):
        from services.vision import _default_score
        breakdown, total = _default_score()
        assert len(breakdown) == 11
        assert all(v == 1 for v in breakdown.values())
        assert isinstance(total, float)


class TestCropBbox:
    def _make_image(self, w=200, h=300):
        img = Image.new("RGB", (w, h), (255, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        return buf.getvalue()

    def test_full_image(self):
        from services.vision import _crop_bbox
        result = _crop_bbox(self._make_image(), {"x": 0, "y": 0, "w": 1.0, "h": 1.0})
        img = Image.open(io.BytesIO(result))
        assert img.size == (200, 300)

    def test_quarter_crop(self):
        from services.vision import _crop_bbox
        result = _crop_bbox(self._make_image(), {"x": 0, "y": 0, "w": 0.5, "h": 0.5})
        img = Image.open(io.BytesIO(result))
        assert img.size == (100, 150)

    def test_clamps_values(self):
        from services.vision import _crop_bbox
        # Negative x, oversize w — should clamp
        result = _crop_bbox(self._make_image(), {"x": -0.5, "y": -0.5, "w": 3.0, "h": 3.0})
        img = Image.open(io.BytesIO(result))
        assert img.width > 0 and img.height > 0


class TestCheckCropQuality:
    def test_fully_opaque(self):
        from services.vision import _check_crop_quality
        img = Image.new("RGBA", (10, 10), (255, 0, 0, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        assert _check_crop_quality(buf.getvalue(), 0.15) is True

    def test_fully_transparent(self):
        from services.vision import _check_crop_quality
        img = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        assert _check_crop_quality(buf.getvalue(), 0.15) is False

    def test_invalid_bytes_returns_true(self):
        from services.vision import _check_crop_quality
        assert _check_crop_quality(b"not an image", 0.15) is True


# ── API call tests (mocked) ──────────────────────────────────────────────


class TestCallVision:
    @pytest.fixture
    def mock_pool(self):
        pool = AsyncMock()
        return pool

    def _make_response(self, text):
        resp = MagicMock()
        block = MagicMock()
        block.text = text
        resp.content = [block]
        return resp

    @pytest.mark.asyncio
    async def test_parses_valid_json_array(self, mock_pool):
        items = [{"type": "Кофта", "color": "Синий", "category_group": "top"}]
        mock_pool.create_message.return_value = self._make_response(json.dumps(items))
        with patch("services.vision.get_anthropic_pool", return_value=mock_pool):
            from services.vision import _call_vision
            result = await _call_vision(b"fake_jpeg")
        assert len(result) == 1
        assert result[0]["type"] == "кофта"  # lowercased
        assert result[0]["color"] == "синий"

    @pytest.mark.asyncio
    async def test_wraps_single_dict(self, mock_pool):
        item = {"type": "Платье", "color": "красный", "category_group": "one_piece"}
        mock_pool.create_message.return_value = self._make_response(json.dumps(item))
        with patch("services.vision.get_anthropic_pool", return_value=mock_pool):
            from services.vision import _call_vision
            result = await _call_vision(b"fake_jpeg")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_strips_markdown_fences(self, mock_pool):
        items = [{"type": "шапка", "color": "белый"}]
        text = f"```json\n{json.dumps(items)}\n```"
        mock_pool.create_message.return_value = self._make_response(text)
        with patch("services.vision.get_anthropic_pool", return_value=mock_pool):
            from services.vision import _call_vision
            result = await _call_vision(b"fake_jpeg")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_recovers_truncated_json(self, mock_pool):
        # Simulate truncated response (missing closing bracket)
        text = '[{"type": "кофта", "color": "синий"}, {"type": "штаны"'
        mock_pool.create_message.return_value = self._make_response(text)
        with patch("services.vision.get_anthropic_pool", return_value=mock_pool):
            from services.vision import _call_vision
            result = await _call_vision(b"fake_jpeg")
        # Should recover first item
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_invalid_json_returns_empty(self, mock_pool):
        mock_pool.create_message.return_value = self._make_response("not json at all")
        with patch("services.vision.get_anthropic_pool", return_value=mock_pool):
            from services.vision import _call_vision
            result = await _call_vision(b"fake_jpeg")
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_response_returns_empty(self, mock_pool):
        resp = MagicMock()
        resp.content = []
        mock_pool.create_message.return_value = resp
        with patch("services.vision.get_anthropic_pool", return_value=mock_pool):
            from services.vision import _call_vision
            result = await _call_vision(b"fake_jpeg")
        assert result == []

    @pytest.mark.asyncio
    async def test_non_list_non_dict_returns_empty(self, mock_pool):
        mock_pool.create_message.return_value = self._make_response('"just a string"')
        with patch("services.vision.get_anthropic_pool", return_value=mock_pool):
            from services.vision import _call_vision
            result = await _call_vision(b"fake_jpeg")
        assert result == []


class TestCallRateVision:
    @pytest.mark.asyncio
    async def test_returns_text_response(self):
        pool = AsyncMock()
        resp = MagicMock()
        block = MagicMock()
        block.text = "⭐ Оценка: 8/10\n✅ Отлично!"
        resp.content = [block]
        pool.create_message.return_value = resp

        with patch("services.vision.get_anthropic_pool", return_value=pool), \
             patch("services.vision.AsyncReadSession") as mock_session_cls:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_session_cls.return_value = mock_session
            with patch("services.vision.get_owner_items", new_callable=AsyncMock, return_value=[]):
                from services.vision import _call_rate_vision
                result = await _call_rate_vision([b"fake"], owner_id="abc", owner_type="child")
        assert "8/10" in result

    @pytest.mark.asyncio
    async def test_fallback_on_empty_response(self):
        pool = AsyncMock()
        resp = MagicMock()
        resp.content = []
        pool.create_message.return_value = resp

        with patch("services.vision.get_anthropic_pool", return_value=pool):
            from services.vision import _call_rate_vision
            result = await _call_rate_vision([b"fake"])
        assert "Не удалось" in result


class TestBuildRatePrompt:
    def test_returns_string(self):
        from services.vision import _build_rate_prompt
        result = _build_rate_prompt([], owner_type="child")
        assert isinstance(result, str)
        assert len(result) > 50

    def test_includes_wardrobe_items(self):
        from services.vision import _build_rate_prompt
        items = [MagicMock(type="кофта", color="синий", category_group="top",
                           score_item=8.0)]
        result = _build_rate_prompt(items, owner_type="child")
        assert isinstance(result, str)
