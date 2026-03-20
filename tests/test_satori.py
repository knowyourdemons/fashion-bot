"""Satori collage renderer tests — unit + integration."""
import asyncio
import io
import os
import pathlib
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── Unit tests (no Satori server needed) ─────────────────────────────────────

class TestPastelBg:
    """_pastel_bg maps Russian color names to pastel HEX."""

    def test_known_colors(self):
        from services.image_builder import _pastel_bg
        assert _pastel_bg("розовый") == "#FFF0F2"
        assert _pastel_bg("синий") == "#EEF0FA"
        assert _pastel_bg("зелёный") == "#EEFAEE"
        assert _pastel_bg("белый") == "#F8F8F6"

    def test_compound_color(self):
        from services.image_builder import _pastel_bg
        assert _pastel_bg("тёмно-синий") == "#EEF0FA"
        assert _pastel_bg("пыльно-розовый") == "#F8F0F2"

    def test_empty_returns_default(self):
        from services.image_builder import _pastel_bg
        assert _pastel_bg("") == "#F5F3F0"
        assert _pastel_bg(None) == "#F5F3F0"

    def test_unknown_color_returns_default(self):
        from services.image_builder import _pastel_bg
        assert _pastel_bg("невидимый") == "#F5F3F0"


class TestAutoTrim:
    """_auto_trim crops transparent edges."""

    def test_trims_transparent_edges(self):
        from services.image_builder import _auto_trim
        from PIL import Image

        # Create 200x200 RGBA with content only in center 100x100
        img = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
        center = Image.new("RGBA", (100, 100), (255, 0, 0, 255))
        img.paste(center, (50, 50))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        raw = buf.getvalue()

        trimmed = _auto_trim(raw)
        result = Image.open(io.BytesIO(trimmed))
        # Should be smaller than 200x200 but bigger than 100x100 (5% padding)
        assert result.width < 200
        assert result.height < 200
        assert result.width >= 100
        assert result.height >= 100

    def test_fully_transparent_returns_original(self):
        from services.image_builder import _auto_trim
        from PIL import Image

        img = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        raw = buf.getvalue()

        result = _auto_trim(raw)
        assert result == raw

    def test_invalid_bytes_returns_original(self):
        from services.image_builder import _auto_trim
        bad = b"not an image"
        assert _auto_trim(bad) == bad


class TestImgToDataUri:
    """_img_to_data_uri produces valid data URI."""

    def test_format(self):
        from services.image_builder import _img_to_data_uri
        result = _img_to_data_uri(b"\x89PNG\r\n")
        assert result.startswith("data:image/png;base64,")
        assert len(result) >= 30


class TestSatoriCard:
    """_satori_card builds correct element tree."""

    def test_placeholder_card_structure(self):
        from services.image_builder import _satori_card
        slot = {"slot": "top", "has_item": False, "item_color": "розовый", "gender": "girl"}
        card = _satori_card(slot, "50%", "260px")

        assert card["type"] == "div"
        style = card["props"]["style"]
        assert style["display"] == "flex"
        assert style["borderRadius"] == 16
        assert style["backgroundColor"] == "#FFF0F2"  # pastel pink
        assert style["width"] == "50%"
        assert style["height"] == "260px"

    def test_photo_card_has_img(self):
        from services.image_builder import _satori_card
        from PIL import Image

        # Create minimal PNG
        img = Image.new("RGBA", (10, 10), (255, 0, 0, 255))
        buf = io.BytesIO()
        img.save(buf, "PNG")

        slot = {
            "slot": "top", "has_item": True,
            "_photo_bytes": buf.getvalue(),
            "item_type": "свитшот", "item_color": "синий",
            "gender": "girl",
        }
        card = _satori_card(slot, "100%", "340px")
        children = card["props"]["children"]

        # First child should be img
        img_el = children[0]
        assert img_el["type"] == "img"
        assert img_el["props"]["src"].startswith("data:image/png;base64,")

    def test_card_label_for_item(self):
        from services.image_builder import _satori_card
        slot = {"slot": "outerwear", "has_item": True, "_photo_bytes": None,
                "item_type": "куртка", "item_color": "красный", "gender": "girl"}
        card = _satori_card(slot, "100%", "340px")
        children = card["props"]["children"]
        # Last child is label div
        label_el = children[-1]
        assert "Куртка" in label_el["props"]["children"]


class TestSatoriRow:
    """_satori_row wraps cards in flex row."""

    def test_row_structure(self):
        from services.image_builder import _satori_row
        cards = [{"type": "div", "props": {}}, {"type": "div", "props": {}}]
        row = _satori_row(cards)
        assert row["type"] == "div"
        assert row["props"]["style"]["display"] == "flex"
        assert row["props"]["style"]["flexDirection"] == "row"
        assert len(row["props"]["children"]) == 2


