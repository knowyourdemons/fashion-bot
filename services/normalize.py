"""
Normalization layer for Vision output.

Maps unusual/rare clothing types and colors to canonical forms
that the outfit selector understands. Works as a fallback chain:
1. Exact match in synonym map
2. Substring match in synonym map
3. Return original (no normalization)

No AI calls needed — pure dictionary lookup.
"""

# ══════════════════════════════════════════════════════════════════════════════
# TYPE SYNONYMS → canonical type
# ══════════════════════════════════════════════════════════════════════════════
# Format: "synonym" → ("canonical_type", "canonical_category_group")
# Vision may return any of these; we normalize to what _select_outfit() knows.

TYPE_SYNONYMS: dict[str, tuple[str, str]] = {
    # ── HEADWEAR → accessory ──
    "капор": ("шапка", "accessory"),
    "капюшон": ("шапка", "accessory"),
    "балаклава": ("шапка", "accessory"),
    "тюбетейка": ("шапка", "accessory"),
    "берет": ("шапка", "accessory"),
    "бини": ("шапка", "accessory"),
    "beanie": ("шапка", "accessory"),
    "ушанка": ("шапка", "accessory"),
    "бейсболка": ("шапка", "accessory"),
    "кепка": ("шапка", "accessory"),
    "панама": ("шапка", "accessory"),
    "бандана": ("шапка", "accessory"),
    "повязка на голову": ("шапка", "accessory"),
    "чепчик": ("шапка", "accessory"),
    "косынка": ("шапка", "accessory"),
    "тюрбан": ("шапка", "accessory"),

    # ── FOOTWEAR variants ──
    "валенки": ("зимние сапоги", "footwear"),
    "дутики": ("зимние сапоги", "footwear"),
    "луноходы": ("зимние сапоги", "footwear"),
    "moon boots": ("зимние сапоги", "footwear"),
    "резиновые сапоги": ("сапоги", "footwear"),
    "кеды": ("кроссовки", "footwear"),
    "слипоны": ("кроссовки", "footwear"),
    "мокасины": ("туфли", "footwear"),
    "балетки": ("туфли", "footwear"),
    "шлёпки": ("сандалии", "footwear"),
    "шлёпанцы": ("сандалии", "footwear"),
    "вьетнамки": ("сандалии", "footwear"),
    "crocs": ("сандалии", "footwear"),
    "кроксы": ("сандалии", "footwear"),
    "чешки": ("тапочки", "footwear"),
    "пинетки": ("тапочки", "footwear"),
    "сникерсы": ("кроссовки", "footwear"),
    "sneakers": ("кроссовки", "footwear"),
    "ботильоны": ("ботинки", "footwear"),
    "челси": ("ботинки", "footwear"),
    "тимберленды": ("ботинки", "footwear"),
    "timberland": ("ботинки", "footwear"),

    # ── TOP variants ──
    "олимпийка": ("худи", "top"),
    "толстовка": ("худи", "top"),
    "свитшот": ("худи", "top"),
    "поло": ("рубашка", "top"),
    "тельняшка": ("лонгслив", "top"),
    "джемпер": ("свитер", "top"),
    "пуловер": ("свитер", "top"),
    "гольф": ("водолазка", "top"),
    "бадлон": ("водолазка", "top"),
    "жилетка": ("кардиган", "top"),
    "безрукавка": ("кардиган", "top"),
    "майка": ("футболка", "top"),
    "tank top": ("футболка", "top"),
    "корсет": ("топ", "top"),
    "туника": ("блузка", "top"),
    "батник": ("рубашка", "top"),
    "фланелька": ("рубашка", "top"),

    # ── BOTTOM variants ──
    "бриджи": ("шорты", "bottom"),
    "капри": ("брюки", "bottom"),
    "кюлоты": ("брюки", "bottom"),
    "лосины": ("леггинсы", "bottom"),
    "треники": ("брюки", "bottom"),
    "спортивные штаны": ("брюки", "bottom"),
    "joggers": ("брюки", "bottom"),
    "карго": ("брюки", "bottom"),
    "чиносы": ("брюки", "bottom"),
    "палаццо": ("брюки", "bottom"),

    # ── OUTERWEAR variants ──
    "парка": ("куртка", "outerwear"),
    "анорак": ("куртка", "outerwear"),
    "плащ": ("тренч", "outerwear"),
    "дождевик": ("ветровка", "outerwear"),
    "кожанка": ("кожаная куртка", "outerwear"),
    "косуха": ("кожаная куртка", "outerwear"),
    "шуба": ("пальто", "outerwear"),
    "дублёнка": ("пальто", "outerwear"),
    "пончо": ("пальто", "outerwear"),
    "накидка": ("пальто", "outerwear"),
    "кейп": ("пальто", "outerwear"),
    "blazer": ("пиджак", "outerwear"),
    "пиджак": ("пиджак", "outerwear"),
    "жакет": ("пиджак", "outerwear"),

    # ── ONE PIECE variants ──
    "сарафан": ("платье", "one_piece"),
    "ромпер": ("комбинезон", "one_piece"),
    "слип": ("комбинезон", "one_piece"),
    "песочник": ("комбинезон", "one_piece"),
    "полукомбинезон": ("комбинезон", "one_piece"),
    "jumpsuit": ("комбинезон", "one_piece"),
    "overalls": ("комбинезон", "one_piece"),

    # ── BASE LAYER / UNDERWEAR variants ──
    "рейтузы": ("колготки", "base_layer"),
    "подштанники": ("термо штаны", "underwear"),
    "кальсоны": ("термо штаны", "underwear"),
    "гетры": ("носки", "base_layer"),
    "следки": ("носки", "base_layer"),
    "подследники": ("носки", "base_layer"),

    # ── ACCESSORY variants ──
    "муфта": ("перчатки", "accessory"),
    "снуд": ("шарф", "accessory"),
    "манишка": ("шарф", "accessory"),
    "палантин": ("шарф", "accessory"),
    "платок": ("шарф", "accessory"),
    "рюкзак": ("сумка", "accessory"),
    "клатч": ("сумка", "accessory"),
    "поясная сумка": ("сумка", "accessory"),
    "fanny pack": ("сумка", "accessory"),
    "часы": ("украшения", "accessory"),
    "брошь": ("украшения", "accessory"),
    "ободок": ("украшения", "accessory"),
    "заколка": ("украшения", "accessory"),
}

