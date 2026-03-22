"""
Скоринг вещи и образа согласно матрицам из БД.
"""
from datetime import date
from decimal import Decimal
from typing import Any

import redis.asyncio as aioredis
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.models.scoring_matrix import ScoringMatrix
from db.models.wardrobe import WardrobeItem

logger = structlog.get_logger()


# ── Standalone функции скоринга ─────────────────────────────────────────────

def matrix_name_for_owner(user, child=None) -> str:
    """Возвращает имя матрицы по сегменту/возрасту."""
    if child:
        age = (date.today() - child.birthdate).days // 365
        gender = getattr(child, "gender", "girl") or "girl"
        if age < 3:
            return f"0-3-{gender}"
        if age < 7:
            return f"3-7-{gender}"
        if age < 12:
            return f"7-12-{gender}"
        return f"12-16-{gender}"

    if getattr(user, "segment", None) == "pregnant":
        trimester = getattr(user, "trimester", 1) or 1
        return f"pregnant-{trimester}"

    age = getattr(user, "age", None) or 30
    if age < 25:
        return "16-25"
    if age < 35:
        return "25-35"
    if age < 45:
        return "35-45"
    return "45+"


def calc_item_score(breakdown: dict, matrix: ScoringMatrix) -> float:
    """Считает score_item по breakdown (значения 0-2) и матрице.

    Формула: sum(value_i × weight_i) / max_score × 10
    """
    total = 0
    for criterion, weight_info in matrix.criteria.items():
        if criterion.startswith("_"):
            continue
        value = breakdown.get(criterion, 1)
        clamped = max(0, min(int(value), 2))
        total += clamped * weight_info["weight"]
    return round((total / matrix.max_score) * 10, 2)

def classify_role(item_type: str, item_color: str) -> str:
    """Определяет роль вещи в гардеробе: base / accent / statement.

    Включает русские и английские названия — Vision может вернуть любой язык.
    """
    neutral_colors = {
        # русские
        "белый", "чёрный", "серый", "бежевый", "navy", "тёмно-синий", "коричневый",
        # английские
        "white", "black", "gray", "grey", "beige", "dark blue", "dark navy", "brown",
    }
    basic_types = {
        # русские
        "футболка", "джинсы", "брюки", "юбка-карандаш", "рубашка", "водолазка", "лонгслив",
        # английские
        "t-shirt", "tshirt", "jeans", "trousers", "pants", "pencil skirt", "shirt",
        "turtleneck", "longsleeve", "long sleeve",
    }
    statement_types = {
        # русские
        "вечернее платье", "кожаная куртка", "пальто", "шуба",
        # английские
        "evening dress", "gown", "leather jacket", "coat", "fur coat", "overcoat",
    }

    color_lower = (item_color or "").lower()
    type_lower = (item_type or "").lower()

    if any(st in type_lower for st in statement_types):
        return "statement"
    if any(bt in type_lower for bt in basic_types) and any(nc in color_lower for nc in neutral_colors):
        return "base"
    return "accent"


def get_wardrobe_balance_insight(items: list) -> str | None:
    """Генерирует инсайт о балансе гардероба (только при ≥10 вещах с ролью)."""
    from collections import Counter
    roles = Counter(getattr(i, "role", None) for i in items if getattr(i, "role", None))
    base = roles.get("base", 0)
    accent = roles.get("accent", 0)
    statement = roles.get("statement", 0)
    total = base + accent + statement
    if total < 10:
        return None
    if base < total * 0.3:
        return "💡 В гардеробе мало базовых вещей — добавь нейтральный топ или брюки, и акценты заиграют!"
    if accent > total * 0.5:
        return "💡 Много ярких вещей — классно! Но пара нейтральных базовых вещей сделает гардероб ещё гибче"
    return None


# ── Capsule wardrobe analysis ────────────────────────────────────────────────

_COMBINABLE_PAIRS_RAW = [
    ("top", "bottom"), ("top", "one_piece"), ("outerwear", "top"),
    ("outerwear", "bottom"), ("outerwear", "one_piece"),
    ("footwear", "bottom"), ("footwear", "one_piece"), ("footwear", "top"),
    ("accessory", "top"), ("accessory", "outerwear"), ("accessory", "bottom"),
]
# Normalize pairs alphabetically for consistent lookup
_COMBINABLE_PAIRS = set()
for a, b in _COMBINABLE_PAIRS_RAW:
    _COMBINABLE_PAIRS.add((min(a, b), max(a, b)))

