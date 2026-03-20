"""Generate minimal weather PNG icons (48x48, RGBA)."""
import os
from PIL import Image, ImageDraw

SIZE = 48
OUT = os.path.dirname(__file__)


def _sun():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, cy = SIZE // 2, SIZE // 2
    # Circle
    r = 14
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 200, 50, 255))
    # Rays
    for angle in range(0, 360, 45):
        import math
        rad = math.radians(angle)
        x1 = cx + int(17 * math.cos(rad))
        y1 = cy + int(17 * math.sin(rad))
        x2 = cx + int(22 * math.cos(rad))
        y2 = cy + int(22 * math.sin(rad))
        d.line([(x1, y1), (x2, y2)], fill=(255, 200, 50, 200), width=2)
    return img


def _cloud():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Main cloud body
    d.ellipse([8, 16, 30, 38], fill=(200, 210, 220, 255))
    d.ellipse([18, 10, 40, 36], fill=(210, 218, 228, 255))
    d.ellipse([4, 22, 24, 42], fill=(195, 205, 218, 255))
    d.ellipse([22, 20, 44, 42], fill=(205, 215, 225, 255))
    return img


def _partly_cloudy():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Small sun top-left
    d.ellipse([4, 4, 22, 22], fill=(255, 200, 50, 255))
    for angle in range(0, 360, 60):
        import math
        rad = math.radians(angle)
        cx, cy = 13, 13
        x1 = cx + int(12 * math.cos(rad))
        y1 = cy + int(12 * math.sin(rad))
        x2 = cx + int(15 * math.cos(rad))
        y2 = cy + int(15 * math.sin(rad))
        d.line([(x1, y1), (x2, y2)], fill=(255, 200, 50, 180), width=2)
    # Cloud foreground
    d.ellipse([12, 20, 32, 40], fill=(210, 218, 228, 255))
    d.ellipse([22, 14, 42, 38], fill=(200, 210, 222, 255))
    d.ellipse([8, 26, 26, 44], fill=(205, 215, 225, 255))
    d.ellipse([26, 24, 44, 44], fill=(210, 218, 228, 255))
    return img


def _rain():
    img = _cloud()
    d = ImageDraw.Draw(img)
    # Rain drops
    for x in [14, 24, 34]:
        d.line([(x, 40), (x - 3, 46)], fill=(100, 150, 220, 200), width=2)
    return img


def _snow():
    img = _cloud()
    d = ImageDraw.Draw(img)
    # Snowflakes
    for x in [12, 24, 36]:
        d.ellipse([x - 2, 40, x + 2, 44], fill=(180, 200, 230, 220))
    return img


def _thunder():
    img = _cloud()
    d = ImageDraw.Draw(img)
    # Lightning bolt
    d.polygon([(22, 36), (26, 36), (23, 42), (28, 42), (20, 48), (24, 42), (20, 42)],
              fill=(255, 220, 50, 255))
    return img


def _fog():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for y in [14, 22, 30, 38]:
        d.line([(6, y), (42, y)], fill=(190, 200, 210, 180), width=3)
    return img


def _drizzle():
    """Light rain — fewer, thinner drops."""
    img = _cloud()
    d = ImageDraw.Draw(img)
    for x in [16, 28]:
        d.line([(x, 40), (x - 2, 44)], fill=(130, 170, 220, 160), width=1)
    return img


def _sleet():
    """Mix rain + snow."""
    img = _cloud()
    d = ImageDraw.Draw(img)
    d.line([(14, 40), (11, 46)], fill=(100, 150, 220, 200), width=2)
    d.ellipse([22, 40, 26, 44], fill=(180, 200, 230, 220))
    d.line([(34, 40), (31, 46)], fill=(100, 150, 220, 200), width=2)
    return img


if __name__ == "__main__":
    icons = {
        "sun": _sun(),
        "partly_cloudy": _partly_cloudy(),
        "cloud": _cloud(),
        "rain": _rain(),
        "drizzle": _drizzle(),
        "snow": _snow(),
        "sleet": _sleet(),
        "thunder": _thunder(),
        "fog": _fog(),
    }
    for name, img in icons.items():
        path = os.path.join(OUT, f"{name}.png")
        img.save(path, "PNG")
        print(f"Saved {path} ({img.size})")
