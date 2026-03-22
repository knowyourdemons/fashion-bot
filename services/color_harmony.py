"""
Color harmony system for outfit scoring.

Maps Russian color names → HSL values, then scores color combinations
using established color theory (monochrome, analogous, complementary).
"""

# ── HSL color map ────────────────────────────────────────────────────────────
# (hue 0-360, saturation 0-100, lightness 0-100)

COLOR_HSL: dict[str, tuple[int, int, int]] = {
    # Reds
    "красный": (0, 80, 50), "алый": (5, 85, 50), "бордовый": (345, 70, 30),
    "малиновый": (340, 75, 45), "рубиновый": (350, 80, 40), "вишнёвый": (340, 65, 35),
    # Pinks
    "розовый": (330, 70, 70), "пудровый": (340, 30, 80), "пыльно-розовый": (340, 25, 70),
    "коралловый": (16, 75, 60), "лососевый": (17, 70, 65), "фуксия": (320, 80, 50),
    "нежно-розовый": (330, 40, 85), "ярко-розовый": (330, 90, 55),
    "дымчато-розовый": (340, 20, 65), "пыльная роза": (340, 25, 65),
    # Oranges
    "оранжевый": (30, 85, 55), "персиковый": (30, 60, 75), "абрикосовый": (25, 70, 70),
    "мандариновый": (25, 85, 55), "рыжий": (25, 70, 50), "терракотовый": (15, 55, 45),
    # Yellows
    "жёлтый": (55, 85, 55), "золотистый": (45, 70, 55), "горчичный": (45, 65, 45),
    "лимонный": (55, 85, 70), "ярко-жёлтый": (55, 90, 55),
    # Greens
    "зелёный": (120, 60, 40), "светло-зелёный": (120, 50, 65), "оливковый": (80, 40, 40),
    "хаки": (80, 30, 45), "мятный": (155, 50, 70), "изумрудный": (145, 65, 35),
    "тёмно-зелёный": (130, 50, 25), "тёмно-оливковый": (80, 35, 30),
    "пыльно-оливковый": (80, 25, 45), "ярко-зелёный": (120, 80, 45),
    # Blues
    "голубой": (200, 65, 70), "нежно-голубой": (200, 50, 80), "серо-голубой": (210, 25, 60),
    "синий": (220, 70, 45), "тёмно-синий": (220, 70, 30), "ярко-синий": (220, 90, 55),
    "navy": (220, 70, 25), "электрик": (220, 95, 50), "приглушённо-синий": (220, 35, 50),
    "приглушённо-голубой": (200, 30, 60), "индиго": (240, 60, 35), "деним": (215, 50, 45),
    "сине-серый": (215, 20, 50),
    # Teals
    "бирюзовый": (175, 60, 50), "тёмная бирюза": (175, 50, 35),
    "тёмно-бирюзовый": (175, 50, 35), "дымчато-бирюзовый": (175, 25, 55),
    # Purples
    "фиолетовый": (270, 60, 45), "сиреневый": (280, 40, 65), "лавандовый": (270, 40, 70),
    "серо-лавандовый": (270, 20, 65), "тёмно-фиолетовый": (270, 60, 30),
    # Browns
    "коричневый": (25, 50, 35), "шоколадный": (20, 55, 25), "тёмно-коричневый": (20, 50, 20),
    "светло-коричневый": (25, 45, 55), "бронзовый": (35, 50, 40),
    "тёмная бронза": (35, 45, 30), "мягкая бронза": (35, 35, 50),
    "верблюжий": (30, 40, 55), "кофейный": (20, 45, 30),
    # Beiges/Neutrals
    "бежевый": (35, 30, 75), "кремовый": (40, 35, 85), "слоновая кость": (40, 40, 90),
    "молочный": (40, 20, 90), "тауп": (30, 15, 55), "тёплый тауп": (30, 20, 55),
    "светло-бежевый": (35, 25, 85), "телесный": (30, 25, 75),
    "тёплая бежевая": (35, 30, 70), "тёплый серый": (30, 10, 55),
    # Blacks/Whites/Grays
    "белый": (0, 0, 100), "чёрный": (0, 0, 5), "серый": (0, 0, 50),
    "светло-серый": (0, 0, 75), "тёмно-серый": (0, 0, 30), "графит": (0, 0, 25),
    "серебристый": (0, 5, 75), "серебристо-серый": (0, 5, 70),
    "стальной": (210, 5, 45), "дымчатый": (0, 5, 55),
    # Reds (continued)
    "ржавый": (15, 60, 40), "тёмный терракот": (15, 50, 35),
    "приглушённый терракот": (15, 35, 45), "пыльный коралл": (16, 40, 60),
    # Misc
    "ярко-красный": (0, 90, 50), "тёплый розовый": (340, 60, 65),
    "нейтральный": (0, 0, 60),
}

