"""
Коллаж из вещей гардероба.
Фаза 1: заглушка — возвращает None.
Фаза 2: grid 2×2 или 2×3, подписи под каждой вещью.
"""
from typing import Optional


async def build_collage(
    photo_ids: list[str],
    labels: Optional[list[str]] = None,
) -> Optional[bytes]:
    """
    Фаза 1 — заглушка.
    Фаза 2:
    - Скачать фото по photo_id из Telegram
    - Исключить base_layer
    - Включить accessory
    - Собрать grid 2×2 или 2×3
    - Добавить подписи под каждой вещью
    - Вернуть bytes коллажа
    """
    return None
