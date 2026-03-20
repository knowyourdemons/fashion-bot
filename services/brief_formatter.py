"""
Форматирование текста Morning Brief для Telegram (HTML parse_mode).
Порядок одевания: под одежду → одежда → обувь → на выход.
"""
from services.brief_weather import wmo_to_emoji
from services.outfit_builder import color_circle


def _sign(t: float) -> str:
    return "+" if t >= 0 else ""


def _format_item(item) -> str:
    """Форматирует вещь: тип (цвет)."""
    type_lower = (item.type or "").lower()
    color_lower = (item.color or "").lower()
    if not color_lower:
        return (item.type or "").strip()
    stem = color_lower[:-2] if len(color_lower) > 5 else color_lower
    if stem in type_lower:
        return (item.type or "").strip()
    return f"{(item.type or '').strip()} {item.color}"


def format_weather_line(weather: dict) -> str:
    """Погода утро→день→вечер с эмодзи: ☀️ +4° утро → 🌤 +7° день → 🌧 +2° вечер"""
    parts = []
    tm = weather.get("temp_morning")
    td = weather.get("temp_day")
    te = weather.get("temp_evening")
    wm = weather.get("wmo_morning", 0)
    wd = weather.get("wmo_day", 0)
    we = weather.get("wmo_evening", 0)

    if tm is not None:
        parts.append(f"{wmo_to_emoji(wm)} {_sign(tm)}{round(tm)}° утро")
    if td is not None:
        parts.append(f"{wmo_to_emoji(wd)} {_sign(td)}{round(td)}° день")
    if te is not None:
        parts.append(f"{wmo_to_emoji(we)} {_sign(te)}{round(te)}° вечер")
    return " → ".join(parts)


def _format_child_block(
    child_name: str,
    day_type: str,
    outfit: dict,
    outfit_comment: str | None = None,
    temp: float | None = None,
    colortype: str = "default",
    regime: str = "прохладно",
) -> str:
    """HTML блок ребёнка в порядке одевания.

    4 группы:
    1. Под одежду (приглушённый) — трусики, майка, колготки
    2. Одежда (жирный, с цветными точками) — кофта, штаны
    3. Обувь
    4. На выход — куртка, шапка, шарф (последнее, берёшь у двери)
    """
    lines = [f"👧 <b>{child_name}</b>, {day_type}"]

    # ── 1. Под одежду ──
    under_parts = []
    if outfit.get("thermal_top"):
        under_parts.append("термобельё верх")
    if outfit.get("thermal_bottom"):
        under_parts.append("термобельё низ")
    if outfit.get("underwear_text"):
        under_parts.append(outfit["underwear_text"])
    for item in outfit.get("underwear_items", []):
        name = (item.type or "").split()[0].lower()
        if name:
            under_parts.append(name)
    leg = outfit.get("tights") or outfit.get("socks")
    if leg:
        under_parts.append(_format_item(leg))

    if under_parts:
        lines.append("<i>ПОД ОДЕЖДУ</i>")
        lines.append(f"<i>  {', '.join(under_parts)}</i>")

    # ── 2. Одежда ──
    clothes = []
    for slot_key in ("top", "removable_layer", "bottom", "one_piece"):
        item = outfit.get(slot_key)
        if item and hasattr(item, "type"):
            dot = color_circle(getattr(item, "color", ""))
            clothes.append(f"{dot} <b>{_format_item(item)}</b>")
    if clothes:
        lines.append("ОДЕЖДА")
        lines.extend(f"  {c}" for c in clothes)

    # ── 3. Обувь ──
    foot = outfit.get("footwear")
    if foot and hasattr(foot, "type"):
        dot = color_circle(getattr(foot, "color", ""))
        lines.append("ОБУВЬ")
        lines.append(f"  {dot} {_format_item(foot)}")

    # ── 4. На выход ──
    exit_items = []
    for slot_key in ("outerwear", "hat", "scarf", "gloves"):
        item = outfit.get(slot_key)
        if item and hasattr(item, "type"):
            dot = color_circle(getattr(item, "color", ""))
            exit_items.append(f"{dot} {_format_item(item)}")
        elif slot_key == "outerwear" and temp is not None and temp < 15:
            exit_items.append("Куртка <i>добавь</i>")
        elif slot_key == "hat" and temp is not None and temp < 8:
            exit_items.append("Шапка <i>добавь</i>")
        elif slot_key == "scarf" and temp is not None and temp < 5:
            exit_items.append("Шарф <i>добавь</i>")
    if exit_items:
        lines.append("НА ВЫХОД")
        lines.extend(f"  {e}" for e in exit_items)

    # ── Комментарий Касси ──
    if outfit_comment:
        lines.append(f"\n💬 <i>{outfit_comment}</i>\n— Касси")

    return "\n".join(lines)