# Colors that are "neutral" — combine with anything
NEUTRAL_HUES = frozenset([
    "белый", "чёрный", "серый", "светло-серый", "тёмно-серый", "графит",
    "бежевый", "кремовый", "молочный", "слоновая кость", "тауп",
    "тёплый тауп", "светло-бежевый", "тёплый серый", "серебристый",
    "серебристо-серый", "телесный", "нейтральный", "дымчатый",
    "navy", "тёмно-синий",  # navy is universally neutral in fashion
])


def _find_color_hsl(color_str: str) -> tuple[int, int, int] | None:
    """Find HSL for a color string (exact match or substring)."""
    if not color_str:
        return None
    c = color_str.lower().strip()
    # Exact match
    if c in COLOR_HSL:
        return COLOR_HSL[c]
    # Substring match
    for name, hsl in COLOR_HSL.items():
        if name in c or c in name:
            return hsl
    return None


def is_neutral(color_str: str) -> bool:
    """Check if a color is neutral (combines with anything)."""
    if not color_str:
        return True
    c = color_str.lower().strip()
    return any(n in c for n in NEUTRAL_HUES)


def _hue_distance(h1: int, h2: int) -> int:
    """Angular distance between two hues on the color wheel (0-180)."""
    d = abs(h1 - h2)
    return min(d, 360 - d)


def color_compatibility(color_a: str, color_b: str) -> float:
    """Score compatibility between two colors (-2 to +2).

    Scoring:
      +2: neutral + anything, or monochrome (same hue, diff lightness)
      +1: analogous (hues within 30°) or complementary (hues ~180°)
       0: triadic (~120°) or unknown colors
      -1: mild clash (hues 45-90° apart, similar saturation)
      -2: strong clash (two bright chromatic colors too close)
    """
    # Neutral colors combine with everything
    if is_neutral(color_a) or is_neutral(color_b):
        return 2.0

    hsl_a = _find_color_hsl(color_a)
    hsl_b = _find_color_hsl(color_b)

    # Unknown colors — assume OK
    if hsl_a is None or hsl_b is None:
        return 0.0

    h_a, s_a, l_a = hsl_a
    h_b, s_b, l_b = hsl_b

    # Low saturation = effectively neutral
    if s_a < 15 or s_b < 15:
        return 2.0

    hue_dist = _hue_distance(h_a, h_b)
    lightness_diff = abs(l_a - l_b)

    # Monochrome: same hue, different lightness
    if hue_dist <= 15 and lightness_diff >= 15:
        return 2.0

    # Analogous: hues within 60° (fashion standard — green+teal, blue+purple)
    if hue_dist <= 60:
        return 1.0

    # Complementary: hues ~180° apart
    if 150 <= hue_dist <= 180:
        return 1.0

    # Triadic: hues ~120° apart
    if 100 <= hue_dist <= 140:
        return 0.5

    # Split-complementary: ~150°
    if 140 <= hue_dist <= 160:
        return 0.5

    # Potential clash: 70-100° apart with both saturated
    if 70 <= hue_dist <= 100 and s_a >= 50 and s_b >= 50:
        return -1.0

    # Everything else — not great, not terrible
    return 0.0


def score_outfit_colors(items: list) -> float:
    """Score overall color harmony of an outfit.

    Args:
        items: list of objects with .color attribute

    Returns:
        Score from 0 to 10 (10 = perfect harmony)
    """
    colors = [getattr(i, "color", "") or "" for i in items if getattr(i, "color", "")]
    if len(colors) < 2:
        return 7.0  # single item = OK by default

    # Count non-neutral colors
    chromatic = [c for c in colors if not is_neutral(c)]

    # Too many chromatic colors = penalty (rule of 3)
    if len(chromatic) > 3:
        color_penalty = (len(chromatic) - 3) * 1.5
    else:
        color_penalty = 0

    # Pairwise compatibility
    total_compat = 0.0
    pair_count = 0
    for i in range(len(colors)):
        for j in range(i + 1, len(colors)):
            total_compat += color_compatibility(colors[i], colors[j])
            pair_count += 1

    if pair_count == 0:
        return 7.0

    avg_compat = total_compat / pair_count  # Range: -2 to +2

    # Map -2..+2 → 0..10
    base_score = (avg_compat + 2) * 2.5  # 0..10
    final = max(0, min(10, base_score - color_penalty))

    return round(final, 1)
