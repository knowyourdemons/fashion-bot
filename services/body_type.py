"""Body type styling rules for AI prompt injection.

5 types: hourglass, pear, apple, rectangle, inverted_triangle.
Rules: clothing, footwear, bags — what works and what to avoid.
Tone: recommendations, not prohibitions ("лучше смотрится" not "избегай").
"""

BODY_TYPE_RULES: dict[str, str] = {
    "hourglass": (
        "Тип фигуры: песочные часы.\n"
        "Принцип: подчёркивать талию.\n"
        "Верх: V-neck, wrap, fitted — отлично. Boxy oversized скроет талию.\n"
        "Низ: high-waist, юбка-карандаш, bootcut подчёркивают фигуру.\n"
        "Платья: wrap dress, fit-and-flare — идеально.\n"
        "Верхнее: пальто с поясом, fitted блейзер.\n"
        "Обувь: каблук подчёркивает S-линию, но и без каблука отлично.\n"
        "Сумка: crossbody на уровне талии, structured shoulder."
    ),
    "pear": (
        "Тип фигуры: груша (бёдра шире плеч).\n"
        "Принцип: акцент ВВЕРХ — объём и яркие цвета на плечах.\n"
        "Верх: boat neck, off-shoulder, объёмные рукава, яркие цвета сверху.\n"
        "Низ: A-line, wide-leg от бедра, straight, тёмные цвета.\n"
        "Платья: A-line, empire waist лучше всего.\n"
        "Верхнее: structured blazer, cropped jacket.\n"
        "Обувь: nude обувь удлиняет ноги. Лучше без ankle strap.\n"
        "Сумка: на уровне талии или выше — отвлекает от бёдер."
    ),
    "apple": (
        "Тип фигуры: яблоко (широкая середина).\n"
        "Принцип: создать вертикаль, не подчёркивать середину.\n"
        "Верх: V-neck удлиняет торс. Empire line, туника, длина ниже бедра.\n"
        "Низ: high-waist straight, bootcut, wide-leg.\n"
        "Платья: A-line, empire, wrap dress.\n"
        "Верхнее: длинный кардиган, open blazer создают вертикаль.\n"
        "Обувь: острый носок удлиняет. Небольшой каблук балансирует.\n"
        "Сумка: длинная crossbody ниже талии или на плече — не на уровне живота."
    ),
    "rectangle": (
        "Тип фигуры: прямоугольник (плечи ≈ бёдра ≈ талия).\n"
        "Принцип: создать изгибы — пояс, peplum, оборки.\n"
        "Верх: peplum, ruched, off-shoulder добавляют форму.\n"
        "Низ: paper bag waist, юбка с оборками, pleated.\n"
        "Платья: fit-and-flare, belted dress, wrap.\n"
        "Верхнее: тренч с поясом, peplum жакет.\n"
        "Обувь: каблук создаёт S-кривую. Ремешки добавляют детали.\n"
        "Сумка: округлые формы (hobo, rounded crossbody) добавляют кривые."
    ),
    "inverted_triangle": (
        "Тип фигуры: перевёрнутый треугольник (плечи шире бёдер).\n"
        "Принцип: убрать объём сверху, добавить снизу.\n"
        "Верх: V-neck, scoop neck, raglan, тёмные цвета сверху.\n"
        "Низ: wide-leg, A-line юбка, pleated, яркий/светлый низ.\n"
        "Платья: A-line, fit-and-flare.\n"
        "Верхнее: прямое пальто. Подплечники не нужны.\n"
        "Обувь: объёмная обувь (сапоги, платформы) балансирует плечи.\n"
        "Сумка: tote на бедре добавляет объём снизу."
    ),
}


def get_body_type_prompt(body_type: str | None) -> str:
    """Get body type rules for AI prompt. Empty string if no body_type."""
    if not body_type:
        return ""
    rules = BODY_TYPE_RULES.get(body_type)
    if not rules:
        return ""
    return f"\n\n{rules}"


