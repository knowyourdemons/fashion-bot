"""Tests for worker tasks: cleanup_r2, engagement, birthday_alert, growth_alert, reminders, daily_reset."""
import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone, date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure worker.fast_worker has a real register decorator (not MagicMock)
# so that @register("check_engagement") returns the original async function.
if "worker.fast_worker" in sys.modules and isinstance(sys.modules["worker.fast_worker"], MagicMock):
    import types
    _wfw = types.ModuleType("worker.fast_worker")
    _wfw.register = lambda task_type: (lambda fn: fn)
    _wfw.TASK_HANDLERS = {}
    sys.modules["worker.fast_worker"] = _wfw


def _run(coro):
    """Run coroutine in a fresh event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_wardrobe_item(item_id=None, photo_url="https://cdn.example.com/photos/abc123.png",
                        deleted_at=None):
    """Create a mock WardrobeItem."""
    item = MagicMock()
    item.id = item_id or uuid.uuid4()
    item.photo_url = photo_url
    item.deleted_at = deleted_at or (datetime.now(timezone.utc) - timedelta(days=10))
    return item


def _make_user(user_id=None, telegram_id=12345, trial_started_at=None,
               children=None, deleted_at=None, plan="premium"):
    """Create a mock User."""
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    user.telegram_id = telegram_id
    user.trial_started_at = trial_started_at
    user.children = children or []
    user.deleted_at = deleted_at
    user.plan = plan
    return user


def _make_child(name="Алиса", deleted_at=None):
    child = MagicMock()
    child.id = uuid.uuid4()
    child.name = name
    child.deleted_at = deleted_at
    return child


# ── cleanup_r2 helpers ───────────────────────────────────────────────────────

def _cleanup_read_session(items):
    """Build a mock AsyncReadSession context manager returning items."""
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = items
    session.__aenter__.return_value.execute = AsyncMock(return_value=result_mock)
    return session


def _cleanup_write_session():
    """Build a mock AsyncWriteSession context manager."""
    session = AsyncMock()
    session.__aenter__.return_value.execute = AsyncMock()
    session.__aenter__.return_value.commit = AsyncMock()
    return session


# ── cleanup_r2 tests ─────────────────────────────────────────────────────────

class TestCleanupR2:
    """Tests for worker/tasks/cleanup_r2.run()."""

    def test_deletes_r2_files_for_old_deleted_items(self):
        """R2 delete_photo is called with the correct key for each item."""
        async def _test():
            item = _make_wardrobe_item(photo_url="https://cdn.example.com/photos/abc.png")
            r2 = AsyncMock()

            with patch("db.base.AsyncReadSession", return_value=_cleanup_read_session([item])), \
                 patch("db.base.AsyncWriteSession", return_value=_cleanup_write_session()), \
                 patch("services.storage.r2_storage.get_r2_storage", return_value=r2):
                from importlib import reload
                import worker.tasks.cleanup_r2 as mod
                reload(mod)
                await mod.run()

            r2.delete_photo.assert_awaited_once_with("photos/abc.png")
        _run(_test())

    def test_clears_photo_url_after_r2_delete(self):
        """DB update is called to clear photo_url after successful R2 delete."""
        async def _test():
            item = _make_wardrobe_item(photo_url="https://cdn.example.com/photos/abc.png")
            r2 = AsyncMock()
            ws = _cleanup_write_session()

            with patch("db.base.AsyncReadSession", return_value=_cleanup_read_session([item])), \
                 patch("db.base.AsyncWriteSession", return_value=ws), \
                 patch("services.storage.r2_storage.get_r2_storage", return_value=r2):
                from importlib import reload
                import worker.tasks.cleanup_r2 as mod
                reload(mod)
                await mod.run()

            ws.__aenter__.return_value.execute.assert_awaited_once()
            ws.__aenter__.return_value.commit.assert_awaited_once()
        _run(_test())

    def test_skips_items_with_no_photo_url(self):
        """Query filters out items with NULL photo_url; empty result means no work."""
        async def _test():
            with patch("db.base.AsyncReadSession", return_value=_cleanup_read_session([])), \
                 patch("db.base.AsyncWriteSession") as ws_cls:
                from importlib import reload
                import worker.tasks.cleanup_r2 as mod
                reload(mod)
                await mod.run()

            ws_cls.assert_not_called()
        _run(_test())

    def test_continues_on_per_item_r2_error(self):
        """If R2 delete fails for one item, subsequent items are still processed."""
        async def _test():
            item1 = _make_wardrobe_item(photo_url="https://cdn.example.com/photos/fail.png")
            item2 = _make_wardrobe_item(photo_url="https://cdn.example.com/photos/ok.png")
            r2 = AsyncMock()
            r2.delete_photo = AsyncMock(side_effect=[Exception("R2 timeout"), None])
            ws = _cleanup_write_session()

            with patch("db.base.AsyncReadSession", return_value=_cleanup_read_session([item1, item2])), \
                 patch("db.base.AsyncWriteSession", return_value=ws), \
                 patch("services.storage.r2_storage.get_r2_storage", return_value=r2):
                from importlib import reload
                import worker.tasks.cleanup_r2 as mod
                reload(mod)
                await mod.run()

            assert r2.delete_photo.await_count == 2
            # Only the second item succeeds → one DB write
            ws.__aenter__.return_value.execute.assert_awaited_once()
        _run(_test())

    def test_handles_cdn_url_format(self):
        """CDN URL https://...r2.dev/path/file is parsed → key = path/file."""
        async def _test():
            item = _make_wardrobe_item(
                photo_url="https://pub-abc.r2.dev/wardrobe/user1/photo.jpg"
            )
            r2 = AsyncMock()

            with patch("db.base.AsyncReadSession", return_value=_cleanup_read_session([item])), \
                 patch("db.base.AsyncWriteSession", return_value=_cleanup_write_session()), \
                 patch("services.storage.r2_storage.get_r2_storage", return_value=r2):
                from importlib import reload
                import worker.tasks.cleanup_r2 as mod
                reload(mod)
                await mod.run()

            r2.delete_photo.assert_awaited_once_with("wardrobe/user1/photo.jpg")
        _run(_test())

    def test_handles_raw_key_format(self):
        """Non-HTTP photo_url is used as-is for R2 key."""
        async def _test():
            item = _make_wardrobe_item(photo_url="photos/legacy/old.png")
            r2 = AsyncMock()

            with patch("db.base.AsyncReadSession", return_value=_cleanup_read_session([item])), \
                 patch("db.base.AsyncWriteSession", return_value=_cleanup_write_session()), \
                 patch("services.storage.r2_storage.get_r2_storage", return_value=r2):
                from importlib import reload
                import worker.tasks.cleanup_r2 as mod
                reload(mod)
                await mod.run()

            r2.delete_photo.assert_awaited_once_with("photos/legacy/old.png")
        _run(_test())

    def test_does_nothing_when_no_deleted_items(self):
        """No R2 calls when query returns empty result set."""
        async def _test():
            with patch("db.base.AsyncReadSession", return_value=_cleanup_read_session([])), \
                 patch("services.storage.r2_storage.get_r2_storage") as r2_factory:
                from importlib import reload
                import worker.tasks.cleanup_r2 as mod
                reload(mod)
                await mod.run()

            r2_factory.assert_not_called()
        _run(_test())


