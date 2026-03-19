"""
Единый модуль сборки образа.

Используется и morning_brief.py и wardrobe.py — единая точка правды.
"""
from datetime import date

from services.outfit_selector import _select_outfit, _get_temp_regime
from services.brief_weather import _SEASONS

# ── Public API (реэкспорт с публичными именами) ───────────────────────────


def select_outfit(
    items: list,
    season: str,
    today: date,
    temp_morning: float | None = None,
    temp_evening: float | None = None,
    precip_evening: float = 0,
) -> dict:
    return _select_outfit(items, season, today, temp_morning, temp_evening, precip_evening)


def get_temp_regime(temp: float) -> str:
    return _get_temp_regime(temp)


SEASONS = _SEASONS


# ── Collage params ────────────────────────────────────────────────────────────

_DAY_NAMES = {0: "Пн", 1: "Вт", 2: "Ср", 3: "Чт", 4: "Пт", 5: "Сб", 6: "Вс"}
_MONTH_NAMES = {
    1: "янв", 2: "фев", 3: "мар", 4: "апр", 5: "мая", 6: "июн",
    7: "июл", 8: "авг", 9: "сен", 10: "окт", 11: "ноя", 12: "дек",
}


def _weather_emoji(temp: float | None, precip: float = 0) -> str:
    if precip and precip > 50:
        return "🌧"
    if temp is None:
        return "🌤"
    if temp > 25:
        return "☀️"
    if temp > 15:
        return "🌤"
    if temp > 5:
        return "🌥"
    if temp > 0:
        return "❄️"
    return "🥶"


def get_collage_params(
    child=None,
    user=None,
    temp: float | None = None,
    precip: float = 0,
    day_type: str = "",
) -> dict:
    """Возвращает theme, header_text, footer_text для build_collage."""
    today = date.today()

    # Theme
    if child and getattr(child, "gender", "girl") == "boy":
        theme = "boy"
    elif child:
        theme = "girl"
    else:
        theme = "adult"

    # Header
    emoji = _weather_emoji(temp, precip)
    sign = "+" if (temp or 0) >= 0 else ""
    temp_str = f"{sign}{temp:.0f}°C" if temp is not None else ""
    day_str = f"{_DAY_NAMES[today.weekday()]}, {today.day} {_MONTH_NAMES[today.month]}"

    if child:
        context = child.name
        if day_type:
            context += f", {day_type}"
        header = f"{emoji} {day_str} · {temp_str} · {context}"
    else:
        day_ctx = "выходной" if today.weekday() >= 5 else "будний день"
        header = f"{emoji} {day_str} · {temp_str} · {day_ctx}"

    return {
        "theme": theme,
        "header_text": header,
        "footer_text": "Касси · fashioncastle.app",
    }


# ── Outfit slots builder ──────────────────────────────────────────────────────

_SLOT_ORDER = [
    "outerwear", "top", "bottom", "one_piece",
    "footwear", "hat", "scarf", "gloves", "tights",
]


def build_outfit_slots(
    outfit: dict,
    child=None,
    user=None,
    temp: float | None = None,
) -> list[dict]:
    """Конвертирует outfit dict → outfit_slots для build_collage.

    Единая точка — и для morning_brief, и для wardrobe handler.
    Обувь показывается ВСЕГДА (ребёнок/взрослый не ходит босиком).
    Куртка — плейсхолдер при temp ≤ 10°C.
    """
    from worker.tasks.style_config import _needs_tights

    is_adult = child is None
    gender = getattr(child, "gender", "girl") if child else "girl"
    _temp = temp if temp is not None else 15.0

    has_one_piece = bool(outfit.get("one_piece"))
    has_top_bottom = bool(outfit.get("top") or outfit.get("bottom"))

    slots = []
    seen: set = set()

    for slot_key in _SLOT_ORDER:
        if slot_key in seen:
            continue

        # Пропустить конфликтующие слоты
        if slot_key in ("top", "bottom") and has_one_piece:
            continue
        if slot_key == "one_piece" and has_top_bottom:
            continue
        if slot_key == "tights" and not _needs_tights(outfit, _temp):
            continue

        item = outfit.get(slot_key)

        if item and getattr(item, "show_in_collage", True):
            seen.add(slot_key)
            slots.append({
                "slot": slot_key,
                "item_type": item.type,
                "photo_id": item.photo_id,
                "photo_url": getattr(item, "photo_url", None),
                "has_item": True,
                "adult": is_adult,
                "gender": gender,
            })
        else:
            # Нужен ли плейсхолдер?
            needs_placeholder = False
            if slot_key == "outerwear" and _temp <= 10:
                needs_placeholder = True
            elif slot_key == "footwear":
                needs_placeholder = True  # обувь нужна ВСЕГДА
            elif slot_key == "hat" and _temp < 10:
                needs_placeholder = True
            elif slot_key == "scarf" and _temp < 5:
                needs_placeholder = True
            elif slot_key == "gloves" and _temp < 0:
                needs_placeholder = True
            elif slot_key in ("top", "bottom") and not has_one_piece:
                needs_placeholder = True
            elif slot_key == "one_piece" and not has_top_bottom:
                needs_placeholder = True

            if needs_placeholder:
                seen.add(slot_key)
                slots.append({
                    "slot": slot_key,
                    "has_item": False,
                    "photo_id": None,
                    "photo_url": None,
                    "adult": is_adult,
                    "gender": gender,
                })

    return slots


# ── Score → text ──────────────────────────────────────────────────────────────

def score_to_text(score: float) -> str:
    """Текстовая категория вместо цифры для ВЕЩИ."""
    if score >= 8.5:
        return "🌟 Отличная вещь!"
    if score >= 7.0:
        return "👍 Хорошая вещь"
    if score >= 5.0:
        return "👌 Базовая вещь"
    return "🏠 Для дома и отдыха"


def outfit_score_to_text(score: float) -> str:
    """Текстовая категория вместо цифры для ОБРАЗА."""
    if score >= 8.5:
        return "🌟 Супер-образ!"
    if score >= 7.0:
        return "👍 Отличный образ"
    if score >= 5.0:
        return "👌 Хороший образ"
    return "🤔 Можно лучше — попробуй переодень"
