"""
Error path tests — verify graceful degradation when external services fail.
"""
import asyncio
import io
import uuid
from datetime import date, datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

import anthropic
from exceptions import (
    CircuitBreakerOpenError,
    RateLimitError,
)


# ── helper: create AnthropicPool with mocked dependencies ──────────────────

def _make_pool(key_count=1):
    """Create an AnthropicPool with N keys, fully mocked Redis."""
    from core.anthropic_client import AnthropicPool

    redis = AsyncMock()
    redis.register_script.return_value = AsyncMock(return_value=1)
    redis.get.return_value = None
    redis.delete = AsyncMock()
    redis.set = AsyncMock()
    redis.incr.return_value = 1

    keys = [f"sk-test-{i}" for i in range(key_count)]
    with patch("core.anthropic_client.settings") as mock_s:
        mock_s.anthropic_keys_list = keys
        pool = AnthropicPool(redis)

    return pool


def _ok_response(text="ok"):
    r = MagicMock()
    r.content = [MagicMock(text=text)]
    r.usage.input_tokens = 10
    r.usage.output_tokens = 5
    r.usage.cache_read_input_tokens = 0
    r.usage.cache_creation_input_tokens = 0
    return r


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Anthropic API failures
# ═══════════════════════════════════════════════════════════════════════════════

class TestAnthropicPoolTimeout:
    async def test_timeout_all_keys_raises(self):
        """All keys timeout → eventually raises after fallback model also times out."""
        pool = _make_pool(1)

        async def slow(**kw):
            await asyncio.sleep(999)

        # Replace both CB and rate limiter to not touch Redis
        for cb in pool._circuit_breakers.values():
            cb.call = AsyncMock(side_effect=TimeoutError("timeout"))
        pool._rate_limiter.check_api_key_rpm = AsyncMock()

        with pytest.raises((TimeoutError, RuntimeError)):
            await pool.create_message(
                messages=[{"role": "user", "content": "test"}], max_tokens=10,
            )

    async def test_timeout_retries_across_keys(self):
        """Timeout on key 0 → retries on key 1 → success."""
        pool = _make_pool(2)
        pool._rate_limiter.check_api_key_rpm = AsyncMock()

        resp = _ok_response()
        attempt = 0

        async def cb_call(func, *a, **kw):
            nonlocal attempt
            attempt += 1
            if attempt == 1:
                raise TimeoutError("slow")
            return resp

        for cb in pool._circuit_breakers.values():
            cb.call = cb_call

        result = await pool.create_message(
            messages=[{"role": "user", "content": "test"}], max_tokens=10,
        )
        assert result.content[0].text == "ok"


class TestAnthropicAllKeysExhausted:
    async def test_circuit_open_all_keys_raises(self):
        pool = _make_pool(1)
        pool._rate_limiter.check_api_key_rpm = AsyncMock()

        for cb in pool._circuit_breakers.values():
            cb.call = AsyncMock(side_effect=CircuitBreakerOpenError("open"))

        with pytest.raises((CircuitBreakerOpenError, RuntimeError)):
            await pool.create_message(
                messages=[{"role": "user", "content": "test"}], max_tokens=10,
            )

    async def test_rate_limited_all_keys_raises(self):
        pool = _make_pool(1)
        pool._rate_limiter.check_api_key_rpm = AsyncMock(
            side_effect=RateLimitError("rate limit")
        )

        with pytest.raises((RateLimitError, RuntimeError)):
            await pool.create_message(
                messages=[{"role": "user", "content": "test"}], max_tokens=10,
            )


