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

# ── Warmth requirements per temperature regime ──────────────────────────────
# (min_warmth, max_warmth) per slot. None = slot not needed.

WARMTH_REQUIREMENTS: dict[str, dict[str, tuple[int, int] | None]] = {
    "жара": {  # > 25°C
        "top": (1, 3), "bottom": (1, 2), "one_piece": (1, 2),
        "outerwear": None, "footwear": (1, 2),
        "hat": (1, 2), "scarf": None, "gloves": None,
    },
    "тепло": {  # 15-25°C
        "top": (1, 4), "bottom": (1, 3), "one_piece": (1, 3),
        "outerwear": (1, 3), "footwear": (1, 3),
        "hat": None, "scarf": None, "gloves": None,
    },
    "прохладно": {  # 10-15°C
        "top": (1, 4), "bottom": (1, 4), "one_piece": (1, 4),
        "outerwear": (2, 4), "footwear": (1, 4),
        "hat": None, "scarf": None, "gloves": None,
    },
    "холодно": {  # 5-10°C
        "top": (2, 5), "bottom": (2, 5), "one_piece": (2, 5),
        "outerwear": (2, 5), "footwear": (2, 5),
        "hat": (2, 5), "scarf": None, "gloves": None,
    },
    "мороз": {  # 0-5°C
        "top": (2, 5), "bottom": (2, 5), "one_piece": None,
        "outerwear": (3, 5), "footwear": (2, 5),
        "hat": (2, 5), "scarf": (2, 5), "gloves": None,
    },
    "сильный_мороз": {  # < 0°C
        "top": (3, 5), "bottom": (3, 5), "one_piece": None,
        "outerwear": (4, 5), "footwear": (3, 5),
        "hat": (3, 5), "scarf": (3, 5), "gloves": (3, 5),
    },
}
# Note: ranges are intentionally wide. AI picks the BEST option from candidates.
# Warmth filter only removes clearly absurd items (t-shirt at -10°C).
# AI prompt handles nuance (prefer warmer items when cold).

# Style clashes (only enforced for women segments)
_STYLE_CLASHES = [
    frozenset({"sport", "formal"}),
    frozenset({"home", "formal"}),
    frozenset({"home", "sport"}),
]


