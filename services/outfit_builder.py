"""
Единый модуль сборки образа.

Используется и morning_brief.py и wardrobe.py — единая точка правды.
"""
import random
from datetime import date

from services.outfit_selector import _select_outfit, _get_temp_regime
from services.brief_weather import _SEASONS
from worker.tasks.style_config import get_placeholder_label, _needs_tights, get_temp_regime as _style_get_temp_regime

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
    temp_now: float | None = None,
    temp_day: float | None = None,
    temp_evening: float | None = None,
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

    # Header на коллаже — краткий, без дублирования с текстом caption
    # Текст caption уже содержит подробную погоду, поэтому здесь только ключевое
    day_str = f"{_DAY_NAMES[today.weekday()]}, {today.day} {_MONTH_NAMES[today.month]}"

    # Показываем текущую температуру (или утреннюю) — кратко
    if temp_now is not None:
        sn = "+" if temp_now >= 0 else ""
        temp_str = f"{sn}{temp_now:.0f}°C"
    elif temp is not None:
        sm = "+" if temp >= 0 else ""
        temp_str = f"{sm}{temp:.0f}°C"
    else:
        temp_str = ""

    if child:
        context = child.name
        if day_type:
            context += f", {day_type}"
        header = f"{day_str} · {temp_str} · {context}" if temp_str else f"{day_str} · {context}"
    else:
        day_ctx = "выходной" if today.weekday() >= 5 else "будний день"
        header = f"{day_str} · {temp_str} · {day_ctx}" if temp_str else f"{day_str} · {day_ctx}"

    # Footer: weather-aware comment
    footer = ""
    if temp_evening is not None and temp is not None and temp - temp_evening >= 5:
        se = "+" if temp_evening >= 0 else ""
        footer = f"К вечеру {se}{temp_evening:.0f}°C -- оденьте потеплее на забирание"
    elif precip > 50:
        footer = "Возможен дождь -- возьмите зонт"

    return {
        "theme": theme,
        "header_text": header,
        "footer_text": footer,
    }


# ── Outfit slots builder ──────────────────────────────────────────────────────

_SLOT_ORDER = [
    "outerwear", "top", "removable_layer", "bottom", "one_piece",
    "footwear", "hat", "scarf", "gloves", "tights",
]


def build_outfit_slots(
    outfit: dict,
    child=None,
    user=None,
    temp: float | None = None,
    colortype: str = "default",
    regime: str | None = None,
) -> list[dict]:
    """Конвертирует outfit dict → outfit_slots для build_collage.

    Единая точка — и для morning_brief, и для wardrobe handler.
    Обувь показывается ВСЕГДА (ребёнок/взрослый не ходит босиком).
    Плейсхолдеры определяются через get_placeholder_label (SEASON_SLOT_TYPES).
    """
    is_adult = child is None
    gender = getattr(child, "gender", "girl") if child else "girl"
    _temp = temp if temp is not None else 15.0

    if regime is None:
        regime = _style_get_temp_regime(_temp)

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

        # socks → tights fallback
        if slot_key == "tights":
            item = outfit.get("tights") or outfit.get("socks")
        elif slot_key == "removable_layer":
            item = outfit.get("removable_layer")
        else:
            item = outfit.get(slot_key)

        if item and getattr(item, "show_in_collage", True):
            seen.add(slot_key)
            slots.append({
                "slot": slot_key,
                "item_type": item.type,
                "item_color": getattr(item, "color", "") or "",
                "photo_id": item.photo_id,
                "photo_url": getattr(item, "photo_url", None),
                "has_item": True,
                "adult": is_adult,
                "gender": gender,
            })
        else:
            # Нужен ли плейсхолдер? Footwear — всегда. Остальное — через get_placeholder_label.
            if slot_key == "footwear":
                needs_placeholder = True
            elif slot_key == "removable_layer":
                needs_placeholder = False  # плейсхолдер для removable_layer не нужен
            else:
                ph_label = get_placeholder_label(slot_key, colortype, regime)
                needs_placeholder = ph_label is not None
                # Для top/bottom/one_piece get_placeholder_label может вернуть None только
                # если слот отсутствует в SEASON_SLOT_TYPES — тогда не показываем.
                # Дополнительная защита: top/bottom нужны если нет one_piece
                if slot_key in ("top", "bottom") and not has_one_piece and ph_label is not None:
                    needs_placeholder = True
                elif slot_key == "one_piece" and not has_top_bottom and ph_label is not None:
                    needs_placeholder = True

            if needs_placeholder:
                seen.add(slot_key)
                ph_slot: dict = {
                    "slot": slot_key,
                    "has_item": False,
                    "photo_id": None,
                    "photo_url": None,
                    "adult": is_adult,
                    "gender": gender,
                }
                # Подпись placeholder по температуре
                if slot_key == "outerwear":
                    if _temp > 10:
                        ph_slot["label"] = "Ветровка"
                    elif _temp > 0:
                        ph_slot["label"] = "Куртка"
                    else:
                        ph_slot["label"] = "Тёплая куртка"
                elif slot_key == "footwear":
                    if _temp > 20:
                        ph_slot["label"] = "Сандалии"
                    elif _temp > 5:
                        ph_slot["label"] = "Кроссовки"
                    else:
                        ph_slot["label"] = "Ботинки"
                slots.append(ph_slot)

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
    return "👕 Уютная вещь для дома"


def outfit_score_to_text(score: float) -> str:
    """Текстовая категория вместо цифры для ОБРАЗА."""
    if score >= 8.5:
        return "🌟 Супер-образ!"
    if score >= 7.0:
        return "👍 Отличный образ"
    if score >= 5.0:
        return "👌 Хороший образ"
    return "👌 Образ на каждый день"