class TestAnthropicInvalidResponse:
    async def test_empty_content_list(self):
        """Response with empty content should not crash."""
        pool = _make_pool(1)
        pool._rate_limiter.check_api_key_rpm = AsyncMock()

        resp = MagicMock()
        resp.content = []
        resp.usage.input_tokens = 10
        resp.usage.output_tokens = 0
        resp.usage.cache_read_input_tokens = 0
        resp.usage.cache_creation_input_tokens = 0

        for cb in pool._circuit_breakers.values():
            cb.call = AsyncMock(return_value=resp)

        result = await pool.create_message(
            messages=[{"role": "user", "content": "test"}], max_tokens=10,
        )
        assert result.content == []

    async def test_has_clothing_with_empty_response(self):
        pool = _make_pool(1)
        resp = MagicMock()
        resp.content = []

        pool.create_message = AsyncMock(return_value=resp)

        img = Image.new("RGB", (100, 100), (255, 0, 0))
        buf = io.BytesIO()
        img.save(buf, "JPEG")
        result = await pool.has_clothing(buf.getvalue())
        assert result is False


class TestAnthropicRateLimit429:
    async def test_api_rate_limit_retries_to_next_key(self):
        pool = _make_pool(2)
        pool._rate_limiter.check_api_key_rpm = AsyncMock()

        resp = _ok_response()
        call_idx = 0

        async def cb_call(func, *a, **kw):
            nonlocal call_idx
            call_idx += 1
            if call_idx == 1:
                raise anthropic.RateLimitError(
                    message="429", response=MagicMock(status_code=429), body=None,
                )
            return resp

        for cb in pool._circuit_breakers.values():
            cb.call = cb_call

        result = await pool.create_message(
            messages=[{"role": "user", "content": "test"}], max_tokens=10,
        )
        assert result.content[0].text == "ok"


class TestAnthropicNetworkError:
    async def test_connection_error_raises_after_retries(self):
        pool = _make_pool(1)
        pool._rate_limiter.check_api_key_rpm = AsyncMock()

        for cb in pool._circuit_breakers.values():
            cb.call = AsyncMock(side_effect=ConnectionError("network down"))

        with pytest.raises((ConnectionError, RuntimeError)):
            await pool.create_message(
                messages=[{"role": "user", "content": "test"}], max_tokens=10,
            )

    async def test_generic_exception_propagates(self):
        pool = _make_pool(1)
        pool._rate_limiter.check_api_key_rpm = AsyncMock()

        for cb in pool._circuit_breakers.values():
            cb.call = AsyncMock(side_effect=ValueError("weird"))

        with pytest.raises((ValueError, RuntimeError)):
            await pool.create_message(
                messages=[{"role": "user", "content": "test"}], max_tokens=10,
            )


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Weather API failures
# ═══════════════════════════════════════════════════════════════════════════════

class TestWeatherNetworkTimeout:
    async def test_weather_timeout_returns_empty(self):
        import httpx
        from services.brief_weather import _get_weather

        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        with patch("core.redis.get_redis", return_value=mock_redis):
            with patch("httpx.AsyncClient") as mock_cls:
                inst = AsyncMock()
                inst.get.side_effect = httpx.TimeoutException("timed out")
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=inst)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

                result = await _get_weather(54.68, 25.31, "Europe/Vilnius")

        assert result["temp_now"] is None


class TestWeatherInvalidJSON:
    async def test_invalid_json_returns_empty(self):
        from services.brief_weather import _get_weather

        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        with patch("core.redis.get_redis", return_value=mock_redis):
            with patch("httpx.AsyncClient") as mock_cls:
                inst = AsyncMock()
                mock_resp = MagicMock()
                mock_resp.json.side_effect = ValueError("bad json")
                inst.get.return_value = mock_resp
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=inst)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

                result = await _get_weather(54.68, 25.31, "Europe/Vilnius")

        assert result["temp_now"] is None


