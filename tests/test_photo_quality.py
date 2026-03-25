"""
Photo quality assessment tests.

Simulates all possible photo upload variations:
- Resolution (thumbnail vs full)
- Brightness (dark room, overexposed, normal)
- Blur (motion blur, out of focus, sharp)
- Aspect ratio (panorama, screenshot, normal)
- Contrast (flat/washed out vs good)
- Auto-correction (dark → brightened for Vision)
- Format edge cases

Uses PIL to generate synthetic test images — no real photos needed.
"""
import pytest
from io import BytesIO
from PIL import Image, ImageDraw, ImageFilter

pytest.importorskip("structlog", reason="structlog not installed")

from services.photo_quality import (
    assess_photo, preprocess_for_vision, PhotoQuality,
    MIN_RESOLUTION, MIN_BRIGHTNESS, MAX_BRIGHTNESS,
    MIN_BLUR_VARIANCE, MIN_CONTRAST, MAX_ASPECT_RATIO,
)


# ══════════════════════════════════════════════════════════════════════════════
# SYNTHETIC IMAGE GENERATORS
# ══════════════════════════════════════════════════════════════════════════════

def _make_image(
    width=800, height=1000, brightness=128, add_detail=True,
    blur_radius=0, format="JPEG",
) -> bytes:
    """Generate a synthetic photo with controllable properties."""
    img = Image.new("RGB", (width, height), (brightness, brightness, brightness))
    draw = ImageDraw.Draw(img)

    if add_detail:
        # Add shapes to simulate clothing item details
        # (creates contrast and prevents flat/blur false positives)
        for i in range(10):
            x = 100 + i * 60
            y = 100 + i * 80
            color = (
                min(255, brightness + 50 + i * 10),
                min(255, brightness - 20 + i * 5),
                min(255, brightness + 30),
            )
            draw.rectangle([x, y, x + 120, y + 150], fill=color, outline=(0, 0, 0))
            draw.ellipse([x + 20, y + 20, x + 100, y + 100],
                         fill=(max(0, brightness - 40), brightness, min(255, brightness + 60)))

    if blur_radius > 0:
        img = img.filter(ImageFilter.GaussianBlur(radius=blur_radius))

    buf = BytesIO()
    img.save(buf, format=format, quality=85)
    return buf.getvalue()


def _make_dark_photo(brightness=25) -> bytes:
    """Simulate a photo taken in a dark room."""
    return _make_image(brightness=brightness)


def _make_overexposed_photo() -> bytes:
    """Simulate an overexposed/flash photo."""
    return _make_image(brightness=250, add_detail=False)


def _make_blurry_photo() -> bytes:
    """Simulate a motion-blurred photo."""
    return _make_image(blur_radius=15)


def _make_tiny_photo() -> bytes:
    """Simulate a thumbnail/preview image."""
    return _make_image(width=100, height=100)


def _make_panorama() -> bytes:
    """Simulate a panorama/screenshot (extreme aspect ratio)."""
    return _make_image(width=2000, height=400)


def _make_good_photo() -> bytes:
    """Simulate a well-lit, sharp photo of clothing on contrasting background."""
    img = Image.new("RGB", (1200, 1600), (230, 225, 220))  # light beige background
    draw = ImageDraw.Draw(img)
    # Large clothing item with strong contrast
    draw.rectangle([200, 200, 1000, 800], fill=(60, 80, 140))   # dark blue top
    draw.rectangle([250, 250, 950, 750], fill=(80, 100, 160))   # lighter inner
    draw.rectangle([200, 850, 1000, 1400], fill=(50, 50, 70))   # dark pants
    draw.ellipse([400, 100, 800, 250], fill=(200, 50, 50))      # red detail
    draw.rectangle([350, 1420, 850, 1550], fill=(150, 120, 80)) # shoes
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _make_flat_photo() -> bytes:
    """Simulate a photo with no contrast (all same color)."""
    return _make_image(brightness=150, add_detail=False)


