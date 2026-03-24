"""Infrastructure tests — Phase 1: Redis singleton, health check, ONNX safety, DB indexes."""
import asyncio
import threading
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Redis singleton ──────────────────────────────────────────────────────────

class TestRedisSingleton:
    """core.redis module must provide a single shared connection."""

    def test_get_redis_raises_before_init(self):
        """get_redis() raises RuntimeError if init_redis() was not called."""
        import core.redis as mod
        old = mod._client
        mod._client = None
        try:
            with pytest.raises(RuntimeError, match="not initialized"):
                mod.get_redis()
        finally:
            mod._client = old

    @pytest.mark.asyncio
    async def test_init_redis_returns_client(self):
        """init_redis() creates and returns a Redis client."""
        with patch("core.redis.aioredis") as mock_aioredis:
            mock_client = AsyncMock()
            mock_aioredis.from_url.return_value = mock_client

            import core.redis as mod
            old = mod._client
            mod._client = None
            try:
                result = await mod.init_redis()
                assert result is mock_client
                mock_aioredis.from_url.assert_called_once()
            finally:
                mod._client = old

    @pytest.mark.asyncio
    async def test_init_redis_idempotent(self):
        """Calling init_redis() twice returns the same client."""
        with patch("core.redis.aioredis") as mock_aioredis:
            mock_client = AsyncMock()
            mock_aioredis.from_url.return_value = mock_client

            import core.redis as mod
            old = mod._client
            mod._client = None
            try:
                c1 = await mod.init_redis()
                c2 = await mod.init_redis()
                assert c1 is c2
                assert mock_aioredis.from_url.call_count == 1
            finally:
                mod._client = old

    def test_no_from_url_in_worker_tasks(self):
        """No aioredis.from_url() calls in worker tasks (should use get_redis)."""
        import pathlib
        tasks_dir = pathlib.Path("worker/tasks")
        for f in tasks_dir.glob("*.py"):
            content = f.read_text()
            assert "from_url" not in content, (
                f"{f.name} still contains from_url — use get_redis() instead"
            )

    def test_no_from_url_in_handlers(self):
        """No aioredis.from_url() calls in bot handlers."""
        import pathlib
        handlers_dir = pathlib.Path("bot/handlers")
        for f in handlers_dir.glob("*.py"):
            content = f.read_text()
            assert "from_url" not in content, (
                f"{f.name} still contains from_url — use get_redis() instead"
            )


# ── Health check ─────────────────────────────────────────────────────────────

class TestHealthCheck:
    """Health endpoint must verify real dependencies."""

    def test_health_endpoint_exists(self):
        """create_app() registers /health route."""
        from api.app import create_app
        app = create_app()
        routes = [r.path for r in app.routes]
        assert "/health" in routes


# ── ONNX thread safety ──────────────────────────────────────────────────────

class TestOnnxThreadSafety:
    """ONNX session initialization must be thread-safe."""

    def test_get_rmbg_session_uses_lock(self):
        """_rmbg_lock exists for thread-safe session init."""
        from services.image_processor import _rmbg_lock
        assert isinstance(_rmbg_lock, type(threading.Lock()))

    def test_run_rmbg14_import(self):
        """_run_rmbg14 is importable."""
        from services.image_processor import _run_rmbg14
        assert callable(_run_rmbg14)


# ── DB indexes ───────────────────────────────────────────────────────────────

class TestDbIndexes:
    """Critical indexes must exist in migration."""

    def test_migration_file_exists(self):
        """Index migration file exists."""
        import pathlib
        p = pathlib.Path("db/migrations/versions/c3d4e5f6a7b8_add_critical_indexes.py")
        assert p.exists()

    def test_migration_creates_indexes(self):
        """Migration creates all required indexes."""
        import pathlib
        content = pathlib.Path(
            "db/migrations/versions/c3d4e5f6a7b8_add_critical_indexes.py"
        ).read_text()
        for idx in [
            "ix_wardrobe_items_owner",
            "ix_children_user_id",
            "ix_brief_log_user_date",
            "ix_outfit_log_user_date",
            "ix_events_user_id",
            "ix_users_active_onboarded",
        ]:
            assert idx in content, f"Missing index: {idx}"

    def test_wardrobe_index_is_partial(self):
        """Wardrobe items index filters deleted_at IS NULL."""
        import pathlib
        content = pathlib.Path(
            "db/migrations/versions/c3d4e5f6a7b8_add_critical_indexes.py"
        ).read_text()
        assert "deleted_at IS NULL" in content


# ── Integration: DB indexes exist in live DB ────────────────────────────────

class TestDbIndexesLive:
    """Verify indexes exist in actual PostgreSQL (runs in Docker only)."""

    @pytest.mark.asyncio
    async def test_indexes_exist_in_db(self):
        """All critical indexes present in pg_indexes."""
        try:
            from sqlalchemy import text
            from db.base import AsyncReadSession
        except Exception:
            pytest.skip("DB not available")

        expected = {
            "ix_wardrobe_items_owner",
            "ix_children_user_id",
            "ix_brief_log_user_date",
            "ix_outfit_log_user_date",
            "ix_events_user_id",
            "ix_users_active_onboarded",
        }
        try:
            async with AsyncReadSession() as session:
                result = await session.execute(
                    text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
                )
                existing = {row[0] for row in result.fetchall()}
        except Exception:
            pytest.skip("DB connection failed")

        missing = expected - existing
        assert not missing, f"Missing indexes in DB: {missing}"
