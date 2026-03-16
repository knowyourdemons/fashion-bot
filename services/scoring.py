"""
Скоринг вещи и образа согласно матрицам из БД.
"""
from decimal import Decimal
from typing import Any

import redis.asyncio as aioredis
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.models.scoring_matrix import ScoringMatrix
from db.models.wardrobe import WardrobeItem

logger = structlog.get_logger()

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