# ── engagement helpers ────────────────────────────────────────────────────────

def _redis_mock(exists=False):
    """Create a mock Redis client."""
    r = AsyncMock()
    r.exists = AsyncMock(return_value=exists)
    r.set = AsyncMock()
    return r


def _make_session_factory(user, brief_count=0):
    """Return a callable that creates fresh AsyncReadSession context managers.

    The engagement function calls `async with AsyncReadSession()` 3-4 times:
    1. Load user (session.execute → result.scalar_one_or_none)
    2. Load wardrobe items (session delegates to get_owner_items)
    3. Count briefs (session.scalar)
    4. Count liked briefs (session delegates to count_liked_briefs)
    """
    call_count = 0

    def factory():
        nonlocal call_count
        call_count += 1
        session = AsyncMock()
        if call_count == 1:
            # First call: user query
            user_result = MagicMock()
            user_result.scalar_one_or_none.return_value = user
            session.execute = AsyncMock(return_value=user_result)
        elif call_count == 3:
            # Third call: brief count
            session.scalar = AsyncMock(return_value=brief_count)
        # Other calls just return a default AsyncMock session
        return session

    return factory


def _run_engagement(user, redis, wardrobe_items=None, brief_count=0,
                    liked_count=0, is_trial=True, bot_mock=None):
    """Run check_engagement with all dependencies mocked. Returns bot mock."""
    if bot_mock is None:
        bot_mock = AsyncMock()

    session_factory = _make_session_factory(user, brief_count)

    class FakeAsyncReadSession:
        async def __aenter__(self):
            return session_factory()
        async def __aexit__(self, *args):
            pass

    async def _test():
        with patch("db.base.AsyncReadSession", FakeAsyncReadSession), \
             patch("core.redis.get_redis", return_value=redis), \
             patch("core.permissions.is_trial_active", return_value=is_trial), \
             patch("db.crud.wardrobe.get_owner_items", new_callable=AsyncMock, return_value=wardrobe_items or []), \
             patch("config.settings", MagicMock(telegram_bot_token="fake-token")), \
             patch("telegram.Bot", return_value=bot_mock), \
             patch("db.crud.brief_log.count_liked_briefs", new_callable=AsyncMock, return_value=liked_count):
            from importlib import reload
            import worker.tasks.engagement as mod
            reload(mod)
            return await mod.check_engagement({"user_id": str(user.id)})

    result = _run(_test())
    return result, bot_mock