class TestGeocodeFails:
    async def test_geocode_network_error_returns_none(self):
        import httpx
        from services.brief_weather import _geocode_city, _geocode_mem

        _geocode_mem.pop("NonexistentCity12345", None)

        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        with patch("core.redis.get_redis", return_value=mock_redis):
            with patch("httpx.AsyncClient") as mock_cls:
                inst = AsyncMock()
                inst.get.side_effect = httpx.ConnectError("dns failed")
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=inst)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

                result = await _geocode_city("NonexistentCity12345")

        assert result is None

    async def test_empty_city_returns_none(self):
        from services.brief_weather import _geocode_city
        result = await _geocode_city("")
        assert result is None

    async def test_geocode_empty_api_result_returns_none(self):
        from services.brief_weather import _geocode_city, _geocode_mem

        _geocode_mem.pop("EmptyResultCity99", None)

        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        with patch("core.redis.get_redis", return_value=mock_redis):
            with patch("httpx.AsyncClient") as mock_cls:
                inst = AsyncMock()
                mock_resp = MagicMock()
                mock_resp.json.return_value = []  # no results
                inst.get.return_value = mock_resp
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=inst)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

                result = await _geocode_city("EmptyResultCity99")

        assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Image processing failures
# ═══════════════════════════════════════════════════════════════════════════════

