"""
Форматирование текста Morning Brief для Telegram.
"""
from worker.tasks.style_config import get_placeholder_label, SLOT_EMOJI

_MISSING = " (в гардеробе нет — добавь фото)"


def _format_item(item) -> str:
    """Форматирует вещь: тип (цвет), без дубля цвета если уже есть в названии."""
    type_lower = (item.type or "").lower()
    color_lower = (item.color or "").lower()
    if not color_lower:
        return (item.type or "").strip()
    # Сравниваем по стему (без последних 2 символов), чтобы
    # "серебристый" находился в "серебристые", "розовый" в "розовые" и т.д.
    stem = color_lower[:-2] if len(color_lower) > 5 else color_lower
    if stem in type_lower:
        return (item.type or "").strip()
    return f"{(item.type or '').strip()} ({item.color})"


def _format_child_block(
    child_name: str,
    day_type: str,
    outfit: dict,
    outfit_comment: str | None = None,
    temp: float | None = None,
    colortype: str = "default",
    regime: str = "прохладно",
) -> str:
    temp = temp if temp is not None else outfit.get("temp", 15.0)
    lines = [f"👧 {child_name} ({day_type}):"]

    # Термобельё
    if outfit["thermal_top"] or outfit["thermal_bottom"]:
        parts = []
        if outfit["thermal_top"]:
            parts.append(f"→ {_format_item(outfit['thermal_top'])}")
        if outfit["thermal_bottom"]:
            parts.append(f"→ {_format_item(outfit['thermal_bottom'])}")
        lines.append("🧤 Термобельё: " + " ".join(parts))

    # Бельё
    underwear_parts = []
    if outfit["underwear_text"]:
        underwear_parts.append(f"→ {outfit['underwear_text']}")
    for item in outfit["underwear_items"]:
        underwear_parts.append(f"→ {_format_item(item)}")
    if underwear_parts:
        lines.append("👙 Бельё: " + " ".join(underwear_parts))

    # Образ
    lines.append("👗 Образ:")
    if outfit["one_piece"]:
        i = outfit["one_piece"]
        lines.append(f"→ {SLOT_EMOJI['one_piece']} {_format_item(i)}")
    else:
        if outfit["top"]:
            lines.append(f"→ {SLOT_EMOJI['top']} {_format_item(outfit['top'])}")
        else:
            lbl = get_placeholder_label("top", colortype, regime)
            lines.append(f"→ {SLOT_EMOJI['top']} {lbl or 'верх — любой по сезону'}")
        if outfit["bottom"]:
            lines.append(f"→ {SLOT_EMOJI['bottom']} {_format_item(outfit['bottom'])}")
        else:
            lbl = get_placeholder_label("bottom", colortype, regime)
            lines.append(f"→ {SLOT_EMOJI['bottom']} {lbl or 'низ — любой по сезону'}")
    if outfit["removable_layer"]:
        lines.append(f"→ {_format_item(outfit['removable_layer'])} [снять вечером]")

    # Ноги
    leg_item = outfit["tights"] or outfit["socks"]
    if leg_item:
        lines.append(f"🧦 Ноги: → {_format_item(leg_item)}")
    elif temp < 10:
        lbl = get_placeholder_label("tights", colortype, regime)
        lines.append(f"🧦 Ноги: → {lbl or 'колготки или тёплые носки'}")

    # Обувь
    if outfit["footwear"]:
        lines.append(f"{SLOT_EMOJI['footwear']} Обувь: → {_format_item(outfit['footwear'])}")
    else:
        lbl = get_placeholder_label("footwear", colortype, regime)
        lines.append(f"{SLOT_EMOJI['footwear']} Обувь: → {lbl or 'обувь — любая по сезону'}")

    # Верхняя одежда
    if outfit["outerwear"]:
        lines.append(f"{SLOT_EMOJI['outerwear']} Верхняя одежда: → {_format_item(outfit['outerwear'])}")
    elif temp <= 15:
        lbl = get_placeholder_label("outerwear", colortype, regime)
        if lbl:
            lines.append(f"{SLOT_EMOJI['outerwear']} Верхняя одежда: → {lbl}")

    # Аксессуары
    acc_parts = []
    for key in ("hat", "scarf", "gloves"):
        if outfit[key]:
            acc_parts.append(f"→ {_format_item(outfit[key])}")
    if acc_parts:
        lines.append("🎩 Аксессуары: " + " ".join(acc_parts))

    lines.append("")
    if outfit_comment:
        lines.append(f"💬 {outfit_comment}")

    return "\n".join(lines)
