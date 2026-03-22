"""
Photo quality assessment before Vision API call.

Checks brightness, blur, resolution, and aspect ratio
BEFORE sending to Claude Vision ($0.003/call).
Returns specific user-actionable tips if quality is low.

Design:
- Fast (< 50ms per check)
- No false positives (prefer sending bad photo to Vision
  over rejecting a good one)
- Specific tips (not "фото плохое", but "слишком тёмно — включи свет")
"""
from io import BytesIO

from PIL import Image, ImageFilter, ImageStat


# ── Quality thresholds ───────────────────────────────────────────────────────
# Calibrated conservatively — only reject clearly unusable photos.

MIN_RESOLUTION = 200          # px: smaller than 200x200 = thumbnails/icons
MAX_ASPECT_RATIO = 4.0        # width/height or height/width > 4 = panorama/screenshot
MIN_BRIGHTNESS = 40           # 0-255 mean; <40 = very dark room photo
MAX_BRIGHTNESS = 245          # >245 = overexposed/white
MIN_BLUR_VARIANCE = 30.0      # Laplacian variance; <30 = very blurry
MIN_CONTRAST = 15.0           # std dev of luminance; <15 = extremely flat


class PhotoQuality:
    """Result of photo quality assessment."""

    def __init__(self):
        self.is_usable: bool = True
        self.issues: list[str] = []          # machine-readable issue codes
        self.tips: list[str] = []            # user-facing tips (Russian)
        self.brightness: float = 128.0
        self.blur_score: float = 100.0
        self.width: int = 0
        self.height: int = 0
        self.was_corrected: bool = False     # True if brightness was auto-fixed
        self.corrected_bytes: bytes | None = None  # enhanced image for Vision

    @property
    def should_warn(self) -> bool:
        """True if quality is borderline — send to Vision but warn user."""
        return len(self.tips) > 0 and self.is_usable

    def tip_text(self) -> str:
        """Format tips for user message."""
        if not self.tips:
            return ""
        return "💡 " + " ".join(self.tips)


def assess_photo(photo_bytes: bytes) -> PhotoQuality:
    """Assess photo quality before Vision API call.

    Returns PhotoQuality with is_usable flag and specific tips.
    Fast: < 50ms on typical phone photos.

    Does NOT reject borderline photos — only clearly unusable ones.
    For borderline, sets tips but keeps is_usable=True.
    """
    result = PhotoQuality()

    try:
        img = Image.open(BytesIO(photo_bytes))
    except Exception:
        result.is_usable = False
        result.issues.append("invalid_format")
        result.tips.append("Не могу открыть файл. Отправь фото в формате JPEG или PNG.")
        return result

    # Convert to RGB for analysis
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        img_rgb = bg
    elif img.mode != "RGB":
        img_rgb = img.convert("RGB")
    else:
        img_rgb = img

    result.width, result.height = img.size

    # ── Resolution check ──
    min_dim = min(img.size)
    if min_dim < MIN_RESOLUTION:
        result.is_usable = False
        result.issues.append("too_small")
        result.tips.append(f"Фото слишком маленькое ({img.size[0]}×{img.size[1]}). Отправь оригинал, не превью.")
        return result

    # ── Aspect ratio check ──
    w, h = img.size
    ratio = max(w / h, h / w) if min(w, h) > 0 else 1
    if ratio > MAX_ASPECT_RATIO:
        result.issues.append("bad_aspect")
        result.tips.append("Похоже на скриншот или панораму. Сфоткай вещь отдельно.")
        # Still usable — Vision may detect item

    # ── Brightness check ──
    stat = ImageStat.Stat(img_rgb)
    # Mean brightness across RGB channels
    result.brightness = sum(stat.mean[:3]) / 3

    corrected_img = None

    if result.brightness < MIN_BRIGHTNESS:
        result.issues.append("too_dark")
        result.tips.append("Фото тёмное — включи свет или сфоткай днём у окна.")
        # Try to auto-correct brightness for Vision
        from PIL import ImageEnhance
        enhancer = ImageEnhance.Brightness(img_rgb)
        factor = 120.0 / max(result.brightness, 1)  # target mean ~120
        factor = min(factor, 3.0)  # don't over-brighten
        corrected_img = enhancer.enhance(factor)
        result.was_corrected = True
    elif result.brightness > MAX_BRIGHTNESS:
        result.issues.append("overexposed")
        result.tips.append("Фото пересвечено — убери вспышку и сфоткай при мягком свете.")

    # ── Contrast check ──
    gray = img_rgb.convert("L")
    gray_stat = ImageStat.Stat(gray)
    contrast = gray_stat.stddev[0]

    if contrast < MIN_CONTRAST:
        result.issues.append("low_contrast")
        if "too_dark" not in result.issues:
            result.tips.append("Фото слишком однотонное — положи вещь на контрастный фон.")

    # ── Blur detection (Laplacian variance) ──
    # Resize to 500px max for consistent blur measurement
    analysis_size = 500
    if max(img_rgb.size) > analysis_size:
        ratio_resize = analysis_size / max(img_rgb.size)
        new_size = (int(w * ratio_resize), int(h * ratio_resize))
        gray_resized = gray.resize(new_size, Image.LANCZOS)
    else:
        gray_resized = gray

    # Laplacian filter → variance of result = blur metric
    laplacian = gray_resized.filter(ImageFilter.Kernel(
        size=(3, 3),
        kernel=[-1, -1, -1, -1, 8, -1, -1, -1, -1],
        scale=1,
        offset=128,
    ))
    lap_stat = ImageStat.Stat(laplacian)
    result.blur_score = lap_stat.var[0]

    if result.blur_score < MIN_BLUR_VARIANCE:
        result.issues.append("blurry")
        result.tips.append("Фото размытое — держи телефон ровно и подожди фокусировку.")

    # ── Prepare corrected image for Vision (if brightness was fixed) ──
    if corrected_img is not None:
        buf = BytesIO()
        corrected_img.save(buf, format="JPEG", quality=85)
        result.corrected_bytes = buf.getvalue()

    return result


def preprocess_for_vision(photo_bytes: bytes) -> tuple[bytes, PhotoQuality]:
    """Assess quality and optionally enhance photo before Vision.

    Returns:
        (photo_bytes_for_vision, quality_result)

    If photo is too dark, returns brightness-corrected version.
    If photo is fine, returns original.
    """
    quality = assess_photo(photo_bytes)

    if quality.corrected_bytes:
        return quality.corrected_bytes, quality

    return photo_bytes, quality
