"""
Outfit Engine v2: AI-powered outfit selection.

Replaces rule-based _select_outfit() with Haiku-powered selection.
AI picks the visible outfit, rules handle base layer.
Single Haiku call returns BOTH selection AND comment.

Fallback: rule-based selector if AI fails.
"""
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import date

import structlog

from services.outfit_selector import _select_outfit, _get_temp_regime
from services.outfit_builder import (
    _is_base_layer_item,
    has_minimum_outfit,
    BASE_LAYER_TYPE_PATTERNS,
    BASE_LAYER_GROUPS,
)
from worker.tasks.style_config import _needs_tights

logger = structlog.get_logger()

# ── Result dataclass ─────────────────────────────────────────────────────────


@dataclass
class OutfitResult:
    """Result from outfit engine — outfit dict + comment + metadata."""
    outfit: dict                      # same shape as _select_outfit() returns
    comment: str                      # Kassi comment (from AI reason)
    is_wow: bool = False
    ai_selected: bool = False         # True if AI picked, False if fallback


# ── Segment prompts ──────────────────────────────────────────────────────────

_SYSTEM_MOM = """Ты стилист Касси. Подбираешь одежду для ребёнка.

ЗАДАЧА: из списка вещей выбери лучшую комбинацию на день.

ПРАВИЛА для детского образа:
- Главное: УДОБНО, тепло, практично. Легко надеть/снять.
- При <10° платье/юбку для садика НЕ предлагать (бегать неудобно).
- При <5° обязательны: тёплая куртка, шапка.
- При >20° можно шорты, платье, лёгкую обувь.
- Цвета: мягкие рекомендации (для ребёнка всё сочетается).
- Тон: тёплый, как подруга-мама. Коротко и по делу.

ФОРМАТ ОТВЕТА — строго JSON:
{
  "items": {"top": "uuid", "bottom": "uuid", "outerwear": "uuid", "footwear": "uuid", "hat": "uuid"},
  "comment": "2-3 предложения: что выбрала и почему. Тёплый тон.",
  "is_wow": false
}

- Включай ТОЛЬКО слоты для которых выбрал вещь.
- UUID бери из списка кандидатов.
- comment = комментарий Касси к образу. НЕ упоминай числовой скор.
- is_wow = true если образ особенно удачный (цвета + стиль + сезон)."""

_SYSTEM_WOMAN = """Ты стилист Касси. Подбираешь образ для женщины.

ЗАДАЧА: из списка вещей выбери СТИЛЬНУЮ комбинацию на день.

ПРАВИЛА для женского образа:
- Главное: СТИЛЬНО, неожиданные сочетания которые женщина не подумала бы сама.
- Цвета должны гармонировать: нейтральная база + яркий акцент, или monochrome.
- Аксессуары (сумка, шарф) = завершение образа, включи если есть.
- Платье — приветствуется для офиса/свидания.
- При ре-ролле дай ДРУГОЕ настроение, не просто другую кофту.
- Тон: стильный, уверенный. Объясни ПОЧЕМУ это сочетание работает.

ФОРМАТ ОТВЕТА — строго JSON:
{
  "items": {"top": "uuid", "bottom": "uuid", "outerwear": "uuid", "footwear": "uuid"},
  "comment": "2-3 предложения: почему это сочетание работает. Про цвет, стиль, настроение.",
  "is_wow": false
}

- Включай ТОЛЬКО слоты для которых выбрал вещь.
- UUID бери из списка кандидатов.
- comment = стилистический разбор. НЕ упоминай числовой скор.
- is_wow = true если образ особенно стильный."""

# ── Item serialization ───────────────────────────────────────────────────────

# Max items to send to AI (prevent token overflow)
_MAX_CANDIDATES = 60
_MAX_PER_GROUP = 15

# Slot categories the AI can pick from (visual slots only)
_AI_SLOTS = frozenset([
    "outerwear", "top", "bottom", "one_piece", "footwear",
    "accessory",  # hat, scarf, gloves, bag
])