def _filter_by_warmth(items: list, regime: str) -> list:
    """Filter items by warmth requirements for temperature regime.

    Items without warmth_level are kept (graceful degradation).
    If filtering would remove too many items (< 2 per needed slot),
    returns original list (better to show something than nothing).
    """
    reqs = WARMTH_REQUIREMENTS.get(regime, {})
    if not reqs:
        return items

    filtered = []
    for item in items:
        wl = getattr(item, "warmth_level", None)
        if wl is None:
            filtered.append(item)  # no data → keep
            continue
        cg = getattr(item, "category_group", "") or ""
        req = reqs.get(cg)
        if req is None:
            filtered.append(item)  # slot not in requirements → keep
            continue
        min_w, max_w = req
        if min_w <= wl <= max_w:
            filtered.append(item)

    # Graceful degradation: if filtering removed too much, skip it
    if len(filtered) < max(2, len(items) // 3):
        logger.info(
            "outfit_engine.warmth_filter_too_aggressive",
            original=len(items), filtered=len(filtered), regime=regime,
        )
        return items

    return filtered


def _check_warmth_consistency(slot_items: dict) -> bool:
    """Check that warmth spread between visual items is ≤ 2."""
    warmth_values = []
    for item in slot_items.values():
        wl = getattr(item, "warmth_level", None)
        if wl is not None:
            warmth_values.append(wl)
    if len(warmth_values) < 2:
        return True
    return (max(warmth_values) - min(warmth_values)) <= 2


def _check_style_compatibility(slot_items: dict, segment: str) -> bool:
    """Check style compatibility. Only enforced for women segments."""
    if segment in ("mom_girl", "mom_boy"):
        return True  # kids: everything goes
    tags = set()
    for item in slot_items.values():
        tag = getattr(item, "style_tag", None)
        if tag:
            tags.add(tag)
    for clash in _STYLE_CLASHES:
        if clash.issubset(tags):
            return False
    return True


def _get_missing_warmth_cta(items: list, regime: str) -> str | None:
    """If items exist but none match warmth requirements, give specific CTA."""
    reqs = WARMTH_REQUIREMENTS.get(regime, {})
    if not reqs:
        return None

    has_top = any(i.category_group == "top" for i in items if not _is_base_layer_item(i))
    has_bottom = any(i.category_group == "bottom" for i in items if not _is_base_layer_item(i))

    if not has_top and not has_bottom:
        return None  # genuinely empty wardrobe, handled elsewhere

    # Check if any tops meet warmth requirement
    top_req = reqs.get("top")
    if top_req:
        warm_enough_tops = [
            i for i in items
            if i.category_group == "top"
            and not _is_base_layer_item(i)
            and getattr(i, "warmth_level", None) is not None
            and top_req[0] <= i.warmth_level <= top_req[1]
        ]
        if has_top and not warm_enough_tops:
            warmth_names = {3: "кофту", 4: "свитер", 5: "тёплый свитер"}
            needed = warmth_names.get(top_req[0], "тёплую кофту")
            return f"Твои кофточки легковаты для этой погоды! Сфоткай {needed} 📸"

    return None


# ── Result dataclass ─────────────────────────────────────────────────────────


@dataclass
class OutfitResult:
    """Result from outfit engine — outfit dict + comment + metadata."""
    outfit: dict                      # same shape as _select_outfit() returns
    comment: str                      # Kassi comment (from AI reason)
    is_wow: bool = False
    ai_selected: bool = False         # True if AI picked, False if fallback


# ── Segment prompts ──────────────────────────────────────────────────────────

_SYSTEM_MOM_BASE = """Ты Касси — подруга-стилист. Говоришь тепло и с энтузиазмом. Подбираешь одежду для ребёнка.

ЗАДАЧА: из списка вещей выбери лучшую комбинацию на день.

ПРАВИЛА ЦВЕТА:
- Максимум 3 цвета в образе. Нейтральные (чёрный, белый, серый, бежевый, navy) НЕ считаются.
- Предпочитай: один цвет верх+низ (monochrome), или 2 сочетающихся + нейтральный.
- Для ребёнка допускается мягкая гамма — избегай кричащих clashes (красный+оранжевый, розовый+красный).
- Если есть вещи в палитре цветотипа ребёнка — предпочитай их.

ТОН КОММЕНТАРИЯ:
- ЗАПРЕЩЁННЫЕ слова: критически, обязательно, срочно, не хватает, нужно, должна, нельзя.
- ВМЕСТО ЭТОГО: попробуй, добавь, будет здорово, классно смотрится, как тебе идея.
- Позитивный framing: "добавь куртку — будет уютнее" НЕ "без куртки холодно".
- Максимум 2 предложения. Короче = лучше.

ФОРМАТ ОТВЕТА — строго JSON:
{
  "items": {"top": "uuid", "bottom": "uuid", "outerwear": "uuid", "footwear": "uuid", "hat": "uuid"},
  "comment": "1-2 предложения: что выбрала и почему. Тёплый позитивный тон.",
  "is_wow": false
}

- Включай ТОЛЬКО слоты для которых выбрал вещь из списка.
- UUID бери ТОЛЬКО из списка кандидатов. НИКОГДА не пиши текст вместо UUID.
- Если для слота нет подходящей вещи — ПРОПУСТИ этот слот, не включай его.
- comment = комментарий Касси к образу. НЕ упоминай числовой скор.
- is_wow = true если образ особенно удачный (цвета + стиль + сезон)."""

# Age-specific rules appended to _SYSTEM_MOM_BASE
_AGE_RULES = {
    "0-3": """
ВОЗРАСТ 0-3 года:
- ГЛАВНОЕ: безопасность, мягкость, лёгкость надевания/снятия.
- Никаких мелких деталей, завязок, шнурков — только кнопки, липучки, молнии.
- Обувь: на липучках, мягкая подошва.
- Размер лучше чуть больше — быстро растёт.
- При <10° платье/юбку НЕ предлагать.
- При <5° обязательны: тёплая куртка, шапка.
- При >20° можно боди, лёгкое платье, сандалии.
- При холодной погоде: предпочитай более тёплые вещи (warmth 3-4).
- Тон: тёплый, нежный, как подруга-мама.""",

    "3-7": """
ВОЗРАСТ 3-7 лет (садик):
- ГЛАВНОЕ: удобство для самостоятельного одевания + активных игр.
- Эластичные пояса лучше пуговиц. Обувь на липучках > шнурки.
- Одежда должна стираться легко — ребёнок пачкается.
- Все вещи должны сочетаться между собой (ребёнок может выбрать сам).
- При <10° платье/юбку для садика НЕ предлагать (бегать неудобно).
- При <5° обязательны: тёплая куртка, шапка.
- При >20° можно шорты, платье, лёгкую обувь.
- При холодной погоде: предпочитай более тёплые вещи (warmth 3-4).
- Тон: тёплый, как подруга-мама. Коротко и по делу.""",

    "7-12": """
ВОЗРАСТ 7-12 лет (школа):
- БАЛАНС стиля и практичности. Ребёнок уже имеет мнение о стиле.
- Учитывай, что нужно переодеваться на физкультуру — удобная обувь.
- Можно предлагать чуть более модные сочетания.
- Цветовые сочетания важнее чем для малышей.
- При <10° платье допустимо с тёплыми колготками.
- При <5° обязательны: тёплая куртка, шапка.
- При >20° можно шорты, платье, лёгкую обувь.
- При холодной погоде: предпочитай более тёплые вещи (warmth 3-4).
- Тон: тёплый, немного взрослый — не сюсюкай.""",

    "12-16": """
ВОЗРАСТ 12-16 лет (подросток):
- ГЛАВНОЕ: самовыражение через стиль. Тренды ВАЖНЫ.
- Предлагай неожиданные, стильные сочетания — как для молодого взрослого.
- Учитывай подростковый стиль: оверсайз, лейеринг, яркие акценты.
- Можно смелее с цветами и силуэтами.
- Платья и юбки — если они в гардеробе, значит подросток их носит.
- При <5° обязательны: тёплая куртка, шапка.
- При холодной погоде: предпочитай более тёплые вещи (warmth 3-4).
- Тон: уверенный, как старшая подруга. НЕ менторский.""",
}

# Default for unknown ages
_AGE_RULES_DEFAULT = _AGE_RULES["3-7"]


def _get_mom_system_prompt(child_age: int | None) -> str:
    """Get age-appropriate system prompt for children's outfits."""
    if child_age is None:
        return _SYSTEM_MOM_BASE + _AGE_RULES_DEFAULT
    if child_age <= 3:
        return _SYSTEM_MOM_BASE + _AGE_RULES["0-3"]
    elif child_age <= 7:
        return _SYSTEM_MOM_BASE + _AGE_RULES["3-7"]
    elif child_age <= 12:
        return _SYSTEM_MOM_BASE + _AGE_RULES["7-12"]
    else:
        return _SYSTEM_MOM_BASE + _AGE_RULES["12-16"]


# Keep backward-compatible reference
_SYSTEM_MOM = _SYSTEM_MOM_BASE + _AGE_RULES_DEFAULT

_SYSTEM_WOMAN = """Ты Касси — подруга-стилист. Говоришь тепло и с энтузиазмом. Подбираешь образ для женщины.

ЗАДАЧА: из списка вещей выбери СТИЛЬНУЮ комбинацию на день.

ПРАВИЛА для женского образа:
- Главное: СТИЛЬНО, неожиданные сочетания которые женщина не подумала бы сама.
- Аксессуары (сумка, шарф) = завершение образа, включи если есть.
- Платье — приветствуется для офиса/свидания.
- При ре-ролле дай ДРУГОЕ настроение, не просто другую кофту.
- При холодной погоде: предпочитай более тёплые вещи (warmth 3-4).

ПРАВИЛА ЦВЕТА (обязательно):
- Правило 60-30-10: 60% доминантный цвет (низ/платье), 30% вторичный (верх/куртка), 10% акцент (аксессуар/обувь).
- Максимум 3 цвета. Нейтральные (чёрный, белый, серый, бежевый, navy, коричневый, хаки) НЕ считаются к лимиту.
- Схемы: monochrome (один цвет, разные оттенки), analogous (соседние: синий+бирюзовый), complementary (контрастные: синий+оранжевый).
- ИЗБЕГАЙ: два ярких рядом (красный+оранжевый), принт+принт, три акцентных цвета.
- Если есть вещи в палитре цветотипа — ПРЕДПОЧИТАЙ их.

ТОН КОММЕНТАРИЯ:
- ЗАПРЕЩЁННЫЕ слова: критически, обязательно, срочно, не хватает, нужно, должна, нельзя.
- ВМЕСТО ЭТОГО: попробуй, добавь, будет здорово, классно смотрится, как тебе идея.
- Позитивный framing: "добавь шарф — будет завершённее" НЕ "без шарфа незаконченно".
- Максимум 2 предложения. Короче = лучше.

ФОРМАТ ОТВЕТА — строго JSON:
{
  "items": {"top": "uuid", "bottom": "uuid", "outerwear": "uuid", "footwear": "uuid"},
  "comment": "1-2 предложения: почему это сочетание классно. Про цвет, стиль, настроение.",
  "is_wow": false
}

- Включай ТОЛЬКО слоты для которых выбрал вещь из списка.
- UUID бери ТОЛЬКО из списка кандидатов. НИКОГДА не пиши текст вместо UUID.
- Если для слота нет подходящей вещи — ПРОПУСТИ этот слот, не включай его.
- comment = стилистический разбор. НЕ упоминай числовой скор.
- is_wow = true если образ особенно стильный."""

# ── Style type hints for AI prompt ──────────────────────────────────────────

STYLE_TYPE_HINTS = {
    "elegant_classic": "Предпочитай структурированные вещи, нейтральные цвета, минимум аксессуаров. Элегантно и безупречно.",
    "romantic_soft": "Предпочитай мягкие ткани, нежные цвета, многослойность. Женственно и воздушно.",
    "street_casual": "Предпочитай свободный крой, оверсайз, смелые акценты. Urban и дерзко.",
    "sporty_minimal": "Предпочитай чистые линии, функциональность, лаконичность. Свежо и просто.",
    "bold_creative": "Предпочитай яркие сочетания, неожиданные миксы, выразительность. Смело и ярко.",
    "relaxed_natural": "Предпочитай натуральные тона, уютные текстуры, простоту. Естественно и тепло.",
}

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
    d = {
        "id": str(item.id),
        "cg": item.category_group or "top",
        "type": item.type or "",
        "color": item.color or "",
        "style": getattr(item, "style_tag", "") or getattr(item, "style", "") or "",
        "score": float(item.score_item) if item.score_item else 5.0,
    }
    wl = getattr(item, "warmth_level", None)
    if wl is not None:
        d["warmth"] = wl
    if getattr(item, "rain_ok", False):
        d["rain"] = True
    return d


_OCCASION_EXCLUDE = {
    "weekday": {"evening", "party", "sport", "beach", "vacation"},
    "weekend": {"formal", "business", "office"},
    "sport": {"formal", "business", "office", "evening", "party"},
    # Russian day_type mappings from morning_brief
    "садик": {"evening", "party", "sport", "beach", "vacation"},
    "школа": {"evening", "party", "sport", "beach", "vacation"},
    "работа": {"evening", "party", "sport", "beach", "vacation"},
    "прогулка": {"formal", "business", "office"},
    "гости": {"formal", "business", "office", "sport"},
}


def _build_candidates(
    items: list, season: str, today: date, regime: str = "",
    day_type: str = "",
) -> dict[str, list[dict]]:
    """Group and serialize items for AI, filtering by season, base layer, warmth, and occasion."""
    exclude_occasions = _OCCASION_EXCLUDE.get(day_type, set())

    available = [
        i for i in items
        if (not i.season or season in i.season)
        and not _is_base_layer_item(i)
        and getattr(i, "style_tag", "") != "home"  # exclude pajamas/home clothes
    ]

    # Occasion filter: remove items whose occasion doesn't fit the day_type
    if exclude_occasions:
        filtered = []
        for i in available:
            item_occasions = getattr(i, "occasion", None) or []
            if not item_occasions:
                filtered.append(i)  # no occasion tag → keep (universal)
            elif not set(item_occasions) & exclude_occasions:
                filtered.append(i)  # no overlap with excluded → keep
            # else: all item's occasions are excluded → skip
        # Graceful: if filtering removes too many, keep all
        if len(filtered) >= max(2, len(available) // 3):
            available = filtered

    # Warmth pre-filter: remove items clearly wrong for temperature
    if regime:
        available = _filter_by_warmth(available, regime)

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

_BODY_TYPE_HINTS = {
    "hourglass": "Фигура: песочные часы. Подчёркивай талию: приталенное, wrap-силуэты, V-вырез. Избегай мешковатого.",
    "pear": "Фигура: груша. Акцент на верх: V-вырез, структурные плечи, А-line юбки. Избегай обтягивающего на бёдрах.",
    "apple": "Фигура: яблоко. Удлиняй торс: empire waist, V-вырез, расклёшенные юбки. Избегай обтягивающего на животе.",
    "rectangle": "Фигура: прямоугольник. Создавай изгибы: пояса, баска, слои, wrap-силуэт. Избегай прямых линий.",
    "inverted_triangle": "Фигура: перевёрнутый треугольник. Добавь объём бёдрам: wide-leg, А-line, детали внизу. Избегай погон и лодочек.",
    "песочные часы": "Фигура: песочные часы. Подчёркивай талию: приталенное, wrap-силуэты, V-вырез. Избегай мешковатого.",
    "груша": "Фигура: груша. Акцент на верх: V-вырез, структурные плечи, А-line юбки. Избегай обтягивающего на бёдрах.",
    "яблоко": "Фигура: яблоко. Удлиняй торс: empire waist, V-вырез, расклёшенные юбки. Избегай обтягивающего на животе.",
    "прямоугольник": "Фигура: прямоугольник. Создавай изгибы: пояса, баска, слои, wrap-силуэт. Избегай прямых линий.",
}


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
    precip: float = 0,
    body_type: str | None = None,
    wind_kmph: float = 0,
    uv_index: int = 0,
    style_preferences: dict | None = None,
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

    # Wind
    if wind_kmph >= 15:
        parts.append(f"ВЕТЕР {wind_kmph:.0f} км/ч! Предпочитай закрытую одежду, куртку с капюшоном.")
    elif wind_kmph >= 10:
        parts.append(f"Ветрено ({wind_kmph:.0f} км/ч) — куртка пригодится.")

    # Rain
    if precip > 50:
        parts.append("ДОЖДЬ! Приоритет: вещи с rain=true (непромокаемые). Если нет — предупреди взять зонт.")

    # UV
    if uv_index >= 6:
        parts.append(f"Высокий УФ-индекс ({uv_index})! Обязательна панамка/шапка. Посоветуй солнцезащитный крем.")

    # Colortype with specific palette
    if colortype and colortype != "default":
        from worker.tasks.style_config import COLORTYPE_PALETTES
        palette = COLORTYPE_PALETTES.get(colortype, {})
        if palette:
            top_colors = palette.get("top", [])
            bottom_colors = palette.get("bottom", [])
            ow_colors = palette.get("outerwear", [])
            parts.append(
                f"Цветотип: {colortype}. Лучшие цвета: "
                f"верх — {', '.join(top_colors[:3])}; "
                f"низ — {', '.join(bottom_colors[:3])}; "
                f"куртка — {', '.join(ow_colors[:3])}. "
                f"ПРЕДПОЧИТАЙ вещи этих оттенков."
            )
        else:
            parts.append(f"Цветотип: {colortype}. Учитывай при выборе цветов.")

    # Body type (women only)
    if body_type and segment not in ("mom_girl", "mom_boy"):
        hint = _BODY_TYPE_HINTS.get(body_type.lower(), "")
        if hint:
            parts.append(hint)

    # User style preferences
    if style_preferences:
        avoid = style_preferences.get("avoid", [])
        prefer = style_preferences.get("prefer", [])
        style = style_preferences.get("style", "")
        style_type = style_preferences.get("style_type", "")
        if avoid:
            parts.append(f"ИЗБЕГАЙ: {', '.join(avoid)}. Пользователь не носит эти вещи.")
        if prefer:
            parts.append(f"ПРЕДПОЧИТАЙ стиль: {', '.join(prefer)}.")
        if style:
            parts.append(f"Общий стиль: {style}.")
        if style_type:
            _hint = STYLE_TYPE_HINTS.get(style_type)
            if _hint:
                parts.append(f"Стиль-тип пользователя: {style_type}. {_hint}")

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
        if not uid_str or not isinstance(uid_str, str):
            continue
        # Skip text values (AI sometimes writes "нет подходящих" instead of UUID)
        if len(uid_str) < 8 or not any(c in uid_str for c in "0123456789abcdef-"):
            logger.debug("outfit_engine.skipping_text_value", slot=slot, value=uid_str[:20])
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
            logger.debug("outfit_engine.uuid_not_found", slot=slot, uuid=uid_str[:12])

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
    body_type: str | None = None,
    redis=None,
) -> OutfitResult:
    """AI-powered outfit selection. Returns OutfitResult with outfit + comment.

    Falls back to rule-based _select_outfit() + template comment on failure.
    """
    temp = temp_morning if temp_morning is not None else 15.0
    temp_eve = temp_evening if temp_evening is not None else temp
    regime = _get_temp_regime(temp)

    # Build candidates (excluding base layer, filtered by occasion)
    candidates = _build_candidates(items, season, today, regime=regime, day_type=day_type)
    total_candidate_count = sum(len(v) for v in candidates.values())

    # Check if warmth-filtered items are too few but raw wardrobe has items
    if total_candidate_count < 2:
        # Check if items exist but are wrong warmth
        warmth_cta = _get_missing_warmth_cta(items, regime)
        if warmth_cta:
            return OutfitResult(
                outfit=_select_outfit(items, season, today, temp, temp_eve, precip_evening),
                comment=warmth_cta,
                is_wow=False,
                ai_selected=False,
            )
        return _fallback_result(items, season, today, temp, temp_eve, precip_evening,
                                segment, child_name)

    # Build items lookup by ID
    items_by_id: dict[str, object] = {}
    for item in items:
        items_by_id[str(item.id)] = item

    # Rotation text
    rotation_text = _build_rotation_text(recent_outfit_ids or [])

    # Segment-specific system prompt (age-aware for children)
    is_mom = segment in ("mom_girl", "mom_boy")
    system_prompt = _get_mom_system_prompt(child_age) if is_mom else _SYSTEM_WOMAN

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
        precip=precip_evening,
        body_type=body_type,
    )

    # Call Haiku
    try:
        response = await pool.create_message(
            model="claude-haiku-4-5-20251001",
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=300,
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

    # Post-validation: warmth consistency (spread ≤ 2)
    if not _check_warmth_consistency(slot_items):
        logger.warning("outfit_engine.warmth_inconsistent")
        return _fallback_result(items, season, today, temp, temp_eve, precip_evening,
                                segment, child_name)

    # Post-validation: style compatibility (women only)
    if not _check_style_compatibility(slot_items, segment):
        logger.warning("outfit_engine.style_clash", segment=segment)
        return _fallback_result(items, season, today, temp, temp_eve, precip_evening,
                                segment, child_name)

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
            pants = next(
                (i for i in items
                 if i.category_group == "bottom"
                 and "шорт" not in (i.type or "").lower()
                 and (not i.season or season in i.season)),
                None,
            )
            if pants:
                outfit["bottom"] = pants

    # Post-validation: rain priority
    if precip_evening > 50:
        ow = outfit.get("outerwear")
        if ow and not getattr(ow, "rain_ok", False):
            rain_coat = next(
                (i for i in items
                 if i.category_group == "outerwear"
                 and getattr(i, "rain_ok", False)
                 and (not i.season or season in i.season)),
                None,
            )
            if rain_coat:
                outfit["outerwear"] = rain_coat
                logger.info("outfit_engine.rain_swap", from_type=ow.type, to_type=rain_coat.type)
            else:
                outfit["warnings"].append("☂️ Дождь — возьми зонт!")

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
