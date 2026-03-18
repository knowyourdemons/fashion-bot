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


# Скоринг образа (взрослые)
OUTFIT_SCORE_WEIGHTS_ADULT = {
    "technical": {
        "color_harmony": 2,
        "style_unity": 2,
        "colortype_outfit": 2,
        "seasonality": 1,
        "occasion_fit": 1,
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

OUTFIT_MAX_ADULT = 23  # нормируем в 10
WOW_THRESHOLD = {"transformation": 3, "unexpected_combination": 2}

OUTFIT_SCORE_WEIGHTS_CHILD = {
    "color_harmony": 2,
    "practicality_outfit": 2,
    "age_appropriateness": 2,
    "weather_fit": 2,
    "style_unity": 1,
    "variety": 1,
}
OUTFIT_MAX_CHILD = 10


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