def _serialize_item(item) -> dict:
    """Serialize a wardrobe item for AI consumption."""
    return {
        "id": str(item.id),
        "cg": item.category_group or "top",
        "type": item.type or "",
        "color": item.color or "",
        "style": getattr(item, "style", "") or "",
        "score": float(item.score_item) if item.score_item else 5.0,
    }


def _build_candidates(items: list, season: str, today: date) -> dict[str, list[dict]]:
    """Group and serialize items for AI, filtering by season and base layer."""
    available = [
        i for i in items
        if (not i.season or season in i.season)
        and not _is_base_layer_item(i)
    ]

    # Group by category_group
    groups: dict[str, list] = {}
    for item in available:
        cg = item.category_group or "top"
        groups.setdefault(cg, []).append(item)

    # Serialize, capping per group and total
    result: dict[str, list[dict]] = {}
    total = 0
    for cg, group_items in groups.items():
        # Sort by score desc, take top N
        sorted_items = sorted(
            group_items,
            key=lambda x: float(x.score_item) if x.score_item else 0,
            reverse=True,
        )[:_MAX_PER_GROUP]

        serialized = [_serialize_item(i) for i in sorted_items]
        result[cg] = serialized
        total += len(serialized)

        if total >= _MAX_CANDIDATES:
            break

    return result


def _build_candidates_text(candidates: dict[str, list[dict]]) -> str:
    """Format candidates for AI prompt."""
    _CG_NAMES = {
        "outerwear": "ВЕРХНЯЯ ОДЕЖДА",
        "top": "ВЕРХ",
        "bottom": "НИЗ",
        "one_piece": "ПЛАТЬЯ/КОМБИНЕЗОНЫ",
        "footwear": "ОБУВЬ",
        "accessory": "АКСЕССУАРЫ",
        "sportswear": "СПОРТ",
    }
    lines = []
    for cg, items in candidates.items():
        name = _CG_NAMES.get(cg, cg.upper())
        item_strs = []
        for it in items:
            s = f'{it["id"][:8]}.. {it["type"]} {it["color"]}'
            if it.get("style"):
                s += f' ({it["style"]})'
            item_strs.append(s)
        lines.append(f"{name}:\n" + "\n".join(f"  - {s}" for s in item_strs))
    return "\n\n".join(lines)


# ── Rotation constraint ─────────────────────────────────────────────────────

def _build_rotation_text(recent_outfit_ids: list[list[str]]) -> str:
    """Build rotation constraint text from recent outfit history."""
    if not recent_outfit_ids:
        return ""

    parts = []
    if recent_outfit_ids:
        # Yesterday's outfit
        yesterday = recent_outfit_ids[0]
        if yesterday:
            parts.append(
                f"Вчерашний образ (НЕ повторять верх+низ вместе): "
                f"{', '.join(uid[:8] for uid in yesterday[:6])}"
            )

    # Full outfit sets from last 5 days
    if len(recent_outfit_ids) > 1:
        parts.append(
            f"Образы за {len(recent_outfit_ids)} дней (избегать полных повторов)."
        )

    return "\n".join(parts) if parts else ""


# ── Build user prompt ────────────────────────────────────────────────────────