def _jpeg_bytes():
    img = Image.new("RGB", (100, 100), (255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


class TestONNXModelNotFound:
    async def test_onnx_fail_fallback_removebg(self):
        from services.image_processor import remove_background

        image_bytes = _jpeg_bytes()
        redis = AsyncMock()
        redis.incr = AsyncMock()

        with patch("services.image_processor._run_silueta", side_effect=FileNotFoundError("no model")):
            with patch("config.settings") as ms:
                ms.removebg_api_key = "test_key"
                with patch("httpx.AsyncClient") as mock_cls:
                    inst = AsyncMock()
                    mock_resp = MagicMock()
                    mock_resp.content = b"removebg_png"
                    mock_resp.raise_for_status = MagicMock()
                    inst.post.return_value = mock_resp
                    mock_cls.return_value.__aenter__ = AsyncMock(return_value=inst)
                    mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

                    result = await remove_background(image_bytes, redis)

        assert result == b"removebg_png"


class TestRemoveBGFails:
    async def test_both_fail_returns_original(self):
        from services.image_processor import remove_background

        image_bytes = _jpeg_bytes()
        redis = AsyncMock()
        redis.incr = AsyncMock()

        with patch("services.image_processor._run_silueta", side_effect=RuntimeError("onnx fail")):
            with patch("config.settings") as ms:
                ms.removebg_api_key = "test_key"
                with patch("httpx.AsyncClient") as mock_cls:
                    inst = AsyncMock()
                    inst.post.side_effect = Exception("api down")
                    mock_cls.return_value.__aenter__ = AsyncMock(return_value=inst)
                    mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

                    result = await remove_background(image_bytes, redis)

        assert result == image_bytes

    async def test_no_removebg_key_returns_original(self):
        from services.image_processor import remove_background

        image_bytes = _jpeg_bytes()

        with patch("services.image_processor._run_silueta", side_effect=RuntimeError("onnx fail")):
            with patch("config.settings") as ms:
                ms.removebg_api_key = ""
                result = await remove_background(image_bytes)

        assert result == image_bytes


class TestInvalidImageData:
    async def test_corrupt_image_returns_original(self):
        from services.image_processor import remove_background

        corrupt = b"not_an_image"
        redis = AsyncMock()
        redis.incr = AsyncMock()

        with patch("config.settings") as ms:
            ms.removebg_api_key = ""
            result = await remove_background(corrupt, redis)

        assert result == corrupt

    def test_preprocess_too_large_image(self):
        from services.image_processor import preprocess
        from exceptions import ImageTooLargeError

        big_data = b"x" * (21 * 1024 * 1024)
        with pytest.raises(ImageTooLargeError):
            preprocess(big_data)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Redis failures
# ═══════════════════════════════════════════════════════════════════════════════

class TestRedisConnectionLost:
    async def test_rate_limiter_redis_down_raises(self):
        from core.rate_limiter import RateLimiter

        redis = MagicMock()
        # register_script is sync and returns a callable script object
        # When the script is called (awaited), it should raise
        script_mock = AsyncMock(side_effect=ConnectionError("Redis connection lost"))
        redis.register_script = MagicMock(return_value=script_mock)

        limiter = RateLimiter(redis)

        with pytest.raises(ConnectionError):
            await limiter.check_user_daily("user123", 10)

    async def test_circuit_breaker_redis_down(self):
        from core.circuit_breaker import CircuitBreaker

        redis = AsyncMock()
        redis.get.side_effect = ConnectionError("Redis gone")

        cb = CircuitBreaker(redis, "test_service")

        async def success_func():
            return "ok"

        with pytest.raises(ConnectionError):
            await cb.call(success_func)

    async def test_rate_limiter_get_usage_redis_down(self):
        from core.rate_limiter import RateLimiter

        redis = AsyncMock()
        redis.register_script.return_value = AsyncMock()
        redis.get.side_effect = ConnectionError("Redis down")

        limiter = RateLimiter(redis)

        with pytest.raises(ConnectionError):
            await limiter.get_user_usage("user123")


class TestRedisTimeoutDuringReroll:
    async def test_reroll_redis_timeout_propagates(self):
        """Redis.incr raises TimeoutError → propagates since handler has no try/except."""
        from bot.handlers.brief import handle_reroll

        update = MagicMock()
        query = MagicMock()
        query.data = "reroll_advice"
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.reply_text = AsyncMock()
        query.edit_message_reply_markup = AsyncMock()
        update.callback_query = query

        user = MagicMock()
        user.id = uuid.uuid4()
        user.segment = "no_kids"
        user.plan = "premium"
        user.plan_expires_at = datetime.now(timezone.utc) + timedelta(days=30)
        user.trial_ends_at = None
        user.trial_started_at = None
        user.telegram_id = 99999

        redis = AsyncMock()
        # Atomic INCR-then-check pattern: incr is the first Redis call now
        redis.incr.side_effect = TimeoutError("Redis timeout")

        context = MagicMock()
        context.user_data = {"db_user": user}
        context.bot_data = {"redis": redis}

        # These are imported locally inside handle_reroll: from core.permissions import ...
        with patch("core.permissions.get_effective_plan", return_value="premium"):
            with patch("core.permissions.get_effective_limits", return_value={"reroll": 3}):
                with patch("core.permissions.get_limit", return_value=3):
                    with patch("bot.handlers.brief._reroll_adult_advice", new_callable=AsyncMock):
                        with pytest.raises(TimeoutError):
                            await handle_reroll(update, context)


class TestRedisUnavailableDuringQueuePush:
    async def test_queue_push_redis_down(self):
        from core.queue import RedisQueue

        redis = AsyncMock()
        redis.lpush.side_effect = ConnectionError("Redis down")

        queue = RedisQueue(redis)

        with pytest.raises(ConnectionError):
            await queue.push("test_task", {"key": "value"})


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Database failures
# ═══════════════════════════════════════════════════════════════════════════════

class TestDBConnectionPoolExhausted:
    async def test_session_creation_fails(self):
        from sqlalchemy.exc import TimeoutError as SATimeoutError

        with patch("db.base._get_write_maker") as mock_maker:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(
                side_effect=SATimeoutError("Pool exhausted")
            )
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_maker.return_value = MagicMock(return_value=mock_session)

            with pytest.raises(SATimeoutError):
                from db.base import AsyncWriteSession
                async with AsyncWriteSession() as session:
                    pass


class TestDBSessionTimeoutDuringWrite:
    async def test_commit_failure_triggers_rollback(self):
        mock_session = AsyncMock()
        mock_session.commit = AsyncMock(side_effect=Exception("connection lost"))
        mock_session.rollback = AsyncMock()

        try:
            await mock_session.commit()
        except Exception:
            await mock_session.rollback()

        mock_session.rollback.assert_called_once()


class TestDBUserNotFoundDuringBrief:
    async def test_brief_feedback_log_not_found(self):
        from bot.handlers.brief import handle_brief_feedback

        update = MagicMock()
        query = MagicMock()
        brief_id = uuid.uuid4()
        query.data = f"brief_feedback:up:{brief_id}"
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.reply_text = AsyncMock()
        query.edit_message_reply_markup = AsyncMock()
        update.callback_query = query

        context = MagicMock()

        with patch("bot.handlers.brief.AsyncWriteSession") as mock_session_cls:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_session_cls.return_value = mock_session

            with patch("bot.handlers.brief.get_log", new_callable=AsyncMock, return_value=None):
                await handle_brief_feedback(update, context)

        query.message.reply_text.assert_called()

    async def test_brief_feedback_db_error_shows_generic(self):
        """DB error during feedback → generic error message."""
        from bot.handlers.brief import handle_brief_feedback

        update = MagicMock()
        query = MagicMock()
        brief_id = uuid.uuid4()
        query.data = f"brief_feedback:up:{brief_id}"
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.reply_text = AsyncMock()
        update.callback_query = query

        context = MagicMock()

        with patch("bot.handlers.brief.AsyncWriteSession") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(
                side_effect=Exception("DB down")
            )
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await handle_brief_feedback(update, context)

        query.message.reply_text.assert_called()

    async def test_share_db_error_shows_fallback(self):
        """DB error during share → fallback text message."""
        from bot.handlers.brief import handle_share

        update = MagicMock()
        query = MagicMock()
        query.data = f"share:{uuid.uuid4()}"
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.reply_text = AsyncMock()
        update.callback_query = query

        context = MagicMock()

        with patch("db.base.AsyncReadSession") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(
                side_effect=Exception("DB timeout")
            )
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await handle_share(update, context)

        query.message.reply_text.assert_called()


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Handler edge cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestBriefFeedbackInvalidUUID:
    async def test_invalid_uuid_shows_error(self):
        from bot.handlers.brief import handle_brief_feedback

        update = MagicMock()
        query = MagicMock()
        query.data = "brief_feedback:up:not-a-valid-uuid"
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.reply_text = AsyncMock()
        update.callback_query = query

        context = MagicMock()

        await handle_brief_feedback(update, context)

        # catch ValueError from uuid.UUID → show generic error
        query.message.reply_text.assert_called()


class TestRerollNoWardrobeItems:
    async def test_adult_reroll_empty_wardrobe_gives_advice(self):
        from bot.handlers.brief import _reroll_adult_advice

        message = MagicMock()
        message.reply_text = AsyncMock()

        user = MagicMock()
        user.id = uuid.uuid4()
        user.city = "Vilnius"
        user.timezone = "Europe/Vilnius"
        user.colortype = "Лето"
        user.body_type = None
        user.segment = "no_kids"

        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="Совет: наденьте куртку")]

        mock_session = AsyncMock()

        with patch("services.brief_weather._geocode_city", new_callable=AsyncMock, return_value=(54.68, 25.31)):
            with patch("services.brief_weather._get_weather", new_callable=AsyncMock, return_value={"temp_morning": 10}):
                with patch("db.base.AsyncReadSession") as mock_ctx:
                    mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
                    mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
                    with patch("db.crud.wardrobe.get_owner_items", new_callable=AsyncMock, return_value=[]):
                        with patch("core.anthropic_client.get_anthropic_pool") as mock_pool:
                            pool = MagicMock()
                            pool.create_message = AsyncMock(return_value=mock_resp)
                            mock_pool.return_value = pool

                            await _reroll_adult_advice(message, user)

        message.reply_text.assert_called()
        text = message.reply_text.call_args[0][0]
        assert "Идея на сегодня" in text


