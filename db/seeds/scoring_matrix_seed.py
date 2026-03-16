"""
Seed: матрицы скоринга по возрасту/полу.
Запуск: python -m db.seeds.scoring_matrix_seed
"""
import asyncio
from sqlalchemy import select

from db.base import AsyncWriteSession
from db.models.scoring_matrix import ScoringMatrix

MATRICES = [
    {
        "name": "0-3_all",
        "age_from": 0,
        "age_to": 3,
        "gender": "all",
        "is_pregnant": False,
        "max_score": 15,
        "criteria": {
            "safety": 2,
            "practicality": 2,
            "durability": 2,
            "age_authenticity": 2,
            "ease_of_care": 1,
            "colortype": 1,
            "comfort": 1,
            "versatility": 1,
            "condition": 1,
            "size_fit_score": 1,
            "seasonality": 1,
        },
    },
    {
        "name": "3-7_all",
        "age_from": 3,
        "age_to": 7,
        "gender": "all",
        "is_pregnant": False,
        "max_score": 14,
        "criteria": {
            "practicality": 2,
            "colortype": 2,
            "versatility": 2,
            "age_authenticity": 2,
            "ease_of_care": 1,
            "comfort": 1,
            "condition": 1,
            "size_fit_score": 1,
            "seasonality": 1,
            "child_preference": 1,
        },
    },
    {
        "name": "7-12_all",
        "age_from": 7,
        "age_to": 12,
        "gender": "all",
        "is_pregnant": False,
        "max_score": 13,
        "criteria": {
            "style": 2,
            "child_preference": 2,
            "colortype": 2,
            "versatility": 2,
            "trend": 1,
            "condition": 1,
            "ease_of_care": 1,
            "seasonality": 1,
            "size_fit_score": 1,
        },
    },
    {
        "name": "12-16_all",
        "age_from": 12,
        "age_to": 16,
        "gender": "all",
        "is_pregnant": False,
        "max_score": 13,
        "criteria": {
            "trend": 2,
            "child_preference": 2,
            "style": 2,
            "colortype": 2,
            "individuality": 2,
            "condition": 1,
            "seasonality": 1,
            "versatility": 1,
        },
    },
    {
        "name": "adult_woman",
        "age_from": 16,
        "age_to": 99,
        "gender": "all",
        "is_pregnant": False,
        "max_score": 12,
        "criteria": {
            "colortype": 2,
            "trend": 2,
            "dress_code": 2,
            "versatility": 2,
            "condition": 1,
            "seasonality": 1,
            "style_unity": 1,
            "brand_quality": 1,
        },
    },
    {
        "name": "pregnant",
        "age_from": 16,
        "age_to": 99,
        "gender": "all",
        "is_pregnant": True,
        "max_score": 12,
        "criteria": {
            "comfort": 3,
            "practicality": 2,
            "post_pregnancy_use": 2,
            "safety": 1,
            "colortype": 1,
            "versatility": 1,
            "condition": 1,
            "seasonality": 1,
        },
    },
]


async def seed() -> None:
    async with AsyncWriteSession() as session:
        for data in MATRICES:
            existing = await session.execute(
                select(ScoringMatrix).where(ScoringMatrix.name == data["name"])
            )
            if existing.scalar_one_or_none():
                print(f"  skip {data['name']} (already exists)")
                continue

            matrix = ScoringMatrix(**data)
            session.add(matrix)

        await session.commit()
        print(f"Scoring matrix seed: {len(MATRICES)} матриц загружено.")


if __name__ == "__main__":
    asyncio.run(seed())