def _build_user_prompt(
    candidates: dict[str, list[dict]],
    temp_morning: float,
    temp_evening: float,
    season: str,
    regime: str,
    segment: str,
    child_name: str | None,
    child_age: int | None,
    child_gender: str | None,
    colortype: str | None,
    day_type: str = "",
    rotation_text: str = "",
    item_count_total: int = 0,
) -> str:
    """Build the user prompt for Haiku."""
    _season_ru = {
        "winter": "зима", "spring": "весна",
        "summer": "лето", "autumn": "осень",
    }.get(season, season)

    parts = []

    # Context
    if child_name and child_age:
        gender_ru = "девочка" if child_gender == "girl" else "мальчик"
        parts.append(f"Ребёнок: {child_name}, {child_age} лет, {gender_ru}.")
    if day_type:
        parts.append(f"Контекст: {day_type}.")

    # Weather
    sm = "+" if temp_morning >= 0 else ""
    se = "+" if temp_evening >= 0 else ""
    parts.append(
        f"Погода: утро {sm}{temp_morning:.0f}°C, вечер {se}{temp_evening:.0f}°C. "
        f"Сезон: {_season_ru}. Режим: {regime}."
    )

    # Colortype
    if colortype and colortype != "default":
        parts.append(f"Цветотип: {colortype}. Учитывай при выборе цветов.")

    # Required slots hint
    required = ["top или one_piece", "bottom (если не платье)", "обувь"]
    if temp_morning <= 15:
        required.append("верхняя одежда")
    if temp_morning < 10:
        required.append("шапка")
    if temp_morning < 5:
        required.append("шарф")
    parts.append(f"Нужны как минимум: {', '.join(required)}.")

    # Item count awareness
    if item_count_total <= 2:
        parts.append(
            "В гардеробе мало вещей (1-2). НЕ хвали 'образ'. "
            "Похвали конкретную вещь и мотивируй сфоткать ещё."
        )
    elif item_count_total <= 5:
        parts.append(
            "В гардеробе 3-5 вещей. Прокомментируй сочетание."
        )

    # Rotation
    if rotation_text:
        parts.append(rotation_text)

    # Candidates
    candidates_text = _build_candidates_text(candidates)
    parts.append(f"\nДоступные вещи:\n{candidates_text}")

    return "\n".join(parts)


# ── Parse AI response ────────────────────────────────────────────────────────

def _parse_ai_response(raw: str, items_by_id: dict) -> tuple[dict, str, bool] | None:
    """Parse Haiku JSON response → (slot_items, comment, is_wow) or None."""
    # Extract JSON from response
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    # Try to find JSON object
    match = re.search(r'\{[^{}]*"items"[^{}]*\{[^{}]*\}[^{}]*"comment"[^{}]*\}', text, re.DOTALL)
    if not match:
        # Fallback: try to parse the whole thing
        match = re.search(r'\{.*\}', text, re.DOTALL)

    if not match:
        logger.warning("outfit_engine.no_json_found", raw=raw[:200])
        return None

    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        logger.warning("outfit_engine.json_parse_failed", raw=match.group()[:200])
        return None

    items_dict = data.get("items", {})
    comment = data.get("comment", "")
    is_wow = data.get("is_wow", False)

    if not items_dict or not comment:
        logger.warning("outfit_engine.incomplete_response", items=bool(items_dict), comment=bool(comment))
        return None

    # Map UUIDs back to items (match by prefix)
    slot_items: dict[str, object] = {}
    for slot, uid_str in items_dict.items():
        if not uid_str:
            continue
        # Try exact match first, then prefix match
        item = items_by_id.get(uid_str)
        if not item:
            # Try prefix match (AI might truncate UUIDs)
            for full_id, obj in items_by_id.items():
                if full_id.startswith(uid_str[:8]):
                    item = obj
                    break
        if item:
            slot_items[slot] = item
        else:
            logger.warning("outfit_engine.uuid_not_found", slot=slot, uuid=uid_str[:12])

    if not slot_items:
        return None

    return slot_items, comment, is_wow


# ── Build outfit dict from AI selection ──────────────────────────────────────

