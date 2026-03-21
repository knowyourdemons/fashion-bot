"""Phase 3 tests — atomic rate limiter, cascade fix, worker concurrency, correlation ID, pool tuning."""
import asyncio
import os
import pathlib
import pytest
from unittest.mock import AsyncMock, MagicMock


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── Atomic rate limiter ──────────────────────────────────────────────────────

class TestAtomicRateLimiter:
    """Rate limiter must use Lua script for atomicity."""

    def test_lua_script_in_code(self):
        content = pathlib.Path("core/rate_limiter.py").read_text()
        assert "_LUA_CHECK_INCR" in content
        assert "register_script" in content
        assert "INCR" in content

    def test_no_get_then_incr_race(self):
        """Old pattern GET→check→INCR must not exist."""
        content = pathlib.Path("core/rate_limiter.py").read_text()
        # Should not have the old racy pattern
        assert "current = await self._redis.get(key)" not in content

    def test_check_api_key_uses_script(self):
        """check_api_key_rpm uses self._script, not pipeline."""
        content = pathlib.Path("core/rate_limiter.py").read_text()
        assert "self._script(" in content
        assert "pipe = self._redis.pipeline()" not in content

    def test_lua_returns_minus_one_on_limit(self):
        """Lua script returns -1 when limit is exceeded."""
        async def _test():
            from core.rate_limiter import RateLimiter
            redis = AsyncMock()
            script_mock = AsyncMock(return_value=-1)
            redis.register_script = MagicMock(return_value=script_mock)
            limiter = RateLimiter(redis)

            from exceptions import RateLimitError
            with pytest.raises(RateLimitError):
                await limiter.check_api_key_rpm("key_0")
        _run(_test())

    def test_lua_allows_under_limit(self):
        """Under limit: Lua returns count, no error."""
        async def _test():
            from core.rate_limiter import RateLimiter
            redis = AsyncMock()
            script_mock = AsyncMock(return_value=5)
            redis.register_script = MagicMock(return_value=script_mock)
            limiter = RateLimiter(redis)
            # Should not raise
            await limiter.check_api_key_rpm("key_0")
        _run(_test())


# ── Cascade → SET NULL ───────────────────────────────────────────────────────

class TestCascadeSetNull:
    """Log tables must use SET NULL, not CASCADE."""

    def test_migration_file_exists(self):
        p = pathlib.Path("db/migrations/versions/d4e5f6a7b8c9_fix_cascade_to_set_null.py")
        assert p.exists()

    def test_migration_changes_to_set_null(self):
        content = pathlib.Path(
            "db/migrations/versions/d4e5f6a7b8c9_fix_cascade_to_set_null.py"
        ).read_text()
        assert 'ondelete="SET NULL"' in content
        assert "brief_log" in content
        assert "outfit_log" in content
        assert "events" in content

    def test_brief_log_model_set_null(self):
        content = pathlib.Path("db/models/brief_log.py").read_text()
        assert 'ondelete="SET NULL"' in content
        assert "nullable=True" in content

    def test_outfit_log_model_set_null(self):
        content = pathlib.Path("db/models/outfit_log.py").read_text()
        assert 'ondelete="SET NULL"' in content

    def test_events_model_set_null(self):
        content = pathlib.Path("db/models/events.py").read_text()
        assert 'ondelete="SET NULL"' in content


# ── Worker concurrency ───────────────────────────────────────────────────────

class TestWorkerConcurrency:
    """Workers must support concurrent task processing via semaphore."""

    def test_fast_worker_has_semaphore(self):
        content = pathlib.Path("worker/fast_worker.py").read_text()
        assert "asyncio.Semaphore" in content
        assert "MAX_CONCURRENT" in content
        assert "_process_and_release" in content

    def test_slow_worker_has_semaphore(self):
        content = pathlib.Path("worker/slow_worker.py").read_text()
        assert "asyncio.Semaphore" in content
        assert "MAX_CONCURRENT" in content

    def test_fast_worker_drains_on_shutdown(self):
        content = pathlib.Path("worker/fast_worker.py").read_text()
        assert "asyncio.wait(self._tasks" in content

    def test_fast_max_concurrent_value(self):
        content = pathlib.Path("worker/fast_worker.py").read_text()
        assert "MAX_CONCURRENT = 4" in content

    def test_slow_max_concurrent_value(self):
        content = pathlib.Path("worker/slow_worker.py").read_text()
        assert "MAX_CONCURRENT = 2" in content


# ── Correlation ID ───────────────────────────────────────────────────────────

class TestCorrelationId:
    """Request ID must propagate through structlog contextvars."""

    def test_request_id_middleware_uses_contextvars(self):
        content = pathlib.Path("api/middleware/request_id.py").read_text()
        assert "ContextVar" in content
        assert "request_id_var" in content
        assert "structlog.contextvars" in content

    def test_structlog_merges_contextvars(self):
        content = pathlib.Path("main.py").read_text()
        assert "structlog.contextvars.merge_contextvars" in content

    def test_request_id_var_importable(self):
        from api.middleware.request_id import request_id_var
        assert request_id_var.get() == ""  # default


# ── Connection pool tuning ───────────────────────────────────────────────────

class TestConnectionPoolTuning:
    """DB engines must have pool_pre_ping and pool_recycle."""

    def test_pool_pre_ping(self):
        content = pathlib.Path("db/base.py").read_text()
        assert "pool_pre_ping=True" in content

    def test_pool_recycle(self):
        content = pathlib.Path("db/base.py").read_text()
        assert "pool_recycle=600" in content

    def test_both_engines_have_tuning(self):
        content = pathlib.Path("db/base.py").read_text()
        # Both write and read makers should have pre_ping
        assert content.count("pool_pre_ping=True") == 2


# ── Integration: cascade migration applied ──────────────────────────────────

@pytest.mark.skipif(
    os.environ.get("ENVIRONMENT") == "test" or os.environ.get("CI") == "true",
    reason="requires seeded database (not available in CI)",
)
class TestCascadeLive:
    """Verify FK constraints changed in live DB."""

    def test_fk_is_set_null(self):
        async def _test():
            from sqlalchemy import text
            from db.base import AsyncReadSession

            query = text("""
                SELECT confdeltype FROM pg_constraint
                WHERE conname IN ('brief_log_user_id_fkey', 'outfit_log_user_id_fkey', 'events_user_id_fkey')
            """)
            async with AsyncReadSession() as session:
                result = await session.execute(query)
                types = [row[0] for row in result.fetchall()]

            assert len(types) == 3, f"Expected 3 FK constraints, got {len(types)}"
            for t in types:
                val = t.decode() if isinstance(t, bytes) else t
                assert val == "n", f"Expected SET NULL ('n'), got '{val}'"

        try:
            _run(_test())
        except Exception as e:
            err = str(e).lower()
            if "cannot use" in err or "connect" in err or "event loop" in err or "attached" in err:
                pytest.skip(f"DB/event loop not available: {e}")
            raise
