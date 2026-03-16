"""
Cloudflare R2 storage — заглушка (Фаза 2).
Presigned URLs, TTL=3600.
"""
from services.storage.base import BaseStorage


class R2Storage(BaseStorage):
    """Фаза 2: реализовать через boto3/httpx + Cloudflare R2 API."""

    async def get_photo(self, photo_id: str) -> bytes:
        raise NotImplementedError("R2Storage — Фаза 2")

    async def upload_photo(self, photo_bytes: bytes, filename: str) -> str:
        raise NotImplementedError("R2Storage — Фаза 2")

    async def delete_photo(self, photo_id: str) -> None:
        raise NotImplementedError("R2Storage — Фаза 2")

    async def generate_presigned_url(self, photo_id: str, ttl: int = 3600) -> str:
        """Генерирует presigned URL (Фаза 2)."""
        raise NotImplementedError("R2Storage — Фаза 2")
