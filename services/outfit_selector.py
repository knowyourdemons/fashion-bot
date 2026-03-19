"""
Выбор образа послойно по температуре и сезону.
Чистая бизнес-логика без side effects.
"""
from datetime import date

from worker.tasks.style_config import _needs_tights


def _get_temp_regime(temp: float) -> str:
    if temp > 25:
        return "жара"
    elif temp > 15:
        return "тепло"
    elif temp > 10:
        return "прохладно"
    elif temp > 5:
        return "холодно"
    elif temp > 0:
        return "мороз"
    else:
        return "сильный_мороз"


def _select_outfit(
    items: list,
    season: str,
    today: date,
    temp_morning: float | None = None,
    temp_evening: float | None = None,
    precip_evening: float = 0,
) -> dict:
    """Выбирает образ послойно с учётом температуры.

    Returns dict с ключами:
        thermal_top, thermal_bottom, underwear_items, underwear_text,
        one_piece, top, bottom, removable_layer, tights, socks,
        footwear, outerwear, hat, scarf, gloves, warnings, all_items
    """
    temp = temp_morning if temp_morning is not None else 15.0
    temp_eve = temp_evening if temp_evening is not None else temp
    regime = _get_temp_regime(temp)
    warnings: list[str] = []

    # Переходный период
    if abs(temp_eve - temp) > 8:
        sm = "+" if temp >= 0 else ""
        se = "+" if temp_eve >= 0 else ""
        warnings.append(f"🌡 Утром {sm}{temp}°C → вечером {se}{temp_eve}°C — одень слоями!")

    # Дождь вечером
    if precip_evening and precip_evening > 50:
        warnings.append("☂️ Вечером дождь — возьми зонт!")

    available = [
        i for i in items
        if (not i.season or season in i.season) and i.last_worn != today
    ]

    def _first(cg=None, type_contains=None, type_not_contains=None,
               prefer_contains=None, exclude_ids=None):
        pool = available
        if cg:
            if isinstance(cg, (list, tuple)):
                pool = [i for i in pool if i.category_group in cg]
            else:
                pool = [i for i in pool if i.category_group == cg]
        if type_contains:
            pool = [i for i in pool if type_contains.lower() in (i.type or "").lower()]
        if type_not_contains:
            pool = [i for i in pool if type_not_contains.lower() not in (i.type or "").lower()]
        if exclude_ids:
            pool = [i for i in pool if i.id not in exclude_ids]
        if prefer_contains and pool:
            preferred = [i for i in pool if prefer_contains.lower() in (i.type or "").lower()]
            return preferred[0] if preferred else pool[0]
        return pool[0] if pool else None

    def _first_any(cg, contains_list):
        pool = [i for i in available if i.category_group == cg]
        pool = [i for i in pool if any(c.lower() in (i.type or "").lower() for c in contains_list)]
        return pool[0] if pool else None

    result: dict = {
        "thermal_top": None,
        "thermal_bottom": None,
        "underwear_items": [],
        "underwear_text": None,
        "one_piece": None,
        "top": None,
        "bottom": None,
        "removable_layer": None,
        "tights": None,
        "socks": None,
        "footwear": None,
        "outerwear": None,
        "hat": None,
        "scarf": None,
        "gloves": None,
        "warnings": warnings,
        "all_items": [],
    }

    # ── СЛОЙ 0: Термобельё (temp <= 5°C) ─────────────────────────────────
    if temp <= 5:
        result["thermal_top"] = _first(cg="underwear", type_contains="термо")
        t_top_id = {result["thermal_top"].id} if result["thermal_top"] else set()
        result["thermal_bottom"] = _first(cg="underwear", type_contains="термо", exclude_ids=t_top_id)

    # ── СЛОЙ 1: Бельё (non-thermal underwear) ────────────────────────────
    underwear_pool = [
        i for i in available
        if i.category_group == "underwear" and "термо" not in (i.type or "").lower()
    ]
    trusiki = next(
        (i for i in underwear_pool if any(w in (i.type or "").lower() for w in ["трусик", "underwear"])),
        underwear_pool[0] if underwear_pool else None,
    )
    if trusiki:
        result["underwear_items"].append(trusiki)
        maika = next(
            (i for i in underwear_pool
             if i.id != trusiki.id
             and any(w in (i.type or "").lower() for w in ["майк", "undershirt", "боди"])),
            None,
        )
        if maika:
            result["underwear_items"].append(maika)
    else:
        result["underwear_text"] = "трусики"

    # ── СЛОЙ 2: Основной образ ────────────────────────────────────────────
    if regime in ("жара", "тепло"):
        result["one_piece"] = _first(cg="one_piece")
        if not result["one_piece"]:
            result["top"] = _first(cg="top")
            result["bottom"] = (
                _first(cg="bottom", prefer_contains="шорт")
                or _first(cg="bottom", prefer_contains="юбк")
                or _first(cg="bottom")
            )
    elif regime in ("прохладно", "холодно"):
        result["top"] = (
            _first(cg="top", prefer_contains="кофт")
            or _first(cg="top", prefer_contains="свитер")
            or _first(cg="top")
        )
        result["bottom"] = (
            _first(cg="bottom", prefer_contains="джинс", type_not_contains="шорт")
            or _first(cg="bottom", prefer_contains="брюк", type_not_contains="шорт")
            or _first(cg="bottom", type_not_contains="шорт")
            or _first(cg="bottom")
        )
    else:  # мороз / сильный_мороз
        result["top"] = (
            _first(cg="top", prefer_contains="свитер")
            or _first(cg="top", prefer_contains="кофт")
            or _first(cg="top")
        )
        result["bottom"] = (
            _first(cg="bottom", prefer_contains="брюк", type_not_contains="шорт")
            or _first(cg="bottom", type_not_contains="шорт")
            or _first(cg="bottom")
        )

    # Переходный период — съёмный слой
    if abs(temp_eve - temp) > 8:
        top_id = {result["top"].id} if result["top"] else set()
        removable = next(
            (i for i in available
             if i.category_group == "top"
             and any(w in (i.type or "").lower() for w in ["кофт", "толстовк", "худи"])
             and i.id not in top_id),
            None,
        )
        result["removable_layer"] = removable

    # ── СЛОЙ 3: Колготки/носки ─────────────────────────────────────────────
    if temp <= 15:
        if _needs_tights(result, temp):
            tights = (
                _first_any("base_layer", ["колготк", "tights"])
                or _first_any("footwear", ["колготк", "tights"])
            )
            if tights and temp <= 5:
                warm = next(
                    (i for i in available
                     if i.category_group in ("base_layer", "footwear")
                     and any(w in (i.type or "").lower() for w in ["колготк", "tights"])
                     and any(w in (i.type or "").lower() for w in ["плотн", "тёплые", "warm", "thick"])),
                    tights,
                )
                tights = warm
            result["tights"] = tights
        result["socks"] = (
            _first_any("base_layer", ["носк", "socks", "гольф"])
            or _first_any("footwear", ["носк", "socks", "гольф"])
        )
    else:
        result["socks"] = (
            _first_any("base_layer", ["носк", "socks", "гольф"])
            or _first_any("footwear", ["носк", "socks", "гольф"])
        )

    # ── СЛОЙ 4: Обувь ─────────────────────────────────────────────────────
    sock_types = {"носки", "гольфы", "socks", "колготки", "tights"}
    footwear_pool = [
        i for i in available
        if i.category_group == "footwear"
        and (i.type or "").lower() not in sock_types
    ]
    if footwear_pool:
        if regime == "жара":
            preferred = [i for i in footwear_pool if any(w in (i.type or "").lower() for w in ["сандал", "босоножк", "sandal"])]
        elif regime == "прохладно":
            preferred = [i for i in footwear_pool if any(w in (i.type or "").lower() for w in ["кроссовк", "туфл", "sneaker"])]
        elif regime in ("холодно", "мороз", "сильный_мороз"):
            preferred = [i for i in footwear_pool if any(w in (i.type or "").lower() for w in ["ботинк", "сапог", "boot"])]
        else:
            preferred = []
        result["footwear"] = preferred[0] if preferred else footwear_pool[0]

    # ── СЛОЙ 5: Верхняя одежда ────────────────────────────────────────────
    if temp <= 15:
        outerwear_pool = [i for i in available if i.category_group == "outerwear"]
        if outerwear_pool:
            if temp <= 5:
                warm = [i for i in outerwear_pool if any(w in (i.type or "").lower() for w in ["пуховик", "тёплая", "зимняя", "down"])]
                result["outerwear"] = warm[0] if warm else outerwear_pool[0]
            else:
                result["outerwear"] = outerwear_pool[0]

    # ── СЛОЙ 6: Аксессуары ────────────────────────────────────────────────
    if temp < 10:
        result["hat"] = _first_any("accessory", ["шапк", "hat", "balaclava", "балаклав"])
    if temp < 5:
        result["scarf"] = _first_any("accessory", ["шарф", "scarf"])
    if temp < 0:
        result["gloves"] = _first_any("accessory", ["перчатк", "варежк", "gloves"])

    # Все вещи для скоринга
    all_items = []
    for key in ("thermal_top", "thermal_bottom", "one_piece", "top", "bottom",
                "removable_layer", "tights", "socks", "footwear", "outerwear",
                "hat", "scarf", "gloves"):
        if result[key]:
            all_items.append(result[key])
    all_items.extend(result["underwear_items"])
    result["all_items"] = all_items
    result["temp"] = temp

    return result