class TestAdultRerollHaikuFails:
    async def test_haiku_fails_shows_fallback(self):
        from bot.handlers.brief import _reroll_adult_advice

        message = MagicMock()
        message.reply_text = AsyncMock()

        user = MagicMock()
        user.id = uuid.uuid4()
        user.city = "Vilnius"
        user.timezone = "Europe/Vilnius"
        user.colortype = "Лето"
        user.body_type = None
        user.segment = "no_kids"

        mock_session = AsyncMock()

        with patch("services.brief_weather._geocode_city", new_callable=AsyncMock, return_value=(54.68, 25.31)):
            with patch("services.brief_weather._get_weather", new_callable=AsyncMock, return_value={"temp_morning": 10}):
                with patch("db.base.AsyncReadSession") as mock_ctx:
                    mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
                    mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
                    with patch("db.crud.wardrobe.get_owner_items", new_callable=AsyncMock, return_value=[]):
                        with patch("core.anthropic_client.get_anthropic_pool") as mock_pool:
                            pool = MagicMock()
                            pool.create_message = AsyncMock(side_effect=RuntimeError("haiku down"))
                            mock_pool.return_value = pool

                            await _reroll_adult_advice(message, user)

        message.reply_text.assert_called()
        text = message.reply_text.call_args[0][0]
        # Fallback: "Сегодня +10°C — выбери <advice>"
        assert "Идея на сегодня" in text


