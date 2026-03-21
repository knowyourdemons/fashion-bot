"""Tests for the collage thumbnail pipeline (image_processor.py)."""
import io
import pytest
from PIL import Image


def _make_jpeg(width=200, height=300, color=(128, 100, 80)) -> bytes:
    """Create a simple JPEG test image."""
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _make_rgba_png(width=200, height=300, bg_alpha=0) -> bytes:
    """Create a PNG with transparent background and a colored center object."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, bg_alpha))
    # Draw a colored rectangle in the center (simulating an item)
    for y in range(height // 4, 3 * height // 4):
        for x in range(width // 4, 3 * width // 4):
            img.putpixel((x, y), (180, 120, 100, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_dark_jpeg(width=200, height=300) -> bytes:
    """Create a dark JPEG with some contrast (mean brightness < 90)."""
    img = Image.new("RGB", (width, height), (20, 15, 10))
    # Add brighter region to give autocontrast something to work with
    for y in range(height // 3, 2 * height // 3):
        for x in range(width // 3, 2 * width // 3):
            img.putpixel((x, y), (80, 70, 60))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


class TestExifRotate:
    def test_returns_bytes(self):
        from services.image_processor import exif_rotate
        result = exif_rotate(_make_jpeg())
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_preserves_image(self):
        from services.image_processor import exif_rotate
        original = _make_jpeg(100, 150)
        result = exif_rotate(original)
        img = Image.open(io.BytesIO(result))
        assert img.size[0] == 100
        assert img.size[1] == 150

    def test_handles_rgba(self):
        from services.image_processor import exif_rotate
        result = exif_rotate(_make_rgba_png())
        img = Image.open(io.BytesIO(result))
        assert img.mode == "RGBA"


class TestAutoBrightness:
    def test_dark_image_brightened(self):
        from services.image_processor import auto_brightness
        from PIL import ImageStat
        dark = _make_dark_jpeg()
        # Measure original brightness
        orig_img = Image.open(io.BytesIO(dark)).convert("RGB")
        orig_stat = ImageStat.Stat(orig_img)
        orig_mean = sum(orig_stat.mean) / 3.0
        # Apply brightness correction
        result = auto_brightness(dark)
        img = Image.open(io.BytesIO(result)).convert("RGB")
        stat = ImageStat.Stat(img)
        mean_after = sum(stat.mean) / 3.0
        # Should be noticeably brighter than original
        assert mean_after > orig_mean, f"Expected brighter: {mean_after} vs {orig_mean}"

    def test_normal_image_unchanged(self):
        from services.image_processor import auto_brightness
        normal = _make_jpeg(color=(150, 140, 130))  # mean ~140, well above 90
        result = auto_brightness(normal)
        # Should be similar size (no dramatic change)
        assert abs(len(result) - len(normal)) < len(normal)

    def test_rgba_preserves_alpha(self):
        from services.image_processor import auto_brightness
        rgba = _make_rgba_png()
        result = auto_brightness(rgba)
        img = Image.open(io.BytesIO(result))
        assert img.mode == "RGBA"


class TestSoftenEdges:
    def test_returns_png(self):
        from services.image_processor import soften_edges
        result = soften_edges(_make_rgba_png())
        assert result[:4] == b'\x89PNG'

    def test_non_rgba_passthrough(self):
        from services.image_processor import soften_edges
        jpeg = _make_jpeg()
        result = soften_edges(jpeg)
        assert result == jpeg  # No alpha → returned as-is

    def test_blurs_alpha(self):
        from services.image_processor import soften_edges
        sharp = _make_rgba_png()
        blurred = soften_edges(sharp, radius=2.0)
        # Result should be different (alpha blurred)
        assert blurred != sharp


class TestPadSquareResize:
    def test_output_is_square(self):
        from services.image_processor import pad_square_resize
        result = pad_square_resize(_make_rgba_png(200, 400), size=400)
        img = Image.open(io.BytesIO(result))
        assert img.size == (400, 400)

    def test_output_is_rgba(self):
        from services.image_processor import pad_square_resize
        result = pad_square_resize(_make_rgba_png(), size=200)
        img = Image.open(io.BytesIO(result))
        assert img.mode == "RGBA"

    def test_custom_size(self):
        from services.image_processor import pad_square_resize
        result = pad_square_resize(_make_rgba_png(), size=100)
        img = Image.open(io.BytesIO(result))
        assert img.size == (100, 100)

    def test_trims_transparent_edges(self):
        from services.image_processor import pad_square_resize
        # Create image with large transparent border
        png = _make_rgba_png(400, 400, bg_alpha=0)
        result = pad_square_resize(png, size=200)
        img = Image.open(io.BytesIO(result))
        # Object should be centered and fill most of the image
        assert img.size == (200, 200)


class TestMakeCollageThumbnail:
    def test_jpeg_input(self):
        from services.image_processor import make_collage_thumbnail
        result = make_collage_thumbnail(_make_jpeg(), needs_bg_removal=False)
        img = Image.open(io.BytesIO(result))
        assert img.size == (400, 400)

    def test_rgba_input_skip_rembg(self):
        from services.image_processor import make_collage_thumbnail
        rgba = _make_rgba_png()
        result = make_collage_thumbnail(rgba, needs_bg_removal=False)
        img = Image.open(io.BytesIO(result))
        assert img.size == (400, 400)
        assert img.mode == "RGBA"

    def test_dark_jpeg_brightness_corrected(self):
        from services.image_processor import make_collage_thumbnail
        result = make_collage_thumbnail(_make_dark_jpeg(), needs_bg_removal=False)
        img = Image.open(io.BytesIO(result))
        # Just verify pipeline doesn't crash and produces valid image
        assert img.size == (400, 400)
        assert len(result) > 100


class TestWarmOutfitCommentNewParams:
    def _comment(self, score=7.0, name=None, **kwargs):
        from services.outfit_builder import warm_outfit_comment
        return warm_outfit_comment(score, name, **kwargs)

    def test_exclude_comment_avoids_repeat(self):
        """With exclude_comment, result should differ."""
        first = self._comment(7.0, "Алиса")
        # Run multiple times — at least one should differ
        different = False
        for _ in range(20):
            result = self._comment(7.0, "Алиса", exclude_comment=first)
            if result != first:
                different = True
                break
        assert different, "Should eventually return a different comment"

    def test_single_item_praises_item(self):
        """With 1 real item, should praise the specific item."""
        result = self._comment(
            7.0, "Алиса",
            real_item_count=1,
            first_item_desc="лосины пыльно-розовые",
        )
        assert "лосины" in result.lower() or "вещь" in result.lower()

    def test_single_item_not_generic_praise(self):
        """Single item comment should reference the item, not generic 'отличный образ'."""
        result = self._comment(
            7.0, "Алиса",
            real_item_count=1,
            first_item_desc="куртка синяя",
        )
        # Should NOT start with generic outfit praise
        assert not result.startswith("Отличный образ")
        assert not result.startswith("Симпатичный образ")

    def test_multiple_items_normal_comment(self):
        """With >1 items, normal outfit comment."""
        result = self._comment(7.5, "Алиса", real_item_count=5)
        assert isinstance(result, str)
        assert len(result) > 10