def _make_phone_camera_photo(quality_tier="mid"):
    """Simulate different phone camera qualities."""
    configs = {
        "low": {"width": 640, "height": 480, "brightness": 100, "blur_radius": 3},
        "mid": {"width": 1280, "height": 960, "brightness": 130, "blur_radius": 0},
        "high": {"width": 4032, "height": 3024, "brightness": 140, "blur_radius": 0},
    }
    cfg = configs[quality_tier]
    return _make_image(**cfg)


# ══════════════════════════════════════════════════════════════════════════════
# BASIC QUALITY CHECKS
# ══════════════════════════════════════════════════════════════════════════════

class TestResolution:
    """Test resolution validation."""

    def test_normal_photo_passes(self):
        q = assess_photo(_make_good_photo())
        assert q.is_usable
        assert "too_small" not in q.issues

    def test_tiny_photo_rejected(self):
        q = assess_photo(_make_tiny_photo())
        assert not q.is_usable
        assert "too_small" in q.issues
        assert any("маленькое" in t for t in q.tips)

    def test_borderline_resolution(self):
        """200×200 is minimum — should pass."""
        photo = _make_image(width=200, height=200)
        q = assess_photo(photo)
        assert q.is_usable

    def test_below_minimum(self):
        """199×199 — should fail."""
        photo = _make_image(width=199, height=199)
        q = assess_photo(photo)
        assert not q.is_usable

    @pytest.mark.parametrize("w,h", [(640, 480), (1280, 960), (4032, 3024)])
    def test_common_phone_resolutions(self, w, h):
        photo = _make_image(width=w, height=h)
        q = assess_photo(photo)
        assert q.is_usable


class TestBrightness:
    """Test brightness detection and auto-correction."""

    def test_normal_brightness_passes(self):
        q = assess_photo(_make_good_photo())
        assert "too_dark" not in q.issues
        assert "overexposed" not in q.issues

    def test_dark_photo_detected(self):
        q = assess_photo(_make_dark_photo(brightness=25))
        assert "too_dark" in q.issues
        assert any("тёмное" in t or "свет" in t for t in q.tips)

    def test_dark_photo_auto_corrected(self):
        """Dark photos should be brightness-corrected for Vision."""
        q = assess_photo(_make_dark_photo(brightness=25))
        assert q.was_corrected
        assert q.corrected_bytes is not None
        assert len(q.corrected_bytes) > 0

        # Corrected image should be brighter
        corrected_img = Image.open(BytesIO(q.corrected_bytes))
        from PIL import ImageStat
        stat = ImageStat.Stat(corrected_img)
        corrected_brightness = sum(stat.mean[:3]) / 3
        assert corrected_brightness > q.brightness, "Corrected image should be brighter"

    def test_dark_photo_still_usable(self):
        """Dark photos are usable (after correction) — don't reject."""
        q = assess_photo(_make_dark_photo(brightness=30))
        assert q.is_usable  # warning but usable

    def test_overexposed_detected(self):
        q = assess_photo(_make_overexposed_photo())
        assert "overexposed" in q.issues
        assert any("пересвечено" in t or "вспышку" in t for t in q.tips)

    def test_borderline_brightness(self):
        """Brightness 50 = dim but acceptable."""
        photo = _make_image(brightness=50)
        q = assess_photo(photo)
        assert q.is_usable

    @pytest.mark.parametrize("brightness", [60, 80, 100, 140, 180, 220])
    def test_normal_brightness_range(self, brightness):
        """Normal brightness range should have no issues."""
        photo = _make_image(brightness=brightness)
        q = assess_photo(photo)
        assert "too_dark" not in q.issues
        assert "overexposed" not in q.issues


class TestBlur:
    """Test blur detection."""

    def test_sharp_photo_passes(self):
        q = assess_photo(_make_good_photo())
        assert "blurry" not in q.issues

    def test_very_blurry_detected(self):
        q = assess_photo(_make_blurry_photo())
        assert "blurry" in q.issues
        assert any("размытое" in t for t in q.tips)

    def test_slight_blur_passes(self):
        """Slight blur (radius 2) should pass — phones aren't perfect."""
        photo = _make_image(blur_radius=2)
        q = assess_photo(photo)
        # Slight blur should not trigger warning
        assert q.is_usable

    def test_blur_score_stored(self):
        q = assess_photo(_make_good_photo())
        assert q.blur_score > 0