# ── engagement tests ──────────────────────────────────────────────────────────

class TestEngagement:
    """Tests for worker/tasks/engagement.check_engagement()."""

    def test_day3_few_items_sends_wardrobe_prompt(self):
        """Day 3 with < 15 items sends add-more-items message."""
        user = _make_user(trial_started_at=datetime.now(timezone.utc) - timedelta(days=2))
        child = _make_child()
        user.children = [child]

        _, bot = _run_engagement(user, _redis_mock(), wardrobe_items=[MagicMock()] * 5)

        bot.send_message.assert_awaited_once()
        text = bot.send_message.call_args.kwargs.get("text", "")
        assert "Добавь ещё" in text

    def test_day3_enough_items_skips_prompt(self):
        """Day 3 with >= 15 items does NOT send a message."""
        user = _make_user(trial_started_at=datetime.now(timezone.utc) - timedelta(days=2))
        child = _make_child()
        user.children = [child]

        result, bot = _run_engagement(user, _redis_mock(), wardrobe_items=[MagicMock()] * 20)

        bot.send_message.assert_not_awaited()
        assert result == {}

    def test_day7_sends_week_message(self):
        """Day 7 sends the week-together message."""
        user = _make_user(trial_started_at=datetime.now(timezone.utc) - timedelta(days=6))
        child = _make_child(name="Маша")
        user.children = [child]

        _, bot = _run_engagement(user, _redis_mock(), brief_count=5)

        bot.send_message.assert_awaited_once()
        text = bot.send_message.call_args.kwargs.get("text", "")
        assert "Неделя вместе" in text

    def test_day10_sends_expiry_warning(self):
        """Day 10 sends the 4-days-left warning for trial users."""
        user = _make_user(trial_started_at=datetime.now(timezone.utc) - timedelta(days=9))
        child = _make_child()
        user.children = [child]

        _, bot = _run_engagement(user, _redis_mock(), brief_count=10, is_trial=True)

        bot.send_message.assert_awaited_once()
        text = bot.send_message.call_args.kwargs.get("text", "")
        assert "4 дня" in text

    def test_day11_sends_detailed_stats(self):
        """Day 11 sends the detailed trial report with stats."""
        user = _make_user(trial_started_at=datetime.now(timezone.utc) - timedelta(days=10))
        child = _make_child(name="Алиса")
        user.children = [child]

        _, bot = _run_engagement(
            user, _redis_mock(), brief_count=12, liked_count=8,
            wardrobe_items=[MagicMock()] * 25
        )

        bot.send_message.assert_awaited_once()
        text = bot.send_message.call_args.kwargs.get("text", "")
        assert "11 дней" in text
        markup = bot.send_message.call_args.kwargs.get("reply_markup")
        assert markup is not None

    def test_skips_if_redis_lock_exists(self):
        """No message sent if Redis lock already set for today."""
        user = _make_user(trial_started_at=datetime.now(timezone.utc) - timedelta(days=6))
        child = _make_child()
        user.children = [child]

        result, bot = _run_engagement(user, _redis_mock(exists=True))

        bot.send_message.assert_not_awaited()
        assert result == {}

    def test_sets_redis_lock_after_sending(self):
        """Redis lock is set with 86400s TTL after successful send."""
        user = _make_user(trial_started_at=datetime.now(timezone.utc) - timedelta(days=6))
        child = _make_child()
        user.children = [child]
        redis = _redis_mock()

        _run_engagement(user, redis, brief_count=3)

        redis.set.assert_awaited_once()
        _, kwargs = redis.set.call_args
        assert kwargs.get("ex") == 86400

    def test_handles_missing_user(self):
        """Returns empty dict when user not found in DB."""
        redis = _redis_mock()
        # _run_engagement with user=None (missing user)
        result, bot = _run_engagement(
            _make_user(), redis,  # user object exists but DB returns None
        )
        # Actually need custom session that returns None for user
        class NullUserSession:
            async def __aenter__(self):
                s = AsyncMock()
                r = MagicMock()
                r.scalar_one_or_none.return_value = None
                s.execute = AsyncMock(return_value=r)
                return s
            async def __aexit__(self, *args):
                pass

        async def _test():
            with patch("db.base.AsyncReadSession", NullUserSession), \
                 patch("core.redis.get_redis", return_value=redis):
                from importlib import reload
                import worker.tasks.engagement as mod
                reload(mod)
                return await mod.check_engagement({"user_id": str(uuid.uuid4())})

        result = _run(_test())
        assert result == {}

    def test_handles_non_trial_user(self):
        """Returns empty dict when user has no trial_started_at."""
        user = _make_user(trial_started_at=None)
        result, bot = _run_engagement(user, _redis_mock())
        assert result == {}
        bot.send_message.assert_not_awaited()

    def test_day10_skips_non_trial_active_user(self):
        """Day 10 with is_trial condition skips if trial not active."""
        user = _make_user(trial_started_at=datetime.now(timezone.utc) - timedelta(days=9))
        child = _make_child()
        user.children = [child]

        result, bot = _run_engagement(user, _redis_mock(), is_trial=False)

        bot.send_message.assert_not_awaited()
        assert result == {}

    def test_non_schedule_day_returns_empty(self):
        """Trial day not in schedule (e.g. day 5) returns empty dict."""
        user = _make_user(trial_started_at=datetime.now(timezone.utc) - timedelta(days=4))
        child = _make_child()
        user.children = [child]
        result, bot = _run_engagement(user, _redis_mock())
        assert result == {}
        bot.send_message.assert_not_awaited()

    def test_day11_includes_upgrade_and_compare_buttons(self):
        """Day 11 message includes inline keyboard with upgrade + compare buttons."""
        user = _make_user(trial_started_at=datetime.now(timezone.utc) - timedelta(days=10))
        child = _make_child()
        user.children = [child]

        _, bot = _run_engagement(
            user, _redis_mock(), brief_count=8, liked_count=5,
            wardrobe_items=[MagicMock()] * 15
        )

        bot.send_message.assert_awaited_once()
        markup = bot.send_message.call_args.kwargs.get("reply_markup")
        assert markup is not None

    def test_user_with_no_children_uses_fallback_name(self):
        """When user has no children, child_name defaults to fallback."""
        user = _make_user(trial_started_at=datetime.now(timezone.utc) - timedelta(days=6))
        user.children = []

        _, bot = _run_engagement(user, _redis_mock(), brief_count=3)

        bot.send_message.assert_awaited_once()
        text = bot.send_message.call_args.kwargs.get("text", "")
        # "тебя" is the fallback name
        assert "тебя" in text

    def test_send_failure_is_caught(self):
        """Bot.send_message failure is caught and logged, no exception raised."""
        user = _make_user(trial_started_at=datetime.now(timezone.utc) - timedelta(days=6))
        child = _make_child()
        user.children = [child]

        bot = AsyncMock()
        bot.send_message = AsyncMock(side_effect=Exception("Telegram API error"))

        result, _ = _run_engagement(user, _redis_mock(), brief_count=3, bot_mock=bot)

        assert result == {}