# ── Цветовые кружки для Telegram-текста (НЕ PIL) ─────────────────────────

_COLOR_CIRCLES: dict[str, str] = {
    "красн": "🔴", "алый": "🔴", "бордо": "🔴",
    "розов": "🟣", "пыльно": "🟣", "лилов": "🟣", "малин": "🟣", "фукси": "🟣",
    "оранж": "🟠", "персик": "🟠", "рыж": "🟠", "коралл": "🟠",
    "жёлт": "🟡", "золот": "🟡", "лимон": "🟡", "горчич": "🟡",
    "зелён": "🟢", "хаки": "🟢", "мятн": "🟢", "оливк": "🟢", "изумруд": "🟢",
    "голуб": "🔵", "бирюз": "🔵", "лазур": "🔵",
    "синий": "🔵", "синев": "🔵", "navy": "🔵", "индиго": "🔵", "деним": "🔵",
    "фиолет": "🟣", "сирен": "🟣", "лаванд": "🟣",
    "корич": "🟤", "шоколад": "🟤", "кофе": "🟤", "каштан": "🟤",
    "беж": "🟡", "кремов": "🟡", "молочн": "🟡", "слонов": "🟡",
    "бел": "⚪", "снежн": "⚪",
    "чёрн": "⚫",
    "сер": "⚪", "графит": "⚫", "стальн": "⚪",
}


def color_circle(color_str: str) -> str:
    """Возвращает цветной кружок-эмодзи по названию цвета (для Telegram-текста, не PIL)."""
    if not color_str:
        return "⚪"
    color_lower = color_str.lower()
    for key, emoji in _COLOR_CIRCLES.items():
        if key in color_lower:
            return emoji
    return "⚪"


# ── Wardrobe summary для системного промпта чата ──────────────────────────

_WARDROBE_GROUP_NAMES: dict[str, str] = {
    "outerwear": "Верхняя одежда",
    "top": "Верх",
    "bottom": "Низ",
    "one_piece": "Платья/комбинезоны",
    "footwear": "Обувь",
    "accessory": "Аксессуары",
    "underwear": "Бельё",
    "base_layer": "Базовый слой",
}


async def get_wardrobe_summary(owner_id, owner_type: str, session) -> str:
    """Краткое описание гардероба для system prompt Haiku (max ~300 токенов)."""
    from db.crud.wardrobe import get_owner_items
    items = await get_owner_items(session, owner_id, owner_type)
    if not items:
        return "Гардероб пуст."

    groups: dict[str, list[str]] = {}
    for item in items:
        cg = item.category_group or "другое"
        groups.setdefault(cg, []).append(f"{item.type} ({item.color})")

    lines = [f"В гардеробе {len(items)} вещей:"]
    for cg, items_list in list(groups.items())[:8]:
        name = _WARDROBE_GROUP_NAMES.get(cg, cg)
        shown = items_list[:5]
        extra = len(items_list) - 5
        line = f"  {name}: {', '.join(shown)}"
        if extra > 0:
            line += f" и ещё {extra}"
        lines.append(line)

    return "\n".join(lines)


_MISSING_SLOT_NAMES = {
    "outerwear": "тёплую куртку", "footwear": "обувь",
    "hat": "шапку", "scarf": "шарф", "gloves": "перчатки",
    "top": "верх", "bottom": "низ",
}


def warm_outfit_comment(
    score: float,
    child_name: str = None,
    temp: float = None,
    has_outerwear: bool = True,
    missing_slots: list = None,
) -> str:
    """Тёплый развёрнутый комментарий Касси к образу с советом."""
    name = child_name or "ты"

    if score >= 8.5:
        options = [
            f"Отличный образ, {name}! Тепло, стильно и всё сочетается ✨",
            f"Собрала классный образ для {name}! Будет выглядеть замечательно",
            f"Образ на все сто, {name}! Цвета отлично играют вместе",
        ]
    elif score >= 7.0:
        options = [
            f"Хороший образ, {name} — и тепло, и красиво! Добавь яркий аксессуар — будет ещё лучше",
            f"Отличный образ для {name}! Всё по погоде. Попробуй добавить шарф для настроения",
            f"Симпатичный образ, {name}! Комфортно весь день",
        ]
    elif score >= 5.0:
        options = [
            f"Удобный образ, {name}! Добавь пару ярких вещей — комбинаций станет больше",
            f"Удобный образ для {name}! Загрузи ещё вещей — смогу собирать интереснее",
        ]
    else:
        options = [
            f"Собрала из того что есть, {name}. Добавь ещё вещей — образы станут разнообразнее!",
        ]

    comment = random.choice(options)

    if missing_slots:
        missing_text = [_MISSING_SLOT_NAMES[s] for s in missing_slots[:2] if s in _MISSING_SLOT_NAMES]
        if missing_text:
            comment += f"\nСовет: добавь {' и '.join(missing_text)} в гардероб!"
    elif temp is not None and temp <= 5 and not has_outerwear:
        comment += "\n⚠️ Холодно — добавь тёплую куртку в гардероб!"

    return comment


async def get_wardrobe_summary_cached(owner_id, owner_type: str, redis, session) -> str:
    """Wardrobe summary с кешем в Redis (1 час TTL)."""
    cache_key = f"wardrobe_summary:{owner_id}"
    if redis:
        try:
            cached = await redis.get(cache_key)
            if cached:
                return cached.decode() if isinstance(cached, bytes) else cached
        except Exception:
            pass

    summary = await get_wardrobe_summary(owner_id, owner_type, session)

    if redis:
        try:
            await redis.set(cache_key, summary, ex=3600)
        except Exception:
            pass

    return summary