class TestAspectRatio:
    """Test aspect ratio validation."""

    def test_portrait_passes(self):
        """4:5 portrait (common phone photo)."""
        photo = _make_image(width=800, height=1000)
        q = assess_photo(photo)
        assert "bad_aspect" not in q.issues

    def test_landscape_passes(self):
        """3:2 landscape."""
        photo = _make_image(width=1200, height=800)
        q = assess_photo(photo)
        assert "bad_aspect" not in q.issues

    def test_square_passes(self):
        photo = _make_image(width=800, height=800)
        q = assess_photo(photo)
        assert "bad_aspect" not in q.issues

    def test_panorama_warned(self):
        """5:1 panorama → warning."""
        photo = _make_image(width=2500, height=500)
        q = assess_photo(photo)
        assert "bad_aspect" in q.issues
        assert any("скриншот" in t or "панорам" in t for t in q.tips)

    def test_panorama_still_usable(self):
        """Panorama warned but not rejected — Vision may still find item."""
        photo = _make_image(width=2500, height=500)
        q = assess_photo(photo)
        assert q.is_usable


class TestContrast:
    """Test contrast detection."""

    def test_good_contrast_passes(self):
        q = assess_photo(_make_good_photo())
        assert "low_contrast" not in q.issues

    def test_flat_photo_warned(self):
        """All-same-color photo = no contrast."""
        q = assess_photo(_make_flat_photo())
        assert "low_contrast" in q.issues


# ══════════════════════════════════════════════════════════════════════════════
# PREPROCESSING PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

class TestPreprocessing:
    """Test preprocess_for_vision() returns corrected image when needed."""

    def test_good_photo_resized(self):
        original = _make_good_photo()
        processed, quality = preprocess_for_vision(original)
        assert quality.is_usable
        # Should be resized to 768px max (saves Vision API tokens)
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(processed))
        assert max(img.size) <= 768
        assert len(processed) < len(original)  # smaller after resize

    def test_dark_photo_corrected(self):
        original = _make_dark_photo(brightness=25)
        processed, quality = preprocess_for_vision(original)
        assert processed != original  # should be brightened
        assert quality.was_corrected
        assert len(processed) > 0

    def test_overexposed_not_corrected(self):
        """Overexposed photos are not auto-corrected (too risky), only resized."""
        original = _make_overexposed_photo()
        processed, quality = preprocess_for_vision(original)
        assert not quality.was_corrected
        # Photo is resized but not brightness-corrected
        assert len(processed) > 0


# ══════════════════════════════════════════════════════════════════════════════
# REAL-WORLD SCENARIOS
# ══════════════════════════════════════════════════════════════════════════════

