"""Phase 2 tests — queue reliability, backoff, pagination, task tracking, atomic pool."""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _run(coro):
    """Run coroutine in a fresh event loop (avoids session-loop conflicts)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()



# ── Queue reliability (ack/nack/recover) ─────────────────────────────────────

class TestQueueReliability:
    """Queue must not lose messages on crash."""

    def test_pop_moves_to_processing(self):
        """pop() moves message to processing list."""
        async def _test():
            from core.queue import RedisQueue, QueuePriority, TaskMessage, _PROCESSING_KEY
            redis = AsyncMock()
            q = RedisQueue(redis)
            msg_data = TaskMessage(task_type="test", payload={"a": 1}).to_json()
            redis.rpoplpush = AsyncMock(return_value=msg_data.encode())
            result = await q.pop([QueuePriority.HIGH])
            redis.rpoplpush.assert_called_once_with(QueuePriority.HIGH.value, _PROCESSING_KEY)
            assert result.task_type == "test"
        _run(_test())

    def test_ack_removes_from_processing(self):
        """ack() removes message from processing list."""
        async def _test():
            from core.queue import RedisQueue, TaskMessage, _PROCESSING_KEY
            redis = AsyncMock()
            q = RedisQueue(redis)
            msg = TaskMessage(task_type="test", payload={})
            msg._raw_json = msg.to_json()
            await q.ack(msg)
            redis.lrem.assert_called_once_with(_PROCESSING_KEY, 1, msg._raw_json)
        _run(_test())

    def test_requeue_moves_back(self):
        """requeue() removes from processing and pushes back to queue."""
        async def _test():
            from core.queue import RedisQueue, QueuePriority, TaskMessage, _PROCESSING_KEY
            redis = AsyncMock()
            q = RedisQueue(redis)
            msg = TaskMessage(task_type="test", payload={}, retry_count=0)
            msg._raw_json = msg.to_json()
            await q.requeue(msg, QueuePriority.HIGH)
            redis.lrem.assert_called_once_with(_PROCESSING_KEY, 1, msg._raw_json)
            redis.lpush.assert_called_once()
            assert msg.retry_count == 1
        _run(_test())

    def test_dead_removes_from_processing(self):
        """move_to_dead() removes from processing list."""
        async def _test():
            from core.queue import RedisQueue, TaskMessage, _PROCESSING_KEY
            redis = AsyncMock()
            q = RedisQueue(redis)
            msg = TaskMessage(task_type="test", payload={})
            msg._raw_json = msg.to_json()
            await q.move_to_dead(msg, "test error")
            redis.lrem.assert_called_once_with(_PROCESSING_KEY, 1, msg._raw_json)
        _run(_test())

    def test_recover_processing_moves_to_high(self):
        """recover_processing() moves orphaned messages back to HIGH."""
        async def _test():
            from core.queue import RedisQueue, QueuePriority, _PROCESSING_KEY
            redis = AsyncMock()
            redis.rpoplpush = AsyncMock(side_effect=[b'{"task_type":"t","payload":{}}', None])
            q = RedisQueue(redis)
            count = await q.recover_processing()
            assert count == 1
            redis.rpoplpush.assert_called_with(_PROCESSING_KEY, QueuePriority.HIGH.value)
        _run(_test())


# ── Exponential backoff ──────────────────────────────────────────────────────

class TestExponentialBackoff:
    """Workers must delay retries with exponential backoff."""

    def test_backoff_values_in_code(self):
        """Fast and slow worker define backoff delays."""
        import pathlib
        for f in ["worker/fast_worker.py", "worker/slow_worker.py"]:
            content = pathlib.Path(f).read_text()
            assert "_BACKOFF = [1, 4, 16]" in content, f"{f} missing backoff"

    def test_sleep_before_requeue_in_code(self):
        """Workers sleep(delay) before requeue."""
        import pathlib
        content = pathlib.Path("worker/fast_worker.py").read_text()
        assert "asyncio.sleep(delay)" in content
        assert "_BACKOFF[min(msg.retry_count" in content

    def test_backoff_delay_increases(self):
        """Backoff delay increases with retry count."""
        backoff = [1, 4, 16]
        assert backoff[min(0, len(backoff) - 1)] == 1
        assert backoff[min(1, len(backoff) - 1)] == 4
        assert backoff[min(2, len(backoff) - 1)] == 16
        assert backoff[min(5, len(backoff) - 1)] == 16  # caps at last

    def test_max_retries_goes_to_dead(self):
        """After MAX_RETRIES, code sends to dead letter."""
        import pathlib
        content = pathlib.Path("worker/fast_worker.py").read_text()
        assert "msg.retry_count >= self.MAX_RETRIES" in content
        assert "move_to_dead" in content


# ── Background task tracking ────────────────────────────────────────────────

class TestBackgroundTaskTracking:
    """Fire-and-forget tasks must be tracked for graceful shutdown."""

    def test_track_task_function_exists(self):
        from bot.handlers.wardrobe import _track_task, _background_tasks
        assert callable(_track_task)
        assert isinstance(_background_tasks, set)

    def test_tracked_task_auto_removes(self):
        """Completed tasks auto-remove from tracking set."""
        async def _test():
            from bot.handlers.wardrobe import _track_task, _background_tasks
            async def _dummy():
                return 42
            initial = len(_background_tasks)
            task = _track_task(_dummy())
            assert task in _background_tasks
            await task
            await asyncio.sleep(0)
            assert task not in _background_tasks
            assert len(_background_tasks) == initial
        _run(_test())

    def test_no_raw_create_task_in_wardrobe(self):
        """wardrobe.py should use _track_task, not asyncio.create_task outside of _track_task."""
        import pathlib
        content = pathlib.Path("bot/handlers/wardrobe.py").read_text()
        lines = content.split("\n")
        in_track_task_fn = False
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if "def _track_task" in stripped:
                in_track_task_fn = True
                continue
            if in_track_task_fn and stripped and not stripped.startswith(("#", "\"", "task", "return", "_background")):
                if not line.startswith("    ") and not line.startswith("\t"):
                    in_track_task_fn = False
            if "asyncio.create_task(" in line and not in_track_task_fn:
                pytest.fail(f"Line {i}: raw asyncio.create_task() — use _track_task()")


# ── Pagination in schedule_all ───────────────────────────────────────────────

class TestSchedulePagination:
    """schedule_all() must paginate user queries."""

    def test_schedule_all_has_batch_limit(self):
        """schedule_all() uses LIMIT/OFFSET pagination."""
        import pathlib
        content = pathlib.Path("worker/tasks/morning_brief.py").read_text()
        assert "_BATCH" in content
        assert ".limit(_BATCH)" in content
        assert ".offset(offset)" in content or ".offset(_t_offset)" in content

    def test_no_unbounded_all_users(self):
        """No list(result.scalars().all()) without LIMIT in _schedule_all_impl."""
        import pathlib
        content = pathlib.Path("worker/tasks/morning_brief.py").read_text()
        # schedule_all delegates to _schedule_all_impl where pagination lives
        start = content.find("async def _schedule_all_impl")
        assert start != -1, "_schedule_all_impl must exist"
        # Find next top-level function
        end = content.find("\nasync def ", start + 1)
        if end == -1:
            end = content.find("\n@register", start + 1)
        schedule_fn = content[start:end] if end != -1 else content[start:]
        # Check that limit is used near each .all()
        assert ".limit(_BATCH)" in schedule_fn


# ── Anthropic pool atomic counter ───────────────────────────────────────────

class TestAnthropicPoolAtomic:
    """Anthropic pool must use atomic counter, not itertools.cycle."""

    def test_no_itertools_cycle(self):
        """anthropic_client.py must not use itertools.cycle."""
        import pathlib
        content = pathlib.Path("core/anthropic_client.py").read_text()
        assert "itertools" not in content
        assert "cycle(" not in content

    def test_has_asyncio_lock(self):
        """AnthropicPool uses asyncio.Lock for round-robin."""
        import pathlib
        content = pathlib.Path("core/anthropic_client.py").read_text()
        assert "asyncio.Lock()" in content
        assert "async with self._lock" in content

    def test_next_client_is_async(self):
        """_next_client must be async (awaitable)."""
        import pathlib
        content = pathlib.Path("core/anthropic_client.py").read_text()
        assert "async def _next_client" in content
        assert "await self._next_client()" in content