# ══════════════════════════════════════════════════════════════════════════════
# Professional styling context builder
# ══════════════════════════════════════════════════════════════════════════════

CONTRAST_RULES = {
    "HIGH": "Контрастные сочетания: тёмное + светлое, navy + белый. Монохром нежных тонов может 'потушить' яркую внешность.",
    "MEDIUM": "Сбалансированные сочетания: и контраст и тональные.",
    "LOW": "Тональные нежные переходы. Монохром — отлично. Резкие контрасты могут подавлять.",
}

KIBBE_RULES = {
    "DRAMATIC": "Чистые линии, structured ткани, минимум деталей, сильная вертикаль. НЕ: рюши, мелкие принты.",
    "NATURAL": "Relaxed, текстурные ткани, layered. Linen, cotton, кожа. НЕ: слишком tight или formal.",
    "CLASSIC": "Balanced, symmetrical, quality mid-weight. Wool, silk, cashmere. НЕ: extreme oversized или extreme tight.",
    "GAMINE": "Compact, fitted, можно bold мелкие детали. Crisp ткани. НЕ: oversized flowing, слишком длинные линии.",
    "ROMANTIC": "Мягкие линии, подчёркивать талию. Flowing, soft, draping. НЕ: harsh structured, angular.",
}

ESSENCE_RULES = {
    "DRAMATIC": "Power dressing, statement pieces, bold.",
    "NATURAL": "Effortless, layered, earthy, relaxed elegance.",
    "CLASSIC": "Timeless, polished, quality > quantity.",
    "GAMINE": "Playful, unexpected combos, mix masculine + feminine.",
    "ROMANTIC": "Feminine, soft, detailed, waist emphasis.",
}


def build_full_styling_context(user) -> str:
    """Build complete professional styling context for AI prompt."""
    lines = []

    ct = getattr(user, "colortype", None)
    if ct:
        lines.append(f"Цветотип: {ct}")

    cl = getattr(user, "contrast_level", None)
    if cl and cl in CONTRAST_RULES:
        lines.append(f"Контраст: {cl}. {CONTRAST_RULES[cl]}")

    kf = getattr(user, "kibbe_family", None)
    if kf and kf in KIBBE_RULES:
        lines.append(f"Силуэт ({kf}): {KIBBE_RULES[kf]}")

    se = getattr(user, "style_essence", None)
    if se and se in ESSENCE_RULES:
        lines.append(f"Сущность ({se}): {ESSENCE_RULES[se]}")

    bt = getattr(user, "body_type", None)
    if bt:
        prompt = get_body_type_prompt(bt)
        if prompt:
            lines.append(prompt.strip())

    if not lines:
        return ""
    return "Стилистический профиль:\n" + "\n".join(lines)


KIBBE_FABRIC_COMPATIBILITY = {
    "DRAMATIC": {"best": ["structured", "leather", "crisp", "matte"], "avoid": ["chiffon", "lace", "jersey"]},
    "NATURAL": {"best": ["linen", "cotton", "leather", "knit"], "avoid": ["shiny", "stiff"]},
    "CLASSIC": {"best": ["wool", "silk", "cashmere", "cotton"], "avoid": ["chunky_knit", "distressed"]},
    "GAMINE": {"best": ["crisp", "cotton", "denim", "structured"], "avoid": ["heavy_draping", "oversized"]},
    "ROMANTIC": {"best": ["silk", "chiffon", "jersey", "lace", "cashmere"], "avoid": ["stiff", "harsh"]},
}


def fabric_kibbe_score(fabric_hint: str, kibbe_family: str) -> float:
    """Score 0-1 for fabric-body compatibility."""
    if not fabric_hint or not kibbe_family:
        return 0.5
    compat = KIBBE_FABRIC_COMPATIBILITY.get(kibbe_family, {})
    f = fabric_hint.lower()
    for best in compat.get("best", []):
        if best in f:
            return 1.0
    for avoid in compat.get("avoid", []):
        if avoid in f:
            return 0.2
    return 0.5
