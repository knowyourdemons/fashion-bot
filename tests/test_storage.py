"""Tests for storage providers: BaseStorage, R2Storage, TelegramStorage."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest


# ---------------------------------------------------------------------------
# 1. BaseStorage cannot be instantiated
# ---------------------------------------------------------------------------

class TestBaseStorage:
    def test_cannot_instantiate(self):
        from services.storage.base import BaseStorage
        with pytest.raises(TypeError):
            BaseStorage()

    def test_subclass_must_implement_all(self):
        from services.storage.base import BaseStorage

        class Incomplete(BaseStorage):
            pass

        with pytest.raises(TypeError):
            Incomplete()

    def test_subclass_with_all_methods_ok(self):
        from services.storage.base import BaseStorage

        class Complete(BaseStorage):
            async def get_photo(self, photo_id: str) -> bytes:
                return b""

            async def upload_photo(self, photo_bytes: bytes, filename: str) -> str:
                return ""

            async def delete_photo(self, photo_id: str) -> None:
                pass

        obj = Complete()
        assert obj is not None


# ---------------------------------------------------------------------------
# R2Storage helpers
# ---------------------------------------------------------------------------

def _make_r2(mock_client, bucket="test-bucket", cdn="https://cdn.example.com"):
    """Create R2Storage with mocked boto3 client and settings."""
    with patch("services.storage.r2_storage._make_client", return_value=mock_client), \
         patch("services.storage.r2_storage.settings") as mock_settings:
        mock_settings.cloudflare_r2_bucket = bucket
        mock_settings.cloudflare_r2_cdn_url = cdn
        from services.storage.r2_storage import R2Storage
        storage = R2Storage()
    # Also patch settings for get_public_url (reads settings at call time)
    storage._settings_cdn = cdn
    return storage


# ---------------------------------------------------------------------------
# 2-8. R2Storage
# ---------------------------------------------------------------------------

class TestR2Storage:
    def _make(self):
        mock_client = MagicMock()
        storage = _make_r2(mock_client)
        return storage, mock_client

    @pytest.mark.asyncio
    async def test_upload_photo_returns_key_with_owner(self):
        storage, mock_client = self._make()
        key = await storage.upload_photo(b"img", "shirt.jpg", owner_id="u123")
        assert key == "wardrobe/u123/shirt.jpg"

    @pytest.mark.asyncio
    async def test_upload_photo_returns_key_without_owner(self):
        storage, mock_client = self._make()
        key = await storage.upload_photo(b"img", "shirt.jpg")
        assert key == "wardrobe/shirt.jpg"

    @pytest.mark.asyncio
    async def test_upload_photo_calls_put_object(self):
        storage, mock_client = self._make()
        await storage.upload_photo(b"data", "f.jpg", owner_id="o1", content_type="image/png")
        mock_client.put_object.assert_called_once_with(
            Bucket="test-bucket",
            Key="wardrobe/o1/f.jpg",
            Body=b"data",
            ContentType="image/png",
        )

    @pytest.mark.asyncio
    async def test_get_photo_returns_bytes(self):
        storage, mock_client = self._make()
        body_mock = MagicMock()
        body_mock.read.return_value = b"photo-bytes"
        mock_client.get_object.return_value = {"Body": body_mock}

        result = await storage.get_photo("wardrobe/u1/a.jpg")
        assert result == b"photo-bytes"
        mock_client.get_object.assert_called_once_with(
            Bucket="test-bucket", Key="wardrobe/u1/a.jpg"
        )

    @pytest.mark.asyncio
    async def test_delete_photo_calls_delete_object(self):
        storage, mock_client = self._make()
        await storage.delete_photo("wardrobe/u1/a.jpg")
        mock_client.delete_object.assert_called_once_with(
            Bucket="test-bucket", Key="wardrobe/u1/a.jpg"
        )

    def test_get_public_url_formats_correctly(self):
        storage, _ = self._make()
        with patch("services.storage.r2_storage.settings") as s:
            s.cloudflare_r2_cdn_url = "https://cdn.example.com"
            url = storage.get_public_url("wardrobe/u1/a.jpg")
        assert url == "https://cdn.example.com/wardrobe/u1/a.jpg"

    def test_get_public_url_strips_trailing_slash(self):
        storage, _ = self._make()
        with patch("services.storage.r2_storage.settings") as s:
            s.cloudflare_r2_cdn_url = "https://cdn.example.com/"
            url = storage.get_public_url("wardrobe/u1/a.jpg")
        assert url == "https://cdn.example.com/wardrobe/u1/a.jpg"

    def test_test_connection_returns_true(self):
        storage, mock_client = self._make()
        mock_client.head_bucket.return_value = {}
        assert storage.test_connection() is True

    def test_test_connection_returns_false_on_error(self):
        storage, mock_client = self._make()
        mock_client.head_bucket.side_effect = Exception("boom")
        assert storage.test_connection() is False

    @pytest.mark.asyncio
    async def test_upload_uses_run_in_executor(self):
        storage, mock_client = self._make()
        loop = asyncio.get_event_loop()
        with patch.object(loop, "run_in_executor", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = None
            await storage.upload_photo(b"x", "f.jpg")
            mock_exec.assert_called_once()
            # First arg is executor (None), second is the lambda
            assert mock_exec.call_args[0][0] is None

    @pytest.mark.asyncio
    async def test_get_photo_uses_run_in_executor(self):
        storage, mock_client = self._make()
        body_mock = MagicMock()
        body_mock.read.return_value = b"data"
        loop = asyncio.get_event_loop()
        with patch.object(loop, "run_in_executor", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = {"Body": body_mock}
            result = await storage.get_photo("k")
            mock_exec.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_presigned_url(self):
        storage, mock_client = self._make()
        mock_client.generate_presigned_url.return_value = "https://presigned.example.com/obj?sig=abc"
        url = await storage.generate_presigned_url("wardrobe/u1/a.jpg", ttl=600)
        assert url == "https://presigned.example.com/obj?sig=abc"
        mock_client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "test-bucket", "Key": "wardrobe/u1/a.jpg"},
            ExpiresIn=600,
        )

    @pytest.mark.asyncio
    async def test_generate_presigned_url_default_ttl(self):
        storage, mock_client = self._make()
        mock_client.generate_presigned_url.return_value = "https://url"
        await storage.generate_presigned_url("k")
        _, kwargs = mock_client.generate_presigned_url.call_args
        # Default TTL is passed as positional — check ExpiresIn
        call_args = mock_client.generate_presigned_url.call_args
        assert call_args[1].get("ExpiresIn", call_args[0][2] if len(call_args[0]) > 2 else None) == 3600 or \
               mock_client.generate_presigned_url.call_args == (
                   ("get_object",),
                   {"Params": {"Bucket": "test-bucket", "Key": "k"}, "ExpiresIn": 3600},
               )


# ---------------------------------------------------------------------------
# 12. Singleton get_r2_storage
# ---------------------------------------------------------------------------

class TestR2StorageSingleton:
    def test_get_r2_storage_returns_same_instance(self):
        with patch("services.storage.r2_storage._make_client", return_value=MagicMock()), \
             patch("services.storage.r2_storage.settings") as s:
            s.cloudflare_r2_bucket = "b"
            s.cloudflare_r2_cdn_url = "https://cdn"
            import services.storage.r2_storage as mod
            mod._r2 = None  # Reset singleton
            a = mod.get_r2_storage()
            b = mod.get_r2_storage()
            assert a is b
            mod._r2 = None  # Cleanup


# ---------------------------------------------------------------------------
# 9-11. TelegramStorage
# ---------------------------------------------------------------------------

class TestTelegramStorage:
    @pytest.mark.asyncio
    async def test_get_photo_downloads_file(self):
        mock_bot = AsyncMock()
        mock_file = AsyncMock()
        mock_file.download_as_bytearray.return_value = bytearray(b"photo-data")
        mock_bot.get_file.return_value = mock_file

        from services.storage.telegram_storage import TelegramStorage
        storage = TelegramStorage(bot=mock_bot)
        result = await storage.get_photo("file_id_123")

        mock_bot.get_file.assert_awaited_once_with("file_id_123")
        mock_file.download_as_bytearray.assert_awaited_once()
        assert result == bytearray(b"photo-data")

    @pytest.mark.asyncio
    async def test_upload_photo_raises_not_implemented(self):
        mock_bot = AsyncMock()
        from services.storage.telegram_storage import TelegramStorage
        storage = TelegramStorage(bot=mock_bot)

        with pytest.raises(NotImplementedError):
            await storage.upload_photo(b"data", "f.jpg")

    @pytest.mark.asyncio
    async def test_delete_photo_is_noop(self):
        mock_bot = AsyncMock()
        from services.storage.telegram_storage import TelegramStorage
        storage = TelegramStorage(bot=mock_bot)

        # Should not raise, should not call anything on bot
        await storage.delete_photo("file_id_123")
        mock_bot.delete_file.assert_not_called()

    def test_telegram_storage_is_base_storage_subclass(self):
        from services.storage.base import BaseStorage
        from services.storage.telegram_storage import TelegramStorage
        assert issubclass(TelegramStorage, BaseStorage)