class TestRealWorldScenarios:
    """Simulate common user photo situations."""

    def test_closet_dark_photo(self):
        """User takes photo inside dark closet — brightness ~30."""
        photo = _make_image(brightness=30, add_detail=True)
        q = assess_photo(photo)
        assert q.is_usable  # correctable
        assert q.was_corrected
        assert "too_dark" in q.issues

    def test_outdoor_bright_sunlight(self):
        """Bright outdoor photo — should be fine."""
        photo = _make_image(brightness=200, add_detail=True)
        q = assess_photo(photo)
        assert q.is_usable
        assert "overexposed" not in q.issues

    def test_flash_on_white_background(self):
        """Flash + white background — near overexposed."""
        photo = _make_image(brightness=240, add_detail=False)
        q = assess_photo(photo)
        # Borderline — should warn but not reject
        assert q.is_usable

    def test_blurry_moving_child(self):
        """Kid won't stand still — motion blur."""
        photo = _make_image(brightness=130, blur_radius=12)
        q = assess_photo(photo)
        assert "blurry" in q.issues

    def test_screenshot_from_store(self):
        """User sends screenshot of clothing from online store."""
        photo = _make_image(width=1080, height=350)  # typical mobile screenshot crop
        q = assess_photo(photo)
        # aspect ratio 3.08 — below 4.0 threshold, acceptable
        assert q.is_usable

    def test_whatsapp_compressed_photo(self):
        """WhatsApp heavily compresses photos — low quality but usable."""
        # WhatsApp: ~640x480, quality ~60
        img = Image.new("RGB", (640, 480), (130, 130, 130))
        draw = ImageDraw.Draw(img)
        for i in range(5):
            draw.rectangle([50 + i * 100, 50, 150 + i * 100, 400],
                           fill=(100 + i * 20, 80, 140))
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=40)  # heavy compression
        q = assess_photo(buf.getvalue())
        assert q.is_usable

    @pytest.mark.parametrize("tier", ["low", "mid", "high"])
    def test_phone_camera_tiers(self, tier):
        """Different phone cameras — all should be usable."""
        photo = _make_phone_camera_photo(tier)
        q = assess_photo(photo)
        assert q.is_usable, f"{tier} tier phone should be usable"

    def test_png_format(self):
        """PNG photos should work."""
        photo = _make_image(format="PNG")
        q = assess_photo(photo)
        assert q.is_usable

    def test_rgba_format(self):
        """RGBA images (screenshots with transparency)."""
        img = Image.new("RGBA", (800, 600), (130, 130, 130, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle([100, 100, 700, 500], fill=(200, 100, 100, 255))
        buf = BytesIO()
        img.save(buf, format="PNG")
        q = assess_photo(buf.getvalue())
        assert q.is_usable

    def test_corrupt_bytes(self):
        """Corrupt image data should not crash."""
        q = assess_photo(b"not an image at all")
        assert not q.is_usable
        assert "invalid_format" in q.issues

    def test_empty_bytes(self):
        """Empty bytes should not crash."""
        q = assess_photo(b"")
        assert not q.is_usable

    def test_single_pixel(self):
        """1×1 image — too small."""
        img = Image.new("RGB", (1, 1), (128, 128, 128))
        buf = BytesIO()
        img.save(buf, format="PNG")
        q = assess_photo(buf.getvalue())
        assert not q.is_usable


# ══════════════════════════════════════════════════════════════════════════════
# MULTI-ITEM PHOTO SCENARIOS
# ══════════════════════════════════════════════════════════════════════════════

class TestMultiItemScenarios:
    """Photos with multiple clothing items — quality should be assessed on full image."""

    def test_flat_lay_multiple_items(self):
        """Multiple items laid flat — good photo, should pass."""
        # Simulate colorful items on neutral background
        img = Image.new("RGB", (1200, 1600), (230, 230, 230))
        draw = ImageDraw.Draw(img)
        # Item 1: red top
        draw.rectangle([100, 100, 500, 500], fill=(200, 50, 50))
        # Item 2: blue bottom
        draw.rectangle([550, 100, 950, 600], fill=(50, 50, 200))
        # Item 3: shoes
        draw.ellipse([300, 700, 600, 900], fill=(100, 80, 60))
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85)
        q = assess_photo(buf.getvalue())
        assert q.is_usable
        assert len(q.issues) == 0

    def test_items_on_dark_floor(self):
        """Items on dark floor — overall image is dark."""
        img = Image.new("RGB", (1000, 1000), (30, 30, 30))
        draw = ImageDraw.Draw(img)
        draw.rectangle([200, 200, 800, 800], fill=(180, 100, 100))
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85)
        q = assess_photo(buf.getvalue())
        # Dark background but item is visible — should auto-correct
        assert q.is_usable


# ══════════════════════════════════════════════════════════════════════════════
# TIP FORMATTING
# ══════════════════════════════════════════════════════════════════════════════

class TestTipFormatting:
    """Test user-facing tip messages."""

    def test_no_tips_for_good_photo(self):
        q = assess_photo(_make_good_photo())
        assert q.tip_text() == ""

    def test_tips_have_emoji(self):
        q = assess_photo(_make_dark_photo())
        tip = q.tip_text()
        if tip:
            assert tip.startswith("💡")

    def test_should_warn_property(self):
        q = assess_photo(_make_good_photo())
        assert not q.should_warn

        q2 = assess_photo(_make_dark_photo(brightness=30))
        assert q2.should_warn  # has tips but still usable
