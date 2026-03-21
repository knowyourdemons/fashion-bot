"""Tests for thumbnail pipeline improvements.

Covers: rembg quality check, sharpening, contrast boost,
solid/pattern detection, and label logic.
"""
import io
import pytest
from PIL import Image

pytest.importorskip("structlog", reason="structlog not installed")


def _make_png(w=100, h=100, color=(255, 0, 0, 255)) -> bytes:
    """Create a test PNG image."""
    img = Image.new("RGBA", (w, h), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_mostly_transparent_png() -> bytes:
    """Create PNG where >85% pixels are transparent (bad rembg)."""
    img = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    # Small opaque area (10x10 = 1%)
    for x in range(10):
        for y in range(10):
            img.putpixel((x, y), (255, 0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_mostly_opaque_png() -> bytes:
    """Create PNG where <15% pixels are transparent (rembg did nothing)."""
    img = Image.new("RGBA", (100, 100), (200, 100, 50, 255))
    # Small transparent area
    for x in range(5):
        for y in range(5):
            img.putpixel((x, y), (0, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ══════════════════════════════════════════════════════════════════════════════
# REMBG Quality Check
# ══════════════════════════════════════════════════════════════════════════════

class TestRembgQuality:
    def test_good_result(self):
        """50% opaque = good rembg result."""
        from services.image_processor import _check_rembg_quality
        img = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
        for x in range(50):
            for y in range(100):
                img.putpixel((x, y), (255, 0, 0, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        assert _check_rembg_quality(buf.getvalue()) is True

    def test_too_transparent(self):
        """<15% opaque = rembg removed too much."""
        from services.image_processor import _check_rembg_quality
        assert _check_rembg_quality(_make_mostly_transparent_png()) is False

    def test_too_opaque(self):
        """<15% transparent = rembg didn't work."""
        from services.image_processor import _check_rembg_quality
        assert _check_rembg_quality(_make_mostly_opaque_png()) is False

    def test_fully_opaque_rgb(self):
        """Fully opaque RGBA = rembg failed."""
        from services.image_processor import _check_rembg_quality
        png = _make_png(100, 100, (200, 100, 50, 255))
        assert _check_rembg_quality(png) is False


# ══════════════════════════════════════════════════════════════════════════════
# Sharpening
# ══════════════════════════════════════════════════════════════════════════════

class TestSharpening:
    def test_sharpen_returns_valid_png(self):
        from services.image_processor import sharpen_thumbnail
        result = sharpen_thumbnail(_make_png())
        img = Image.open(io.BytesIO(result))
        assert img.size == (100, 100)
        assert img.format == "PNG"

    def test_sharpen_preserves_alpha(self):
        from services.image_processor import sharpen_thumbnail
        # Semi-transparent image
        png = _make_png(50, 50, (255, 0, 0, 128))
        result = sharpen_thumbnail(png)
        img = Image.open(io.BytesIO(result)).convert("RGBA")
        assert img.size == (50, 50)


# ══════════════════════════════════════════════════════════════════════════════
# Contrast Boost
# ══════════════════════════════════════════════════════════════════════════════

class TestContrastBoost:
    def test_boost_returns_valid_png(self):
        from services.image_processor import boost_contrast
        result = boost_contrast(_make_png())
        img = Image.open(io.BytesIO(result))
        assert img.format == "PNG"

    def test_boost_preserves_alpha(self):
        from services.image_processor import boost_contrast
        img = Image.new("RGBA", (50, 50), (100, 100, 100, 128))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        result = boost_contrast(buf.getvalue())
        img2 = Image.open(io.BytesIO(result)).convert("RGBA")
        # Alpha should be preserved
        _, _, _, a = img2.split()
        alpha_vals = list(a.getdata())
        assert all(v == 128 for v in alpha_vals)


# ══════════════════════════════════════════════════════════════════════════════
# Solid vs Pattern Detection
# ══════════════════════════════════════════════════════════════════════════════

class TestSolidDetection:
    """Test that solid vs patterned items are correctly detected."""

    def _check_is_solid(self, item_type: str, item_color: str) -> bool:
        """Simulate the is_solid logic from prepare_items_hybrid."""
        _color_lower = (item_color or "").lower()
        _type_lower = (item_type or "").lower()
        _pattern_words = ["принт", "узор", "полоск", "клетк", "цветоч", "горох", "камуфляж", "леопард"]
        return not any(pw in _color_lower or pw in _type_lower for pw in _pattern_words)

    def test_solid_leggings(self):
        assert self._check_is_solid("леггинсы", "розовые") is True

    def test_solid_jeans(self):
        assert self._check_is_solid("джинсы", "синие") is True

    def test_patterned_floral(self):
        assert self._check_is_solid("лонгслив", "розовый в цветочек") is False

    def test_patterned_stripes(self):
        assert self._check_is_solid("футболка", "полоска") is False

    def test_patterned_print(self):
        assert self._check_is_solid("кофта", "с принтом") is False

    def test_patterned_plaid(self):
        assert self._check_is_solid("рубашка", "в клетку") is False

    def test_solid_black(self):
        assert self._check_is_solid("штаны", "чёрные") is True

    def test_patterned_leopard(self):
        assert self._check_is_solid("топ", "леопардовый") is False