# ═══════════════════════════════════════════════════════════════════════════════
# birthday_alert tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestBirthdayAlert:
    """Tests for worker/tasks/birthday_alert.py"""

    def test_run_executes_without_error(self):
        """Happy path: run() logs and returns (stub)."""
        async def _test():
            from worker.tasks.birthday_alert import run
            await run()
        _run(_test())

    def test_run_returns_none(self):
        """run() is a stub that returns None."""
        async def _test():
            from worker.tasks.birthday_alert import run
            result = await run()
            assert result is None
        _run(_test())


# ═══════════════════════════════════════════════════════════════════════════════
# growth_alert tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestGrowthAlertWHOTable:
    """WHO size table correctness."""

    def test_who_size_table_has_entries(self):
        from worker.tasks.growth_alert import _WHO_SIZE
        assert len(_WHO_SIZE) > 0
        for age, size in _WHO_SIZE.items():
            assert isinstance(age, int)
            assert isinstance(size, int)
            assert size >= 80

    def test_who_sizes_increase_with_age(self):
        from worker.tasks.growth_alert import _WHO_SIZE
        sorted_items = sorted(_WHO_SIZE.items())
        for i in range(1, len(sorted_items)):
            assert sorted_items[i][1] >= sorted_items[i - 1][1], \
                f"Size should not decrease: {sorted_items[i-1]} -> {sorted_items[i]}"