_NEUTRAL_COLORS = frozenset([
    "белый", "чёрный", "серый", "бежевый", "navy", "тёмно-синий",
    "коричневый", "хаки", "молочный", "кремовый", "графит",
    "white", "black", "gray", "grey", "beige", "brown", "navy",
    "cream", "khaki", "charcoal", "taupe",
])


def _is_neutral_color(color: str) -> bool:
    if not color:
        return True
    c = color.lower()
    return any(nc in c for nc in _NEUTRAL_COLORS)


def calc_item_versatility(item, all_items: list) -> int:
    """Calculate how many other items this item can pair with.

    A neutral item pairs with everything. Non-neutral pairs with neutrals only.
    Returns count of compatible items (higher = more versatile).
    """
    cg = getattr(item, "category_group", "") or ""
    color = getattr(item, "color", "") or ""
    is_neutral = _is_neutral_color(color)
    count = 0
    for other in all_items:
        if other.id == item.id:
            continue
        other_cg = getattr(other, "category_group", "") or ""
        pair = (min(cg, other_cg), max(cg, other_cg))
        if pair not in _COMBINABLE_PAIRS:
            continue
        other_color = getattr(other, "color", "") or ""
        other_neutral = _is_neutral_color(other_color)
        # Neutrals combine with everything; non-neutrals combine with neutrals
        if is_neutral or other_neutral:
            count += 1
    return count


def get_wardrobe_gaps(items: list, season: str = "") -> list[str]:
    """Identify missing wardrobe categories for a complete capsule.

    Returns list of actionable suggestions.
    """
    from services.outfit_builder import _is_base_layer_item

    # Filter to visual items only
    visual = [i for i in items if not _is_base_layer_item(i)]
    if not visual:
        return ["Гардероб пуст — начни с базовых вещей: футболка, джинсы, кроссовки"]

    cg_counts: dict[str, int] = {}
    for i in visual:
        cg = getattr(i, "category_group", "") or ""
        cg_counts[cg] = cg_counts.get(cg, 0) + 1

    gaps = []

    # Required minimums for a functional capsule
    _MINIMUMS = {
        "top": (3, "верх (футболки, кофты, рубашки)"),
        "bottom": (2, "низ (джинсы, брюки, юбки)"),
        "footwear": (2, "обувь (кроссовки + ботинки/сандалии)"),
        "outerwear": (1, "верхнюю одежду (куртку)"),
    }

    for cg, (minimum, desc) in _MINIMUMS.items():
        actual = cg_counts.get(cg, 0)
        if actual < minimum:
            need = minimum - actual
            gaps.append(f"Добавь ещё {need} шт. {desc}")

    # Orphan detection: items that pair with < 2 others
    if len(visual) >= 8:
        orphans = []
        for i in visual:
            v = calc_item_versatility(i, visual)
            if v < 2:
                orphans.append(f"{i.type} ({i.color})")
        if orphans and len(orphans) <= 3:
            gaps.append(
                f"Одинокие вещи (мало сочетаний): {', '.join(orphans[:3])}. "
                f"Добавь нейтральный верх/низ — они раскроются!"
            )

    # Combo potential
    tops = cg_counts.get("top", 0)
    bottoms = cg_counts.get("bottom", 0)
    one_pieces = cg_counts.get("one_piece", 0)
    outerwear_n = cg_counts.get("outerwear", 0)
    combos = tops * bottoms * max(outerwear_n + 1, 1) + one_pieces
    if combos > 0 and len(visual) >= 5:
        gaps.append(f"Потенциал: ~{combos} комбинаций из {len(visual)} вещей")

    return gaps


# Скоринг образа (взрослые)
OUTFIT_SCORE_WEIGHTS_ADULT = {
    "technical": {
        "color_harmony": 3,        # was 2, elevated — most impactful
        "style_unity": 2,
        "colortype_outfit": 2,
        "seasonality": 1,
        "occasion_fit": 2,         # was 1, elevated — occasion matters
        "body_type_fit": 1,        # NEW: does outfit flatter body type?
    },
    "aesthetic": {
        "unexpected_combination": 2,
        "focal_point": 2,
        "proportions": 2,
        "modernity": 2,
        "transformation": 3,
    },
    "personal": {
        "variety": 1,
        "sleeping_items": 2,
        "capsule_efficiency": 1,
    },
}

