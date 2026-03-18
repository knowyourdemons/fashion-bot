"""
Cloudflare R2 storage через boto3 (S3-compatible API).
"""
import io
import uuid
from typing import Optional

import boto3
from botocore.config import Config
import structlog

from config import settings
from services.storage.base import BaseStorage

logger = structlog.get_logger()


def _make_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.cloudflare_r2_endpoint,
        aws_access_key_id=settings.cloudflare_r2_access_key,
        aws_secret_access_key=settings.cloudflare_r2_secret_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


class R2Storage(BaseStorage):
    def __init__(self) -> None:
        self._client = _make_client()
        self._bucket = settings.cloudflare_r2_bucket

    async def get_photo(self, photo_key: str) -> bytes:
        """Скачивает фото из R2 по ключу (r2_key)."""
        import asyncio
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self._client.get_object(Bucket=self._bucket, Key=photo_key)
        )
        return response["Body"].read()

    async def upload_photo(self, photo_bytes: bytes, filename: str, owner_id: str = "", content_type: str = "image/jpeg") -> str:
        """Загружает фото в R2. Возвращает r2_key."""
        import asyncio
        key = f"wardrobe/{owner_id}/{filename}" if owner_id else f"wardrobe/{filename}"
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=photo_bytes,
                ContentType=content_type,
            )
        )
        logger.info("r2.uploaded", key=key, size=len(photo_bytes))
        return key

    def get_public_url(self, key: str) -> str:
        """Возвращает публичный CDN URL для ключа."""
        cdn = settings.cloudflare_r2_cdn_url.rstrip("/")
        return f"{cdn}/{key}"

    async def delete_photo(self, photo_key: str) -> None:
        import asyncio
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self._client.delete_object(Bucket=self._bucket, Key=photo_key)
        )

    async def generate_presigned_url(self, photo_key: str, ttl: int = 3600) -> str:
        import asyncio
        loop = asyncio.get_event_loop()
        url = await loop.run_in_executor(
            None,
            lambda: self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": photo_key},
                ExpiresIn=ttl,
            )
        )
        return url

    def test_connection(self) -> bool:
        """Проверяет подключение к R2."""
        try:
            self._client.head_bucket(Bucket=self._bucket)
            return True
        except Exception as e:
            logger.error("r2.connection_failed", error=str(e))
            return False


# Singleton
_r2: Optional[R2Storage] = None

def get_r2_storage() -> R2Storage:
    global _r2
    if _r2 is None:
        _r2 = R2Storage()
    return _r2