# Pre-sorted by key length descending for substring matching
# (longer matches first to avoid partial matches like "бал" matching "балетки")
_TYPE_SYNONYMS_SORTED = sorted(TYPE_SYNONYMS.items(), key=lambda x: len(x[0]), reverse=True)


def normalize_type(raw_type: str, raw_category_group: str = "") -> tuple[str, str]:
    """Normalize a clothing type to canonical form.

    Args:
        raw_type: Vision-returned type (lowercase)
        raw_category_group: Vision-returned category_group

    Returns:
        (normalized_type, normalized_category_group)
        If no synonym found, returns originals unchanged.
    """
    if not raw_type:
        return raw_type, raw_category_group

    t = raw_type.lower().strip()

    # 1. Exact match
    if t in TYPE_SYNONYMS:
        canonical_type, canonical_cg = TYPE_SYNONYMS[t]
        return canonical_type, canonical_cg

    # 2. Substring match (longer keys first)
    for synonym, (canonical_type, canonical_cg) in _TYPE_SYNONYMS_SORTED:
        if synonym in t:
            return canonical_type, canonical_cg

    # 3. No match — return original
    return raw_type, raw_category_group or "top"


# ══════════════════════════════════════════════════════════════════════════════
# COLOR SYNONYMS → canonical color
# ══════════════════════════════════════════════════════════════════════════════

