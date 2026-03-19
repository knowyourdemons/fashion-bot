"""
Форматирование текста Morning Brief для Telegram.
"""


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
    """Короткий блок: только невидимые вещи + комментарий стилиста.

    Видимые вещи (top, bottom, outerwear, footwear, hat, scarf, gloves)
    уже отображены на коллаже — не дублируем в тексте.
    """
    lines = [f"👧 {child_name} ({day_type}):"]

    # Невидимые вещи — одной строкой
    under_parts = []

    # Термобельё
    if outfit.get("thermal_top"):
        under_parts.append("термобельё верх")
    if outfit.get("thermal_bottom"):
        under_parts.append("термобельё низ")

    # Бельё
    if outfit.get("underwear_text"):
        under_parts.append(outfit["underwear_text"])
    for item in outfit.get("underwear_items", []):
        name = (item.type or "").split()[0].lower()
        if name:
            under_parts.append(name)

    # Носки / колготки
    leg = outfit.get("tights") or outfit.get("socks")
    if leg:
        name = (leg.type or "").split()[0].lower()
        if name:
            under_parts.append(name)

    if under_parts:
        lines.append(f"🩲 Под одежду: {', '.join(under_parts)}")

    # Комментарий Касси
    if outfit_comment:
        lines.append(f"\n💬 {outfit_comment}")

    return "\n".join(lines)