OUTFIT_MAX_ADULT = 26  # updated with new criteria
WOW_THRESHOLD = {"transformation": 3, "unexpected_combination": 2}

OUTFIT_SCORE_WEIGHTS_CHILD = {
    "color_harmony": 2,
    "practicality_outfit": 2,
    "age_appropriateness": 2,
    "weather_fit": 2,
    "style_unity": 1,
    "variety": 1,
    "safety": 1,               # NEW: no choking hazards, appropriate fasteners
}
OUTFIT_MAX_CHILD = 11


class ScoringService:
    def __init__(self, session: AsyncSession, redis_client: aioredis.Redis) -> None:
        self._session = session
        self._redis = redis_client

    async def get_matrix(self, name: str) -> ScoringMatrix | None:
        key = f"matrix:cache:{name}"
        cached = await self._redis.get(key)
        if cached:
            import json
            data = json.loads(cached)
            m = ScoringMatrix()
            for k, v in data.items():
                setattr(m, k, v)
            return m

        result = await self._session.execute(
            select(ScoringMatrix).where(
                ScoringMatrix.name == name,
                ScoringMatrix.is_active == True,  # noqa: E712
            )
        )
        matrix = result.scalar_one_or_none()
        if matrix:
            import json
            await self._redis.set(
                key,
                json.dumps({
                    "name": matrix.name,
                    "criteria": matrix.criteria,
                    "max_score": matrix.max_score,
                    "version": matrix.version,
                }),
                ex=3600,
            )
        return matrix

    def score_item(
        self,
        criteria_scores: dict[str, int],
        matrix: ScoringMatrix,
    ) -> tuple[Decimal, dict[str, Any]]:
        """Считает score_item по матрице. Возвращает (score, breakdown)."""
        total = 0
        breakdown: dict[str, Any] = {}

        for criterion, max_weight in matrix.criteria.items():
            given = criteria_scores.get(criterion, 0)
            clamped = max(0, min(given, max_weight))
            breakdown[criterion] = {"given": clamped, "max": max_weight}
            total += clamped

        normalized = round(Decimal(total) / Decimal(matrix.max_score) * 10, 2)
        breakdown["_total"] = total
        breakdown["_max"] = matrix.max_score
        breakdown["_normalized"] = float(normalized)
        return normalized, breakdown

    def score_outfit(
        self,
        criteria_scores: dict[str, int],
        is_child: bool = False,
    ) -> tuple[Decimal, dict[str, Any], bool]:
        """Считает score образа. Возвращает (score_10, breakdown, is_wow)."""
        if is_child:
            total = sum(
                max(0, min(criteria_scores.get(k, 0), w))
                for k, w in OUTFIT_SCORE_WEIGHTS_CHILD.items()
            )
            normalized = round(Decimal(total) / Decimal(OUTFIT_MAX_CHILD) * 10, 2)
            return normalized, {"total": total}, False

        total = 0
        breakdown: dict[str, Any] = {}
        for group, weights in OUTFIT_SCORE_WEIGHTS_ADULT.items():
            group_total = 0
            for k, w in weights.items():
                given = max(0, min(criteria_scores.get(k, 0), w))
                group_total += given
                breakdown[k] = given
            breakdown[f"_{group}_total"] = group_total
            total += group_total

        # Accessory bonus (-1..+2)
        accessory_bonus = max(-1, min(criteria_scores.get("accessory_bonus", 0), 2))
        total += accessory_bonus
        breakdown["accessory_bonus"] = accessory_bonus

        normalized = round(Decimal(total) / Decimal(OUTFIT_MAX_ADULT) * 10, 2)
        breakdown["_total"] = total

        is_wow = (
            criteria_scores.get("transformation", 0) >= WOW_THRESHOLD["transformation"]
            and criteria_scores.get("unexpected_combination", 0) >= WOW_THRESHOLD["unexpected_combination"]
        )

        return normalized, breakdown, is_wow