COLOR_SYNONYMS: dict[str, str] = {
    # Complex/rare colors → simple canonical
    "цвет морской волны": "бирюзовый",
    "морская волна": "бирюзовый",
    "аквамарин": "бирюзовый",
    "тиффани": "бирюзовый",
    "циан": "бирюзовый",

    "маренго": "тёмно-серый",
    "антрацит": "тёмно-серый",
    "мокрый асфальт": "тёмно-серый",
    "асфальт": "серый",
    "дымка": "серый",
    "пепельный": "серый",
    "стальной": "серый",
    "свинцовый": "тёмно-серый",

    "экрю": "кремовый",
    "шампань": "кремовый",
    "ваниль": "кремовый",
    "айвори": "слоновая кость",
    "ivory": "слоновая кость",
    "off-white": "молочный",

    "фисташковый": "светло-зелёный",
    "салатовый": "светло-зелёный",
    "лайм": "светло-зелёный",
    "малахитовый": "изумрудный",
    "нефритовый": "изумрудный",
    "сосновый": "тёмно-зелёный",
    "болотный": "хаки",
    "камуфляж": "хаки",
    "милитари": "хаки",

    "пудра": "пудровый",
    "пудровый розовый": "пудровый",
    "сухая роза": "пыльно-розовый",
    "увядшая роза": "пыльно-розовый",
    "чайная роза": "персиковый",
    "пепел розы": "пыльно-розовый",
    "blush": "пудровый",

    "индиго": "тёмно-синий",
    "васильковый": "голубой",
    "кобальт": "синий",
    "сапфировый": "синий",
    "ультрамарин": "синий",
    "лазурный": "голубой",
    "небесный": "голубой",
    "джинсовый": "голубой",
    "деним": "голубой",

    "марсала": "бордовый",
    "бургунди": "бордовый",
    "burgundy": "бордовый",
    "винный": "бордовый",
    "вишня": "бордовый",
    "гранатовый": "бордовый",
    "клюквенный": "бордовый",
    "брусничный": "бордовый",

    "пурпурный": "фиолетовый",
    "фиалковый": "фиолетовый",
    "аметистовый": "фиолетовый",
    "сливовый": "фиолетовый",
    "баклажановый": "фиолетовый",
    "ежевичный": "фиолетовый",

    "карамельный": "бежевый",
    "капучино": "бежевый",
    "песочный": "бежевый",
    "льняной": "бежевый",
    "нюд": "бежевый",
    "nude": "бежевый",
    "загар": "бежевый",

    "медный": "рыжий",
    "ржавчина": "ржавый",
    "кирпичный": "терракотовый",
    "глиняный": "терракотовый",
    "охра": "горчичный",
    "янтарный": "золотистый",
    "медовый": "золотистый",
    "пшеничный": "золотистый",

    "какао": "коричневый",
    "каштановый": "коричневый",
    "мокко": "коричневый",
    "табачный": "коричневый",
    "коньячный": "коричневый",
    "ореховый": "коричневый",
    "сепия": "коричневый",

    "алый": "красный",
    "рубин": "красный",
    "вишнёвый": "красный",
    "томатный": "красный",
    "клубничный": "красный",

    "лимонный": "жёлтый",
    "канареечный": "жёлтый",
    "шафрановый": "жёлтый",
    "кукурузный": "жёлтый",

    # English colors
    "white": "белый",
    "black": "чёрный",
    "gray": "серый", "grey": "серый",
    "red": "красный",
    "blue": "синий",
    "green": "зелёный",
    "yellow": "жёлтый",
    "pink": "розовый",
    "orange": "оранжевый",
    "purple": "фиолетовый",
    "brown": "коричневый",
    "beige": "бежевый",
    "navy": "тёмно-синий",
    "khaki": "хаки",
    "coral": "коралловый",
    "mint": "мятный",
    "lavender": "лавандовый",
    "burgundy": "бордовый",
    "teal": "бирюзовый",
    "cream": "кремовый",
    "gold": "золотистый",
    "silver": "серебристый",
    "olive": "оливковый",
    "peach": "персиковый",
    "mustard": "горчичный",
    "terracotta": "терракотовый",
    "charcoal": "графит",
    "ivory": "слоновая кость",

    # Multi-word
    "dark blue": "тёмно-синий",
    "light blue": "голубой",
    "dark green": "тёмно-зелёный",
    "light green": "светло-зелёный",
    "dark grey": "тёмно-серый",
    "light grey": "светло-серый",
    "hot pink": "фуксия",
    "dusty pink": "пыльно-розовый",
    "dusty rose": "пыльно-розовый",
    "baby blue": "нежно-голубой",

    # With accents / typos
    "серо-голубой": "серо-голубой",
    "серо-зеленый": "хаки",
    "темно-синий": "тёмно-синий",
    "темно-зеленый": "тёмно-зелёный",
    "светло-серый": "светло-серый",
}

_COLOR_SYNONYMS_SORTED = sorted(COLOR_SYNONYMS.items(), key=lambda x: len(x[0]), reverse=True)


def normalize_color(raw_color: str) -> str:
    """Normalize a color name to canonical form.

    Args:
        raw_color: Vision-returned color (any case)

    Returns:
        Canonical color name (lowercase).
        If no synonym found, returns lowercase original.
    """
    if not raw_color:
        return raw_color

    c = raw_color.lower().strip()

    # 1. Exact match
    if c in COLOR_SYNONYMS:
        return COLOR_SYNONYMS[c]

    # 2. Substring match (longer keys first)
    for synonym, canonical in _COLOR_SYNONYMS_SORTED:
        if synonym in c:
            return canonical

    # 3. No match — return lowercase original
    return c
