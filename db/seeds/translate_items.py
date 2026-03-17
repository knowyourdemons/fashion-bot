"""
Переводит английские названия вещей гардероба на русский язык.
Применяется к wardrobe_items где score_version != 'v2.0'.
Запускается автоматически при старте если есть вещи с английскими названиями.
"""
import asyncio
import re

import structlog

logger = structlog.get_logger()

TRANSLATIONS: dict[str, str] = {
    # types
    "pants": "штаны",
    "leggings": "леггинсы",
    "shorts": "шорты",
    "dress": "платье",
    "skirt": "юбка",
    "shirt": "рубашка",
    "t-shirt": "футболка",
    "cardigan": "кардиган",
    "sweater": "свитер",
    "jacket": "куртка",
    "coat": "пальто",
    "boots": "сапоги",
    "sneakers": "кроссовки",
    "sandals": "сандалии",
    "socks": "носки",
    "tights": "колготки",
    "bodysuit": "боди",
    "jumpsuit": "комбинезон",
    "hoodie": "худи",
    "blouse": "блузка",
    "pajama set": "пижама",
    "quilted jacket": "стёганая куртка",
    "balaclava": "балаклава",
    "scarf": "шарф",
    "hat": "шапка",
    "gloves": "перчатки",
    "underwear": "трусики",
    "undershirt": "майка",
    "thermal top": "термо верх",
    "thermal bottom": "термо низ",
    # compound colors (must be before single-word colors)
    "cream/beige": "кремово-бежевый",
    "yellow/cream": "жёлто-кремовый",
    "beige/cream": "бежево-кремовый",
    "charcoal gray": "тёмно-серый",
    "beige with black polka dots": "бежевый в чёрный горошек",
    "turquoise and white": "бирюзово-белый",
    "cream with pink bows": "кремовый с розовыми бантами",
    "red and white": "красно-белый",
    # colors
    "pink": "розовый",
    "white": "белый",
    "black": "чёрный",
    "beige": "бежевый",
    "grey": "серый",
    "gray": "серый",
    "blue": "голубой",
    "red": "красный",
    "green": "зелёный",
    "lavender": "лавандовый",
    "cream": "кремовый",
    "mint": "мятный",
    "charcoal": "тёмно-серый",
    "burgundy": "бордовый",
    "navy": "тёмно-синий",
    "turquoise": "бирюзовый",
    "mauve": "сиреневый",
    "sage": "шалфейный",
    "orange": "оранжевый",
    "yellow": "жёлтый",
    "purple": "фиолетовый",
    "brown": "коричневый",
    "dark brown": "тёмно-коричневый",
}

# Sorted by length descending so multi-word keys match before single words
_SORTED_TYPE_KEYS = sorted(TRANSLATIONS.keys(), key=len, reverse=True)

# Compound color phrases matched against the whole color string before splitting
_COMPOUND_COLOR_KEYS = {
    k: v for k, v in TRANSLATIONS.items()
    if k in {
        "cream/beige", "yellow/cream", "beige/cream", "charcoal gray",
        "beige with black polka dots", "turquoise and white",
        "cream with pink bows", "red and white", "dark brown",
    }
}
_SORTED_COMPOUND_COLOR_KEYS = sorted(_COMPOUND_COLOR_KEYS.keys(), key=len, reverse=True)

# Single-word color keys
_COLOR_KEYS = {
    k: v for k, v in TRANSLATIONS.items()
    if k in {
        "pink", "white", "black", "beige", "grey", "gray", "blue", "red",
        "green", "lavender", "cream", "mint", "charcoal", "burgundy", "navy",
        "turquoise", "mauve", "sage", "orange", "yellow", "purple", "brown",
    }
}
_SORTED_COLOR_KEYS = sorted(_COLOR_KEYS.keys(), key=len, reverse=True)

_EN_WORD_RE = re.compile(r"[a-zA-Z]")


def _is_english(text: str) -> bool:
    return bool(_EN_WORD_RE.search(text or ""))


def _translate_type(value: str) -> str:
    low = value.lower().strip()
    for key in _SORTED_TYPE_KEYS:
        if low == key:
            return TRANSLATIONS[key]
    return value


def _translate_color(value: str) -> str:
    """Translate color string: compound phrases first, then comma-separated words."""
    low_full = value.lower().strip()
    for key in _SORTED_COMPOUND_COLOR_KEYS:
        if low_full == key:
            return _COMPOUND_COLOR_KEYS[key]

    parts = [p.strip() for p in value.split(",")]
    result = []
    for part in parts:
        low = part.lower()
        translated = part
        for key in _SORTED_COLOR_KEYS:
            if low == key:
                translated = _COLOR_KEYS[key]
                break
        result.append(translated)
    return ", ".join(result)


async def translate_items() -> int:
    """Переводит все вещи с английскими названиями. Возвращает кол-во обновлённых."""
    from sqlalchemy import select, update
    from db.base import AsyncReadSession, AsyncWriteSession
    from db.models.wardrobe import WardrobeItem

    async with AsyncReadSession() as session:
        result = await session.execute(
            select(WardrobeItem).where(
                WardrobeItem.score_version != "v2.0",
                WardrobeItem.deleted_at.is_(None),
            )
        )
        items = list(result.scalars().all())

    to_update = [(i.id, i.type, i.color) for i in items if _is_english(i.type) or _is_english(i.color)]

    if not to_update:
        return 0

    updated = 0
    async with AsyncWriteSession() as session:
        for item_id, item_type, item_color in to_update:
            new_type = _translate_type(item_type) if _is_english(item_type) else item_type
            new_color = _translate_color(item_color) if _is_english(item_color) else item_color
            if new_type != item_type or new_color != item_color:
                await session.execute(
                    update(WardrobeItem)
                    .where(WardrobeItem.id == item_id)
                    .values(type=new_type, color=new_color)
                )
                updated += 1
        await session.commit()

    logger.info("translate_items.done", updated=updated, checked=len(to_update))
    return updated


async def run_if_needed() -> None:
    """Запускает перевод только если есть вещи с английскими названиями."""
    try:
        count = await translate_items()
        if count:
            logger.info("translate_items.applied", count=count)
    except Exception as e:
        logger.warning("translate_items.failed", error=str(e))


if __name__ == "__main__":
    asyncio.run(translate_items())