class TestCheckChildrenGrowth:
    """Tests for _check_children_growth."""

    def test_growth_alert_sent_when_child_outgrown(self):
        """Alert sent when child's actual size < WHO expected size."""
        async def _test():
            from worker.tasks.growth_alert import _check_children_growth

            user = MagicMock()
            user.id = uuid.uuid4()
            user.telegram_id = 12345

            child = MagicMock()
            child.id = uuid.uuid4()
            child.name = "Алиса"
            child.birthdate = date.today() - timedelta(days=36 * 30)
            child.current_size = "92"

            mock_bot = AsyncMock()
            mock_bot.send_message = AsyncMock()

            with patch("config.settings") as mock_settings:
                mock_settings.telegram_bot_token = "fake_token"
                with patch("telegram.Bot", return_value=mock_bot):
                    await _check_children_growth(user, [child])

            mock_bot.send_message.assert_called_once()
            call_kwargs = mock_bot.send_message.call_args[1]
            assert call_kwargs["chat_id"] == 12345
            assert "подрос" in call_kwargs["text"]
        _run(_test())

    def test_no_alert_when_size_matches(self):
        """No alert when child's size matches or exceeds WHO."""
        async def _test():
            from worker.tasks.growth_alert import _check_children_growth

            user = MagicMock()
            user.id = uuid.uuid4()
            user.telegram_id = 12345

            child = MagicMock()
            child.id = uuid.uuid4()
            child.name = "Алиса"
            child.birthdate = date.today() - timedelta(days=36 * 30)
            child.current_size = "104"

            mock_bot = AsyncMock()
            mock_bot.send_message = AsyncMock()

            with patch("config.settings") as mock_settings:
                mock_settings.telegram_bot_token = "fake_token"
                with patch("telegram.Bot", return_value=mock_bot):
                    await _check_children_growth(user, [child])

            mock_bot.send_message.assert_not_called()
        _run(_test())

    def test_no_alert_when_no_birthdate(self):
        """Skip child without birthdate."""
        async def _test():
            from worker.tasks.growth_alert import _check_children_growth

            user = MagicMock()
            user.id = uuid.uuid4()
            user.telegram_id = 12345

            child = MagicMock()
            child.id = uuid.uuid4()
            child.name = "Test"
            child.birthdate = None
            child.current_size = "92"

            mock_bot = AsyncMock()
            mock_bot.send_message = AsyncMock()

            with patch("config.settings") as mock_settings:
                mock_settings.telegram_bot_token = "fake_token"
                with patch("telegram.Bot", return_value=mock_bot):
                    await _check_children_growth(user, [child])

            mock_bot.send_message.assert_not_called()
        _run(_test())

    def test_invalid_size_format_does_not_crash(self):
        """Invalid size format (non-numeric) is skipped."""
        async def _test():
            from worker.tasks.growth_alert import _check_children_growth

            user = MagicMock()
            user.id = uuid.uuid4()
            user.telegram_id = 12345

            child = MagicMock()
            child.id = uuid.uuid4()
            child.name = "Test"
            child.birthdate = date.today() - timedelta(days=36 * 30)
            child.current_size = "not_a_number"

            mock_bot = AsyncMock()

            with patch("config.settings") as mock_settings:
                mock_settings.telegram_bot_token = "fake_token"
                with patch("telegram.Bot", return_value=mock_bot):
                    await _check_children_growth(user, [child])

            mock_bot.send_message.assert_not_called()
        _run(_test())

    def test_very_young_child_no_alert(self):
        """Child under 12 months has no WHO size mapping."""
        async def _test():
            from worker.tasks.growth_alert import _check_children_growth

            user = MagicMock()
            user.id = uuid.uuid4()
            user.telegram_id = 12345

            child = MagicMock()
            child.id = uuid.uuid4()
            child.name = "Baby"
            child.birthdate = date.today() - timedelta(days=6 * 30)
            child.current_size = "68"

            mock_bot = AsyncMock()

            with patch("config.settings") as mock_settings:
                mock_settings.telegram_bot_token = "fake_token"
                with patch("telegram.Bot", return_value=mock_bot):
                    await _check_children_growth(user, [child])

            mock_bot.send_message.assert_not_called()
        _run(_test())