def _build_outfit_from_ai(
    slot_items: dict,
    all_items: list,
    temp: float,
    season: str,
    today: date,
) -> dict:
    """Build outfit dict (same shape as _select_outfit) from AI selection."""
    result: dict = {
        "thermal_top": None,
        "thermal_bottom": None,
        "underwear_items": [],
        "underwear_text": None,
        "one_piece": slot_items.get("one_piece"),
        "top": slot_items.get("top"),
        "bottom": slot_items.get("bottom"),
        "removable_layer": slot_items.get("removable_layer"),
        "tights": None,
        "socks": None,
        "footwear": slot_items.get("footwear"),
        "outerwear": slot_items.get("outerwear"),
        "hat": slot_items.get("hat"),
        "scarf": slot_items.get("scarf"),
        "gloves": slot_items.get("gloves"),
        "warnings": [],
        "all_items": [],
    }

    # ── Base layer from rules (not AI) ──
    available = [
        i for i in all_items
        if (not i.season or season in i.season)
    ]

    # Thermal underwear (temp <= 5°C)
    if temp <= 5:
        for i in available:
            if i.category_group == "underwear" and "термо" in (i.type or "").lower():
                if not result["thermal_top"]:
                    result["thermal_top"] = i
                elif not result["thermal_bottom"]:
                    result["thermal_bottom"] = i

    # Regular underwear
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

    # Tights/socks
    if temp <= 15:
        if _needs_tights(result, temp):
            tights = next(
                (i for i in available
                 if i.category_group in ("base_layer", "footwear")
                 and any(w in (i.type or "").lower() for w in ["колготк", "tights"])),
                None,
            )
            result["tights"] = tights
        socks = next(
            (i for i in available
             if i.category_group in ("base_layer", "footwear")
             and any(w in (i.type or "").lower() for w in ["носк", "socks", "гольф"])),
            None,
        )
        result["socks"] = socks
    else:
        socks = next(
            (i for i in available
             if i.category_group in ("base_layer", "footwear")
             and any(w in (i.type or "").lower() for w in ["носк", "socks", "гольф"])),
            None,
        )
        result["socks"] = socks

    # Warnings
    temp_eve = temp  # AI doesn't return evening temp, reuse
    if abs(temp_eve - temp) > 8:
        sm = "+" if temp >= 0 else ""
        se = "+" if temp_eve >= 0 else ""
        result["warnings"].append(
            f"🌡 Утром {sm}{temp}°C → вечером {se}{temp_eve}°C — одень слоями!"
        )

    # Collect all items for scoring
    all_outfit = []
    for key in ("thermal_top", "thermal_bottom", "one_piece", "top", "bottom",
                "removable_layer", "tights", "socks", "footwear", "outerwear",
                "hat", "scarf", "gloves"):
        if result[key]:
            all_outfit.append(result[key])
    all_outfit.extend(result["underwear_items"])
    result["all_items"] = all_outfit
    result["temp"] = temp

    return result


# ══════════════════════════════════════════════════════════════════════════════
# MAIN API
# ══════════════════════════════════════════════════════════════════════════════


