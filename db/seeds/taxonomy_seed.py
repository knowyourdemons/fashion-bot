"""
Seed: полный справочник категорий одежды.
Запуск: python -m db.seeds.taxonomy_seed
"""
import asyncio
from sqlalchemy import select

from db.base import AsyncWriteSession
from db.models.taxonomy import ItemCategory, TaxonomyVersion

# Структура: (code, group, label_ru, parent_code | None, level)
CATEGORIES: list[tuple[str, str, str, str | None, int]] = [
    # Верхняя одежда
    ("outerwear", "outerwear", "Верхняя одежда", None, 0),
    ("outerwear.coat", "outerwear", "Пальто", "outerwear", 1),
    ("outerwear.coat.trench", "outerwear", "Тренч", "outerwear.coat", 2),
    ("outerwear.coat.wool", "outerwear", "Шерстяное пальто", "outerwear.coat", 2),
    ("outerwear.jacket", "outerwear", "Куртка", "outerwear", 1),
    ("outerwear.jacket.down", "outerwear", "Пуховик", "outerwear.jacket", 2),
    ("outerwear.jacket.bomber", "outerwear", "Бомбер", "outerwear.jacket", 2),
    ("outerwear.jacket.denim", "outerwear", "Джинсовая куртка", "outerwear.jacket", 2),
    ("outerwear.jacket.leather", "outerwear", "Кожаная куртка", "outerwear.jacket", 2),
    ("outerwear.jacket.windbreaker", "outerwear", "Ветровка", "outerwear.jacket", 2),
    ("outerwear.vest", "outerwear", "Жилет", "outerwear", 1),
    # Верх
    ("top", "top", "Верх", None, 0),
    ("top.tshirt", "top", "Футболка", "top", 1),
    ("top.shirt", "top", "Рубашка", "top", 1),
    ("top.blouse", "top", "Блузка", "top", 1),
    ("top.sweater", "top", "Свитер", "top", 1),
    ("top.sweater.turtleneck", "top", "Водолазка", "top.sweater", 2),
    ("top.hoodie", "top", "Худи", "top", 1),
    ("top.cardigan", "top", "Кардиган", "top", 1),
    ("top.top", "top", "Топ", "top", 1),
    ("top.crop", "top", "Кроп-топ", "top", 1),
    # Низ
    ("bottom", "bottom", "Низ", None, 0),
    ("bottom.jeans", "bottom", "Джинсы", "bottom", 1),
    ("bottom.trousers", "bottom", "Брюки", "bottom", 1),
    ("bottom.shorts", "bottom", "Шорты", "bottom", 1),
    ("bottom.skirt", "bottom", "Юбка", "bottom", 1),
    ("bottom.skirt.mini", "bottom", "Мини-юбка", "bottom.skirt", 2),
    ("bottom.skirt.midi", "bottom", "Миди-юбка", "bottom.skirt", 2),
    ("bottom.skirt.maxi", "bottom", "Макси-юбка", "bottom.skirt", 2),
    ("bottom.leggings", "bottom", "Леггинсы", "bottom", 1),
    # Цельные образы
    ("one_piece", "one_piece", "Цельные образы", None, 0),
    ("one_piece.dress", "one_piece", "Платье", "one_piece", 1),
    ("one_piece.dress.casual", "one_piece", "Повседневное платье", "one_piece.dress", 2),
    ("one_piece.dress.evening", "one_piece", "Вечернее платье", "one_piece.dress", 2),
    ("one_piece.jumpsuit", "one_piece", "Комбинезон", "one_piece", 1),
    ("one_piece.overalls", "one_piece", "Комбинезон-оверолл", "one_piece", 1),
    # Обувь
    ("footwear", "footwear", "Обувь", None, 0),
    ("footwear.sneakers", "footwear", "Кроссовки", "footwear", 1),
    ("footwear.shoes", "footwear", "Туфли", "footwear", 1),
    ("footwear.shoes.loafers", "footwear", "Лоферы", "footwear.shoes", 2),
    ("footwear.shoes.heels", "footwear", "На каблуке", "footwear.shoes", 2),
    ("footwear.boots", "footwear", "Ботинки", "footwear", 1),
    ("footwear.boots.ankle", "footwear", "Ботильоны", "footwear.boots", 2),
    ("footwear.boots.knee", "footwear", "Сапоги", "footwear.boots", 2),
    ("footwear.sandals", "footwear", "Сандалии", "footwear", 1),
    ("footwear.slippers", "footwear", "Тапочки/мюли", "footwear", 1),
    ("footwear.ugg", "footwear", "Угги", "footwear", 1),
    # Аксессуары
    ("accessory", "accessory", "Аксессуары", None, 0),
    ("accessory.bag", "accessory", "Сумка", "accessory", 1),
    ("accessory.belt", "accessory", "Ремень", "accessory", 1),
    ("accessory.scarf", "accessory", "Шарф/платок", "accessory", 1),
    ("accessory.hat", "accessory", "Головной убор", "accessory", 1),
    ("accessory.jewelry", "accessory", "Украшения", "accessory", 1),
    ("accessory.sunglasses", "accessory", "Очки", "accessory", 1),
    ("accessory.gloves", "accessory", "Перчатки", "accessory", 1),
    # Базовый слой
    ("base_layer", "base_layer", "Базовый слой", None, 0),
    ("base_layer.underwear", "base_layer", "Нижнее бельё", "base_layer", 1),
    ("base_layer.bra", "base_layer", "Бюстгальтер", "base_layer", 1),
    ("base_layer.thermal", "base_layer", "Термобельё", "base_layer", 1),
    ("base_layer.socks", "base_layer", "Носки/колготки", "base_layer", 1),
    # Спортивная одежда
    ("sportswear", "sportswear", "Спортивная одежда", None, 0),
    ("sportswear.leggings", "sportswear", "Спортивные леггинсы", "sportswear", 1),
    ("sportswear.top", "sportswear", "Спортивный топ", "sportswear", 1),
    ("sportswear.jacket", "sportswear", "Спортивная куртка", "sportswear", 1),
    # Для беременных
    ("pregnant_specific", "pregnant_specific", "Для беременных", None, 0),
    ("pregnant_specific.pants", "pregnant_specific", "Брюки для беременных", "pregnant_specific", 1),
    ("pregnant_specific.dress", "pregnant_specific", "Платье для беременных", "pregnant_specific", 1),
    ("pregnant_specific.bra", "pregnant_specific", "Бюстгальтер для кормления", "pregnant_specific", 1),
    # Домашняя/пляжная
    ("home_beach", "home_beach", "Домашняя/пляжная", None, 0),
    ("home_beach.pajamas", "home_beach", "Пижама", "home_beach", 1),
    ("home_beach.swimwear", "home_beach", "Купальник", "home_beach", 1),
    # Особые случаи
    ("special", "special", "Особые случаи", None, 0),
    ("special.costume", "special", "Костюм/образ", "special", 1),
    ("special.uniform", "special", "Форма/спецодежда", "special", 1),
]


async def seed() -> None:
    async with AsyncWriteSession() as session:
        # Создаём версию
        version = TaxonomyVersion(version="v1.0", description="Начальный справочник", is_current=True)
        session.add(version)

        # Индекс code → объект для parent_id
        code_to_obj: dict[str, ItemCategory] = {}

        for i, (code, group, label_ru, parent_code, level) in enumerate(CATEGORIES):
            existing = await session.execute(
                select(ItemCategory).where(ItemCategory.code == code)
            )
            if existing.scalar_one_or_none():
                continue

            parent_id = code_to_obj[parent_code].id if parent_code else None
            item = ItemCategory(
                code=code,
                group=group,
                label_ru=label_ru,
                parent_id=parent_id,
                level=level,
                sort_order=i,
            )
            session.add(item)
            await session.flush()  # получаем id
            code_to_obj[code] = item

        await session.commit()
        print(f"Taxonomy seed: {len(CATEGORIES)} категорий загружено.")


if __name__ == "__main__":
    asyncio.run(seed())
