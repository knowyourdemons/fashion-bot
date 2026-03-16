"""
Dev seed: тестовые данные (только ENVIRONMENT=dev).
Запуск: python -m db.seeds.dev_seed
"""
import asyncio
from datetime import date

from sqlalchemy import select

from config import settings
from db.base import AsyncWriteSession
from db.models.user import User
from db.models.child import Child
from db.models.wardrobe import WardrobeItem


async def seed() -> None:
    if settings.environment != "dev":
        print("Dev seed пропущен: ENVIRONMENT != dev")
        return

    async with AsyncWriteSession() as session:
        # Проверяем, есть ли уже тестовый юзер
        existing = await session.execute(
            select(User).where(User.telegram_id == 195169)
        )
        if existing.scalar_one_or_none():
            print("Dev seed: пользователь уже существует, пропускаем.")
            return

        # Создаём пользователя
        user = User(
            telegram_id=195169,
            name="Стас",
            city="Вильнюс",
            timezone="Europe/Vilnius",
            plan="premium",
            segment="mom_girl",
            onboarding_completed=True,
        )
        session.add(user)
        await session.flush()

        # Создаём ребёнка
        child = Child(
            user_id=user.id,
            name="Алиса Мария",
            birthdate=date(2022, 12, 19),
            gender="girl",
            colortype="Лето",
            shoe_size=27,
            current_size="92",
        )
        session.add(child)
        await session.flush()

        # 8 вещей гардероба
        items_data = [
            {
                "owner_id": child.id,
                "owner_type": "child",
                "category_group": "top",
                "category_code": "top.tshirt",
                "type": "футболка",
                "color": "белый",
                "style": "casual",
                "season": ["spring", "summer"],
                "occasion": ["everyday"],
                "photo_id": "dev_photo_1",
                "condition": "хорошая",
            },
            {
                "owner_id": child.id,
                "owner_type": "child",
                "category_group": "bottom",
                "category_code": "bottom.jeans",
                "type": "джинсы",
                "color": "синий",
                "style": "casual",
                "season": ["spring", "autumn"],
                "occasion": ["everyday"],
                "photo_id": "dev_photo_2",
                "condition": "хорошая",
            },
            {
                "owner_id": child.id,
                "owner_type": "child",
                "category_group": "outerwear",
                "category_code": "outerwear.jacket.down",
                "type": "пуховик",
                "color": "розовый",
                "style": "casual",
                "season": ["winter"],
                "occasion": ["everyday"],
                "photo_id": "dev_photo_3",
                "condition": "новая",
            },
            {
                "owner_id": child.id,
                "owner_type": "child",
                "category_group": "footwear",
                "category_code": "footwear.sneakers",
                "type": "кроссовки",
                "color": "белый",
                "style": "sport",
                "season": ["spring", "summer", "autumn"],
                "occasion": ["everyday", "sport"],
                "photo_id": "dev_photo_4",
                "condition": "хорошая",
            },
            {
                "owner_id": child.id,
                "owner_type": "child",
                "category_group": "one_piece",
                "category_code": "one_piece.dress.casual",
                "type": "платье",
                "color": "жёлтый",
                "style": "casual",
                "season": ["spring", "summer"],
                "occasion": ["everyday", "party"],
                "photo_id": "dev_photo_5",
                "condition": "новая",
            },
            {
                "owner_id": child.id,
                "owner_type": "child",
                "category_group": "top",
                "category_code": "top.sweater",
                "type": "свитер",
                "color": "бежевый",
                "style": "casual",
                "season": ["autumn", "winter"],
                "occasion": ["everyday"],
                "photo_id": "dev_photo_6",
                "condition": "хорошая",
            },
            {
                "owner_id": child.id,
                "owner_type": "child",
                "category_group": "accessory",
                "category_code": "accessory.hat",
                "type": "шапка",
                "color": "красный",
                "style": "casual",
                "season": ["winter"],
                "occasion": ["everyday"],
                "photo_id": "dev_photo_7",
                "condition": "хорошая",
            },
            {
                "owner_id": child.id,
                "owner_type": "child",
                "category_group": "footwear",
                "category_code": "footwear.boots.knee",
                "type": "сапоги",
                "color": "коричневый",
                "style": "casual",
                "season": ["autumn", "winter"],
                "occasion": ["everyday"],
                "photo_id": "dev_photo_8",
                "condition": "ношеная",
            },
        ]

        for data in items_data:
            session.add(WardrobeItem(**data))

        await session.commit()
        print(
            f"Dev seed: создан пользователь telegram_id=195169, "
            f"ребёнок 'Алиса Мария', 8 вещей гардероба."
        )


if __name__ == "__main__":
    asyncio.run(seed())