async def select_outfit_ai(
    pool,
    items: list,
    season: str,
    today: date,
    temp_morning: float,
    temp_evening: float,
    precip_evening: float = 0,
    segment: str = "mom_girl",
    child_name: str | None = None,
    child_age: int | None = None,
    child_gender: str | None = None,
    colortype: str | None = None,
    recent_outfit_ids: list[list[str]] | None = None,
    day_type: str = "",
    redis=None,
) -> OutfitResult:
    """AI-powered outfit selection. Returns OutfitResult with outfit + comment.

    Falls back to rule-based _select_outfit() + template comment on failure.
    """
    temp = temp_morning if temp_morning is not None else 15.0
    temp_eve = temp_evening if temp_evening is not None else temp
    regime = _get_temp_regime(temp)

    # Build candidates (excluding base layer)
    candidates = _build_candidates(items, season, today)
    total_candidate_count = sum(len(v) for v in candidates.values())

    # If too few candidates, use rule-based fallback directly
    if total_candidate_count < 2:
        return _fallback_result(items, season, today, temp, temp_eve, precip_evening,
                                segment, child_name)

    # Build items lookup by ID
    items_by_id: dict[str, object] = {}
    for item in items:
        items_by_id[str(item.id)] = item

    # Rotation text
    rotation_text = _build_rotation_text(recent_outfit_ids or [])

    # Segment-specific system prompt
    is_mom = segment in ("mom_girl", "mom_boy")
    system_prompt = _SYSTEM_MOM if is_mom else _SYSTEM_WOMAN

    # Colortype addition
    if colortype and colortype != "default":
        system_prompt += f"\n\nЦветотип: {colortype}. Учитывай при выборе вещей."

    # User prompt
    user_prompt = _build_user_prompt(
        candidates=candidates,
        temp_morning=temp,
        temp_evening=temp_eve,
        season=season,
        regime=regime,
        segment=segment,
        child_name=child_name,
        child_age=child_age,
        child_gender=child_gender,
        colortype=colortype,
        day_type=day_type,
        rotation_text=rotation_text,
        item_count_total=total_candidate_count,
    )

    # Call Haiku
    try:
        response = await pool.create_message(
            model="claude-haiku-4-5-20251001",
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=400,
        )
        raw = response.content[0].text.strip() if response.content else ""

        logger.info(
            "outfit_engine.ai_response",
            raw_len=len(raw),
            segment=segment,
        )

    except Exception as e:
        logger.warning("outfit_engine.ai_failed", error=str(e))
        return _fallback_result(items, season, today, temp, temp_eve, precip_evening,
                                segment, child_name)

    # Parse response
    parsed = _parse_ai_response(raw, items_by_id)
    if not parsed:
        logger.warning("outfit_engine.parse_failed")
        return _fallback_result(items, season, today, temp, temp_eve, precip_evening,
                                segment, child_name)

    slot_items, comment, is_wow = parsed

    # Build outfit dict
    outfit = _build_outfit_from_ai(slot_items, items, temp, season, today)

    # Post-validation: must have minimum outfit
    if not has_minimum_outfit(outfit):
        logger.warning("outfit_engine.no_minimum", slots=list(slot_items.keys()))
        return _fallback_result(items, season, today, temp, temp_eve, precip_evening,
                                segment, child_name)

    # Post-validation: shorts at cold temps
    if outfit.get("bottom") and temp < 10:
        bottom_type = (getattr(outfit["bottom"], "type", "") or "").lower()
        if "шорт" in bottom_type:
            # Try to find pants instead
            pants = next(
                (i for i in items
                 if i.category_group == "bottom"
                 and "шорт" not in (i.type or "").lower()
                 and (not i.season or season in i.season)),
                None,
            )
            if pants:
                outfit["bottom"] = pants

    return OutfitResult(
        outfit=outfit,
        comment=comment,
        is_wow=is_wow,
        ai_selected=True,
    )


# ── Fallback ─────────────────────────────────────────────────────────────────


def _fallback_result(
    items: list,
    season: str,
    today: date,
    temp: float,
    temp_eve: float,
    precip: float,
    segment: str,
    child_name: str | None,
) -> OutfitResult:
    """Fallback to rule-based selector + template comment."""
    from services.outfit_builder import warm_outfit_comment

    outfit = _select_outfit(items, season, today, temp, temp_eve, precip)

    # Build simple comment
    scored = [float(i.score_item) for i in outfit.get("all_items", []) if i.score_item]
    avg = sum(scored) / len(scored) if scored else 6.0

    visual_items = [i for i in outfit.get("all_items", []) if not _is_base_layer_item(i)]
    first_desc = ""
    if len(visual_items) == 1:
        first_desc = f"{visual_items[0].type} {visual_items[0].color}".strip().lower()

    comment = warm_outfit_comment(
        score=avg,
        child_name=child_name,
        temp=temp,
        has_outerwear=outfit.get("outerwear") is not None,
        missing_slots=[],
        real_item_count=len(visual_items),
        first_item_desc=first_desc,
    )

    is_wow = bool(scored and avg >= 8.0)

    return OutfitResult(
        outfit=outfit,
        comment=comment,
        is_wow=is_wow,
        ai_selected=False,
    )
