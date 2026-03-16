"""
Storage через Telegram file_id.
Фаза 1: хранение только в Telegram (бесплатно).
Фаза 2: миграция на R2.
"""
from telegram import Bot

from services.storage.base import BaseStorage


class TelegramStorage(BaseStorage):
    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def get_photo(self, photo_id: str) -> bytes:
        file = await self._bot.get_file(photo_id)
        return await file.download_as_bytearray()

    async def upload_photo(self, photo_bytes: bytes, filename: str) -> str:
        # В Telegram нельзя загрузить файл без отправки сообщения.
        # Реальная загрузка происходит при отправке фото от пользователя —
        # мы просто сохраняем file_id который Telegram возвращает.
        raise NotImplementedError(
            "TelegramStorage.upload_photo не используется напрямую. "
            "file_id получается из входящего сообщения."
        )

    async def delete_photo(self, photo_id: str) -> None:
        # Telegram не позволяет удалять файлы через API.
        pass
