"""Абстрактный storage provider."""
from abc import ABC, abstractmethod


class BaseStorage(ABC):
    @abstractmethod
    async def get_photo(self, photo_id: str) -> bytes:
        """Скачивает фото по ID."""

    @abstractmethod
    async def upload_photo(self, photo_bytes: bytes, filename: str) -> str:
        """Загружает фото. Возвращает URL/ID."""

    @abstractmethod
    async def delete_photo(self, photo_id: str) -> None:
        """Удаляет фото."""