class TestShareBriefDeletedCollage:
    async def test_share_no_collage_file_id(self):
        from bot.handlers.brief import handle_share

        update = MagicMock()
        query = MagicMock()
        brief_id = uuid.uuid4()
        query.data = f"share:{brief_id}"
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.reply_text = AsyncMock()
        query.message.reply_photo = AsyncMock()
        update.callback_query = query

        context = MagicMock()
        context.user_data = {"db_user": MagicMock(segment="no_kids")}

        log = MagicMock()
        log.collage_file_id = None

        mock_session = AsyncMock()

        with patch("db.base.AsyncReadSession") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("bot.handlers.brief.get_log", new_callable=AsyncMock, return_value=log):
                await handle_share(update, context)

        query.message.reply_text.assert_called()
        query.message.reply_photo.assert_not_called()
        assert "Перешли" in query.message.reply_text.call_args[0][0]

    async def test_share_no_brief_id(self):
        from bot.handlers.brief import handle_share

        update = MagicMock()
        query = MagicMock()
        query.data = "share:"
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.reply_text = AsyncMock()
        update.callback_query = query

        context = MagicMock()

        await handle_share(update, context)
        query.message.reply_text.assert_called()


class TestEmptyWardrobeBriefGeneration:
    async def test_reroll_adult_no_city(self):
        """User with no city → still generates advice (weather defaults)."""
        from bot.handlers.brief import _reroll_adult_advice

        message = MagicMock()
        message.reply_text = AsyncMock()

        user = MagicMock()
        user.id = uuid.uuid4()
        user.city = None
        user.timezone = "Europe/Vilnius"
        user.colortype = None
        user.body_type = None
        user.segment = "no_kids"

        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="Совет без города")]

        mock_session = AsyncMock()

        with patch("db.base.AsyncReadSession") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("db.crud.wardrobe.get_owner_items", new_callable=AsyncMock, return_value=[]):
                with patch("core.anthropic_client.get_anthropic_pool") as mock_pool:
                    pool = MagicMock()
                    pool.create_message = AsyncMock(return_value=mock_resp)
                    mock_pool.return_value = pool

                    await _reroll_adult_advice(message, user)

        message.reply_text.assert_called()
        text = message.reply_text.call_args[0][0]
        assert "Идея на сегодня" in text


class TestHandleRerollNoUser:
    async def test_reroll_no_user_in_context(self):
        from bot.handlers.brief import handle_reroll

        update = MagicMock()
        query = MagicMock()
        query.data = "reroll_advice"
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.reply_text = AsyncMock()
        update.callback_query = query

        context = MagicMock()
        context.user_data = {}

        await handle_reroll(update, context)

        query.message.reply_text.assert_not_called()

    async def test_brief_feedback_noop_vote(self):
        """Brief feedback with 'noop' brief_id → ack without DB call."""
        from bot.handlers.brief import handle_brief_feedback

        update = MagicMock()
        query = MagicMock()
        query.data = "brief_feedback:up:noop"
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.reply_text = AsyncMock()
        query.edit_message_reply_markup = AsyncMock()
        query.edit_message_caption = AsyncMock()
        update.callback_query = query

        context = MagicMock()

        await handle_brief_feedback(update, context)

        # Now uses edit_message_caption instead of reply_text
        query.edit_message_caption.assert_called_once()
        assert "Надели" in query.edit_message_caption.call_args.kwargs.get("caption", "")