class TestGrowthAlertRun:
    """Tests for growth_alert.run() — full flow."""

    def test_run_no_users_no_alerts(self):
        """No mom users → no alerts sent."""
        async def _test():
            from worker.tasks.growth_alert import run

            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_session.execute.return_value = mock_result

            mock_bot = AsyncMock()

            with patch("db.base.AsyncReadSession") as mock_ctx:
                mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
                mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
                with patch("config.settings") as mock_settings:
                    mock_settings.telegram_bot_token = "fake_token"
                    with patch("telegram.Bot", return_value=mock_bot):
                        await run()

            mock_bot.send_message.assert_not_called()
        _run(_test())

    def test_run_bot_send_error_does_not_crash(self):
        """If bot.send_message fails, run() continues with next child."""
        async def _test():
            from worker.tasks.growth_alert import run

            child = MagicMock()
            child.id = uuid.uuid4()
            child.name = "Алиса"
            child.birthdate = date.today() - timedelta(days=36 * 30)
            child.current_size = "86"
            child.deleted_at = None

            user = MagicMock()
            user.id = uuid.uuid4()
            user.telegram_id = 12345
            user.children = [child]

            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [user]
            mock_session.execute.return_value = mock_result

            mock_bot = AsyncMock()
            mock_bot.send_message.side_effect = Exception("Telegram down")

            with patch("db.base.AsyncReadSession") as mock_ctx:
                mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
                mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
                with patch("config.settings") as mock_settings:
                    mock_settings.telegram_bot_token = "fake_token"
                    with patch("telegram.Bot", return_value=mock_bot):
                        await run()
        _run(_test())

    def test_run_with_decimal_size(self):
        """Size with decimal point (e.g. '98.5') is parsed correctly."""
        async def _test():
            from worker.tasks.growth_alert import _check_children_growth

            user = MagicMock()
            user.id = uuid.uuid4()
            user.telegram_id = 12345

            child = MagicMock()
            child.id = uuid.uuid4()
            child.name = "Test"
            child.birthdate = date.today() - timedelta(days=36 * 30)
            child.current_size = "98.5"

            mock_bot = AsyncMock()

            with patch("config.settings") as mock_settings:
                mock_settings.telegram_bot_token = "fake_token"
                with patch("telegram.Bot", return_value=mock_bot):
                    await _check_children_growth(user, [child])

            mock_bot.send_message.assert_not_called()
        _run(_test())


