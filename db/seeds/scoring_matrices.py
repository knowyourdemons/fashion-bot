"""Seed scoring matrices into DB."""
import structlog
from sqlalchemy import select

from db.base import AsyncWriteSession, AsyncReadSession
from db.models.scoring_matrix import ScoringMatrix

logger = structlog.get_logger()

_MATRICES = [
    {
        "name": "0-3",
        "age_from": 0, "age_to": 3, "gender": "all", "is_pregnant": False,
        "max_score": 30, "version": "v2.0",
        "criteria": {
            "safety":           {"weight": 3, "max": 6},
            "practicality":     {"weight": 2, "max": 4},
            "durability":       {"weight": 2, "max": 4},
            "age_authenticity": {"weight": 2, "max": 4},
            "comfort":          {"weight": 1, "max": 2},
            "colortype":        {"weight": 1, "max": 2},
            "ease_of_care":     {"weight": 1, "max": 2},
            "versatility":      {"weight": 1, "max": 2},
            "condition":        {"weight": 1, "max": 2},
            "size_fit_score":   {"weight": 1, "max": 2},
            "seasonality":      {"weight": 1, "max": 2},
            "_wow_condition": "color_harmony=2 AND age_appropriateness=2 AND colortype_child=2",
            "_wow_message": "✨ Стилист одобряет — такой образ встретишь в детском Vogue!",
        },
    },
    {
        "name": "3-7",
        "age_from": 3, "age_to": 7, "gender": "all", "is_pregnant": False,
        "max_score": 34, "version": "v2.0",
        "criteria": {
            "practicality":     {"weight": 3, "max": 6},
            "durability":       {"weight": 2, "max": 4},
            "colortype":        {"weight": 2, "max": 4},
            "age_authenticity": {"weight": 2, "max": 4},
            "comfort":          {"weight": 2, "max": 4},
            "child_preference": {"weight": 1, "max": 2},
            "ease_of_care":     {"weight": 1, "max": 2},
            "versatility":      {"weight": 1, "max": 2},
            "condition":        {"weight": 1, "max": 2},
            "size_fit_score":   {"weight": 1, "max": 2},
            "seasonality":      {"weight": 1, "max": 2},
            "_wow_condition": "color_harmony=2 AND age_appropriateness=2 AND practicality_outfit=2",
            "_wow_message": "✨ Стилист одобряет — такой образ встретишь в детском Vogue!",
        },
    },
    {
        "name": "7-12",
        "age_from": 7, "age_to": 12, "gender": "all", "is_pregnant": False,
        "max_score": 32, "version": "v2.0",
        "criteria": {
            "child_preference": {"weight": 3, "max": 6},
            "practicality":     {"weight": 2, "max": 4},
            "colortype":        {"weight": 2, "max": 4},
            "versatility":      {"weight": 2, "max": 4},
            "durability":       {"weight": 2, "max": 4},
            "style":            {"weight": 1, "max": 2},
            "comfort":          {"weight": 1, "max": 2},
            "condition":        {"weight": 1, "max": 2},
            "size_fit_score":   {"weight": 1, "max": 2},
            "seasonality":      {"weight": 1, "max": 2},
            "_wow_condition": "color_harmony=2 AND style_unity=2 AND weather_fit=2",
            "_wow_message": "✨ Стилист одобряет — такой образ встретишь в детском Vogue!",
        },
    },
    {
        "name": "12-16",
        "age_from": 12, "age_to": 16, "gender": "all", "is_pregnant": False,
        "max_score": 32, "version": "v2.0",
        "criteria": {
            "child_preference": {"weight": 3, "max": 6},
            "individuality":    {"weight": 2, "max": 4},
            "style":            {"weight": 2, "max": 4},
            "colortype":        {"weight": 2, "max": 4},
            "comfort":          {"weight": 2, "max": 4},
            "practicality":     {"weight": 1, "max": 2},
            "trend":            {"weight": 1, "max": 2},
            "condition":        {"weight": 1, "max": 2},
            "versatility":      {"weight": 1, "max": 2},
            "seasonality":      {"weight": 1, "max": 2},
            "_wow_condition": "unexpected_combination=2 AND color_harmony=2 AND style_unity=2",
            "_wow_message": "✨ Стилист одобряет — такой образ встретишь в детском Vogue!",
        },
    },
    {
        "name": "16-25",
        "age_from": 16, "age_to": 25, "gender": "all", "is_pregnant": False,
        "max_score": 26, "version": "v2.0",
        "criteria": {
            "trend":        {"weight": 3, "max": 6},
            "colortype":    {"weight": 2, "max": 4},
            "style_unity":  {"weight": 2, "max": 4},
            "versatility":  {"weight": 1, "max": 2},
            "dress_code":   {"weight": 1, "max": 2},
            "comfort":      {"weight": 1, "max": 2},
            "quality":      {"weight": 1, "max": 2},
            "condition":    {"weight": 1, "max": 2},
            "seasonality":  {"weight": 1, "max": 2},
            "_wow_condition": "unexpected_combination=2 AND modernity=2",
            "_wow_message": "✨ Такой образ обычно предлагают стилисты за $200+",
        },
    },
    {
        "name": "25-35",
        "age_from": 25, "age_to": 35, "gender": "all", "is_pregnant": False,
        "max_score": 26, "version": "v2.0",
        "criteria": {
            "colortype":    {"weight": 2, "max": 4},
            "versatility":  {"weight": 2, "max": 4},
            "quality":      {"weight": 2, "max": 4},
            "dress_code":   {"weight": 2, "max": 4},
            "trend":        {"weight": 1, "max": 2},
            "style_unity":  {"weight": 1, "max": 2},
            "comfort":      {"weight": 1, "max": 2},
            "condition":    {"weight": 1, "max": 2},
            "seasonality":  {"weight": 1, "max": 2},
            "_wow_condition": "unexpected_combination=2 AND modernity=2",
            "_wow_message": "✨ Такой образ обычно предлагают стилисты за $200+",
        },
    },
    {
        "name": "35-45",
        "age_from": 35, "age_to": 45, "gender": "all", "is_pregnant": False,
        "max_score": 30, "version": "v2.0",
        "criteria": {
            "quality":      {"weight": 3, "max": 6},
            "colortype":    {"weight": 2, "max": 4},
            "comfort":      {"weight": 2, "max": 4},
            "dress_code":   {"weight": 2, "max": 4},
            "versatility":  {"weight": 2, "max": 4},
            "style_unity":  {"weight": 1, "max": 2},
            "trend":        {"weight": 1, "max": 2},
            "condition":    {"weight": 1, "max": 2},
            "seasonality":  {"weight": 1, "max": 2},
            "_wow_condition": "unexpected_combination=2 AND modernity=2",
            "_wow_message": "✨ Такой образ обычно предлагают стилисты за $200+",
        },
    },
    {
        "name": "45+",
        "age_from": 45, "age_to": 999, "gender": "all", "is_pregnant": False,
        "max_score": 30, "version": "v2.0",
        "criteria": {
            "comfort":      {"weight": 3, "max": 6},
            "quality":      {"weight": 3, "max": 6},
            "colortype":    {"weight": 2, "max": 4},
            "versatility":  {"weight": 2, "max": 4},
            "dress_code":   {"weight": 2, "max": 4},
            "style_unity":  {"weight": 1, "max": 2},
            "condition":    {"weight": 1, "max": 2},
            "seasonality":  {"weight": 1, "max": 2},
            "_wow_condition": "unexpected_combination=2 AND modernity=2",
            "_wow_message": "✨ Такой образ обычно предлагают стилисты за $200+",
        },
    },
    {
        "name": "pregnant-1",
        "age_from": 0, "age_to": 999, "gender": "all", "is_pregnant": True,
        "max_score": 22, "version": "v2.0",
        "criteria": {
            "comfort":             {"weight": 2, "max": 4},
            "versatility":         {"weight": 2, "max": 4},
            "practicality":        {"weight": 2, "max": 4},
            "post_pregnancy_use":  {"weight": 2, "max": 4},
            "colortype":           {"weight": 1, "max": 2},
            "condition":           {"weight": 1, "max": 2},
            "seasonality":         {"weight": 1, "max": 2},
            "_wow_condition": "color_harmony=2 AND bump_friendly=2",
            "_wow_message": "✨ Прекрасный образ для будущей мамы!",
        },
    },
    {
        "name": "pregnant-2",
        "age_from": 0, "age_to": 999, "gender": "all", "is_pregnant": True,
        "max_score": 28, "version": "v2.0",
        "criteria": {
            "bump_friendly":       {"weight": 3, "max": 6},
            "comfort":             {"weight": 3, "max": 6},
            "practicality":        {"weight": 2, "max": 4},
            "post_pregnancy_use":  {"weight": 2, "max": 4},
            "colortype":           {"weight": 1, "max": 2},
            "versatility":         {"weight": 1, "max": 2},
            "condition":           {"weight": 1, "max": 2},
            "seasonality":         {"weight": 1, "max": 2},
            "_wow_condition": "color_harmony=2 AND bump_friendly=2",
            "_wow_message": "✨ Прекрасный образ для будущей мамы!",
        },
    },
    {
        "name": "pregnant-3",
        "age_from": 0, "age_to": 999, "gender": "all", "is_pregnant": True,
        "max_score": 26, "version": "v2.0",
        "criteria": {
            "comfort":             {"weight": 4, "max": 8},
            "bump_friendly":       {"weight": 3, "max": 6},
            "practicality":        {"weight": 2, "max": 4},
            "post_pregnancy_use":  {"weight": 1, "max": 2},
            "colortype":           {"weight": 1, "max": 2},
            "condition":           {"weight": 1, "max": 2},
            "seasonality":         {"weight": 1, "max": 2},
            "_wow_condition": "color_harmony=2 AND bump_friendly=2",
            "_wow_message": "✨ Прекрасный образ для будущей мамы!",
        },
    },
]


async def seed_scoring_matrices() -> None:
    """Заполняет таблицу scoring_matrices если она пуста."""
    async with AsyncReadSession() as session:
        result = await session.execute(select(ScoringMatrix).limit(1))
        if result.scalar_one_or_none():
            return  # уже заполнено

    async with AsyncWriteSession() as session:
        for data in _MATRICES:
            session.add(ScoringMatrix(**data))
        await session.commit()

    logger.info("scoring_matrices.seeded", count=len(_MATRICES))