class TestLoadSilhouetteBytes:
    """_load_silhouette_bytes finds PNG files."""

    def test_loads_existing_silhouette(self):
        from services.image_builder import _load_silhouette_bytes
        result = _load_silhouette_bytes("outerwear", "girl")
        if result is not None:
            assert result[:4] == b"\x89PNG"

    def test_returns_none_for_missing(self):
        from services.image_builder import _load_silhouette_bytes
        result = _load_silhouette_bytes("nonexistent_slot_xyz")
        assert result is None


class TestBuildCollageSatoriZones:
    """build_collage_satori correctly splits slots into zones."""

    def test_empty_slots_returns_none(self):
        from services.image_builder import build_collage_satori
        result = _run(build_collage_satori([], "header"))
        assert result is None

    def test_only_zone3_slots(self):
        """Only footwear/accessories → still renders."""
        from services.image_builder import build_collage_satori

        slots = [
            {"slot": "footwear", "has_item": False, "item_color": "", "gender": "girl"},
            {"slot": "hat", "has_item": False, "item_color": "", "gender": "girl"},
        ]
        with patch("services.image_builder._render_satori", new_callable=AsyncMock) as mock:
            mock.return_value = b"\x89PNG fake"
            result = _run(build_collage_satori(slots, "Test", style="magazine"))
            assert result is not None
            mock.assert_called_once()


class TestCollageStyles:
    """All 6 styles produce valid element trees."""

    def _slots(self):
        return [
            {"slot": "outerwear", "has_item": False, "item_color": "синий", "gender": "girl", "label": "Куртка"},
            {"slot": "top", "has_item": False, "item_color": "белый", "gender": "girl", "label": "Лонгслив"},
            {"slot": "bottom", "has_item": False, "item_color": "розовый", "gender": "girl", "label": "Юбка"},
            {"slot": "footwear", "has_item": False, "item_color": "", "gender": "girl", "label": "Ботинки"},
        ]

    def test_all_styles_build_valid_elements(self):
        from services.collage_styles import BUILDERS, collect_palette
        slots = self._slots()
        palette = collect_palette(slots)
        for name, builder in BUILDERS.items():
            element, w, h = builder(slots, "Алиса", "Касси", palette)
            assert element["type"] == "div", f"{name}: root not div"
            assert w > 0 and h > 0, f"{name}: invalid dimensions"
            assert "children" in element["props"], f"{name}: no children"

    def test_magazine_has_dark_header(self):
        from services.collage_styles import build_magazine, collect_palette
        slots = self._slots()
        el, _, _ = build_magazine(slots, "Test", "Footer", collect_palette(slots))
        # First child should have dark background
        first = el["props"]["children"][0]
        bg = first["props"]["style"].get("backgroundColor", "")
        assert bg == "#1a1a2e"

    def test_editorial_has_white_bg(self):
        from services.collage_styles import build_editorial, collect_palette
        slots = self._slots()
        el, _, _ = build_editorial(slots, "Test", "Footer", collect_palette(slots))
        assert el["props"]["style"]["backgroundColor"] == "#FFFFFF"

    def test_story_card_has_gradient(self):
        from services.collage_styles import build_story_card, collect_palette
        slots = self._slots()
        el, _, _ = build_story_card(slots, "Test", "Footer", collect_palette(slots))
        bg = el["props"]["style"].get("backgroundImage", "")
        assert "linear-gradient" in bg

    def test_polaroid_has_warm_bg(self):
        from services.collage_styles import build_polaroid, collect_palette
        slots = self._slots()
        el, _, _ = build_polaroid(slots, "Test", "Footer", collect_palette(slots))
        assert el["props"]["style"]["backgroundColor"] == "#F5F0EB"

    def test_pro_stylist_minimal(self):
        from services.collage_styles import build_pro_stylist, collect_palette
        slots = self._slots()
        el, _, _ = build_pro_stylist(slots, "Test", "Footer", collect_palette(slots))
        assert el["props"]["style"]["backgroundColor"] == "#FFFFFF"


class TestRoundRobin:
    """Style rotation works correctly."""

    def test_next_style_cycles(self):
        from services.collage_styles import next_style, STYLES, _style_counter
        import services.collage_styles as mod
        old = mod._style_counter
        mod._style_counter = 0
        try:
            results = [next_style() for _ in range(12)]
            assert results == STYLES + STYLES
        finally:
            mod._style_counter = old

    def test_build_collage_satori_rotates(self):
        from services.image_builder import build_collage_satori
        import services.collage_styles as mod
        mod._style_counter = 0

        slots = [{"slot": "top", "has_item": False, "item_color": "", "gender": "girl"}]
        styles_used = []

        with patch("services.image_builder._render_satori", new_callable=AsyncMock) as mock:
            mock.return_value = b"\x89PNG fake"
            for _ in range(6):
                _run(build_collage_satori(slots, "Test"))
            # Check logs would show different styles — we verify counter advanced
            assert mod._style_counter >= 6