# ═══════════════════════════════════════════════════════════════════════════════
# reminders tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestReminders:
    """Tests for worker/tasks/reminders.py"""

    def test_run_executes_without_error(self):
        """run() is a stub — should not crash."""
        async def _test():
            from worker.tasks.reminders import run
            result = await run()
            assert result is None
        _run(_test())

    def test_handle_send_reminder_returns_sent(self):
        """handle_send_reminder returns {"sent": True}."""
        async def _test():
            from worker.tasks.reminders import handle_send_reminder
            result = await handle_send_reminder({
                "user_id": str(uuid.uuid4()),
                "reminder_type": 3,
            })
            assert result == {"sent": True}
        _run(_test())

    def test_handle_send_reminder_default_type(self):
        """reminder_type defaults to 3 when not provided."""
        async def _test():
            from worker.tasks.reminders import handle_send_reminder
            result = await handle_send_reminder({
                "user_id": str(uuid.uuid4()),
            })
            assert result == {"sent": True}
        _run(_test())

    def test_reminder_rules_structure(self):
        """REMINDER_RULES has correct structure."""
        from worker.tasks.reminders import REMINDER_RULES
        assert len(REMINDER_RULES) == 3
        days = [r[0] for r in REMINDER_RULES]
        assert days == [3, 7, 30]


# ═══════════════════════════════════════════════════════════════════════════════
# daily_reset tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestDailyReset:
    """Tests for worker/tasks/daily_reset.py"""

    def test_reset_no_timezones_in_db(self):
        """No timezones in DB → nothing to reset."""
        async def _test():
            from worker.tasks.daily_reset import reset_daily_limits

            mock_read_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.fetchall.return_value = []
            mock_read_session.execute.return_value = mock_result

            with patch("worker.tasks.daily_reset.AsyncReadSession") as mock_ctx:
                mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_read_session)
                mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

                await reset_daily_limits()
        _run(_test())

    def test_reset_invalid_timezone_skipped(self):
        """Invalid timezone names are skipped without crashing."""
        async def _test():
            from worker.tasks.daily_reset import reset_daily_limits

            mock_read_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.fetchall.return_value = [("Invalid/Timezone",), ("Also/Bad",)]
            mock_read_session.execute.return_value = mock_result

            with patch("worker.tasks.daily_reset.AsyncReadSession") as mock_ctx:
                mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_read_session)
                mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

                # Should not raise
                await reset_daily_limits()
        _run(_test())

    def test_reset_with_midnight_timezone(self):
        """Users in a midnight timezone get their daily counters reset."""
        from zoneinfo import ZoneInfo

        # Find a timezone that is currently at midnight
        now_utc = datetime.now(timezone.utc)
        midnight_tz = None
        for tz_name in ["Pacific/Kiritimati", "Pacific/Auckland", "Asia/Tokyo",
                        "Europe/Moscow", "Europe/London", "America/New_York",
                        "America/Los_Angeles", "Pacific/Honolulu",
                        "Asia/Kolkata", "Australia/Sydney", "Pacific/Fiji"]:
            try:
                local_hour = now_utc.astimezone(ZoneInfo(tz_name)).hour
                if local_hour == 0:
                    midnight_tz = tz_name
                    break
            except Exception:
                continue

        if midnight_tz is None:
            pytest.skip("No timezone is at midnight right now")

        async def _test():
            from worker.tasks.daily_reset import reset_daily_limits

            mock_read_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.fetchall.return_value = [(midnight_tz,)]
            mock_read_session.execute.return_value = mock_result

            mock_write_session = AsyncMock()
            mock_write_session.execute = AsyncMock()
            mock_write_session.commit = AsyncMock()

            with patch("worker.tasks.daily_reset.AsyncReadSession") as mock_read_ctx:
                mock_read_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_read_session)
                mock_read_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

                with patch("worker.tasks.daily_reset.AsyncWriteSession") as mock_write_ctx:
                    mock_write_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_write_session)
                    mock_write_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

                    await reset_daily_limits()

            mock_write_session.execute.assert_called_once()
            mock_write_session.commit.assert_called_once()
        _run(_test())