class TestCollectPalette:
    """collect_palette extracts unique colors from slots."""

    def test_deduplicates(self):
        from services.collage_styles import collect_palette
        slots = [
            {"item_color": "розовый"},
            {"item_color": "розовый"},
            {"item_color": "синий"},
        ]
        result = collect_palette(slots)
        assert len(result) == 2

    def test_max_6(self):
        from services.collage_styles import collect_palette
        slots = [{"item_color": c} for c in
                 ["розовый", "синий", "белый", "чёрный", "зелёный", "красный", "жёлтый", "бежевый"]]
        assert len(collect_palette(slots)) == 6

    def test_empty_slots(self):
        from services.collage_styles import collect_palette
        assert collect_palette([]) == []
        assert collect_palette([{"item_color": ""}]) == []


class TestSatoriFallback:
    """build_collage falls back to PIL when Satori fails."""

    def test_fallback_on_satori_failure(self):
        """When Satori returns None, PIL should be used."""
        from services.image_builder import build_collage

        slots = [
            {"slot": "top", "has_item": False, "item_color": "", "gender": "girl", "label": "Верх"},
        ]
        with patch("services.image_builder.build_collage_satori", new_callable=AsyncMock) as mock_sat:
            mock_sat.return_value = None  # Satori fails
            with patch("services.image_builder._build_layered_layout") as mock_pil:
                from PIL import Image
                mock_pil.return_value = Image.new("RGB", (100, 100), (255, 255, 255))
                result = _run(build_collage(outfit_slots=slots))
                # PIL should have been called
                mock_pil.assert_called_once()
                assert result is not None


# ── Integration tests (need Satori server) ──────────────────────────────────

class TestSatoriIntegration:
    """Live Satori server integration."""

    def _satori_available(self) -> bool:
        try:
            import urllib.request
            r = urllib.request.urlopen("http://renderer:3100/health", timeout=2)
            return r.status == 200
        except Exception:
            return False

    def test_render_satori_returns_png(self):
        if not self._satori_available():
            pytest.skip("Satori server not available")

        from services.image_builder import _render_satori

        element = {
            "type": "div",
            "props": {
                "style": {
                    "display": "flex",
                    "width": "100%",
                    "height": "100%",
                    "backgroundColor": "#1a1a2e",
                    "color": "white",
                    "fontFamily": "DejaVu",
                    "fontSize": 20,
                },
                "children": "Test render",
            },
        }
        result = _run(_render_satori(element, 400, 200))
        assert result is not None
        assert result[:4] == b"\x89PNG"
        assert len(result) > 100

    def test_all_6_styles_render(self):
        if not self._satori_available():
            pytest.skip("Satori server not available")

        from services.image_builder import build_collage_satori
        from services.collage_styles import STYLES

        slots = [
            {"slot": "outerwear", "has_item": False, "item_color": "синий", "gender": "girl"},
            {"slot": "top", "has_item": False, "item_color": "белый", "gender": "girl"},
            {"slot": "bottom", "has_item": False, "item_color": "розовый", "gender": "girl"},
            {"slot": "footwear", "has_item": False, "item_color": "коричневый", "gender": "girl"},
        ]
        for style in STYLES:
            result = _run(build_collage_satori(slots, "Алиса  +4C", style=style))
            assert result is not None, f"Style {style} failed"
            assert result[:4] == b"\x89PNG", f"Style {style} not PNG"
            assert len(result) > 5_000, f"Style {style} too small: {len(result)}"

    def test_collage_with_only_top_bottom(self):
        """Warm weather: no outerwear — all styles handle it."""
        if not self._satori_available():
            pytest.skip("Satori server not available")

        from services.image_builder import build_collage_satori

        slots = [
            {"slot": "top", "has_item": False, "item_color": "белый", "gender": "girl"},
            {"slot": "bottom", "has_item": False, "item_color": "голубой", "gender": "girl"},
        ]
        result = _run(build_collage_satori(slots, "Лето", style="editorial"))
        assert result is not None
        assert len(result) > 5_000

    def test_render_satori_timeout_returns_none(self):
        """Bad URL → returns None (not crash)."""
        from services.image_builder import _render_satori

        with patch("services.image_builder.SATORI_URL", "http://192.0.2.1:9999/render"):
            with patch("services.image_builder.SATORI_TIMEOUT", 1):
                result = _run(_render_satori({"type": "div", "props": {}}, 100, 100))
                assert result is None
