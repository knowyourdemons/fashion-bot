"""Tests for services/share.py — ShareService."""
import json
from unittest.mock import AsyncMock, patch

import pytest

from services.share import SHARE_BASE_URL, SHARE_TTL, ShareService


@pytest.fixture
def redis_mock():
    r = AsyncMock()
    r.get = AsyncMock(return_value=None)
    r.set = AsyncMock()
    r.ttl = AsyncMock(return_value=SHARE_TTL)
    return r


@pytest.fixture
def svc(redis_mock):
    return ShareService(redis_mock)


@pytest.fixture
def outfit_data():
    return {"items": ["shirt", "pants"], "style": "casual"}


# --- create_share ---


@pytest.mark.asyncio
async def test_create_share_returns_valid_url(svc, outfit_data):
    url = await svc.create_share("user1", outfit_data)
    assert url.startswith(f"{SHARE_BASE_URL}/")
    token = url.split("/")[-1]
    assert len(token) == 32  # uuid4().hex


@pytest.mark.asyncio
async def test_create_share_stores_correct_payload(svc, redis_mock, outfit_data):
    url = await svc.create_share("user1", outfit_data)
    token = url.split("/")[-1]

    redis_mock.set.assert_awaited_once()
    call_args = redis_mock.set.call_args
    key = call_args[0][0]
    stored = json.loads(call_args[0][1])

    assert key == f"share:outfit:{token}"
    assert stored["user_id"] == "user1"
    assert stored["outfit"] == outfit_data
    assert stored["votes"] == {"up": 0, "down": 0}


@pytest.mark.asyncio
async def test_create_share_sets_ttl(svc, redis_mock, outfit_data):
    await svc.create_share("user1", outfit_data)
    call_kwargs = redis_mock.set.call_args
    assert call_kwargs.kwargs.get("ex") == SHARE_TTL or call_kwargs[1].get("ex") == SHARE_TTL


@pytest.mark.asyncio
async def test_create_share_unique_tokens(svc, outfit_data):
    url1 = await svc.create_share("user1", outfit_data)
    url2 = await svc.create_share("user1", outfit_data)
    assert url1 != url2


# --- get_share ---


@pytest.mark.asyncio
async def test_get_share_returns_stored_data(svc, redis_mock):
    payload = {"user_id": "u1", "outfit": {"items": []}, "votes": {"up": 0, "down": 0}}
    redis_mock.get.return_value = json.dumps(payload)

    result = await svc.get_share("abc123")
    redis_mock.get.assert_awaited_with("share:outfit:abc123")
    assert result == payload


@pytest.mark.asyncio
async def test_get_share_returns_none_for_missing(svc, redis_mock):
    redis_mock.get.return_value = None
    result = await svc.get_share("nonexistent")
    assert result is None


# --- vote ---


@pytest.mark.asyncio
async def test_vote_increments_up(svc, redis_mock):
    payload = {"user_id": "u1", "outfit": {}, "votes": {"up": 0, "down": 0}}
    redis_mock.get.return_value = json.dumps(payload)

    result = await svc.vote("tok", "up")
    assert result == {"up": 1, "down": 0}


@pytest.mark.asyncio
async def test_vote_increments_down(svc, redis_mock):
    payload = {"user_id": "u1", "outfit": {}, "votes": {"up": 3, "down": 1}}
    redis_mock.get.return_value = json.dumps(payload)

    result = await svc.vote("tok", "down")
    assert result == {"up": 3, "down": 2}


@pytest.mark.asyncio
async def test_vote_returns_none_if_share_missing(svc, redis_mock):
    redis_mock.get.return_value = None
    result = await svc.vote("missing", "up")
    assert result is None
    redis_mock.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_vote_preserves_ttl(svc, redis_mock):
    payload = {"user_id": "u1", "outfit": {}, "votes": {"up": 0, "down": 0}}
    redis_mock.get.return_value = json.dumps(payload)
    redis_mock.ttl.return_value = 42000

    await svc.vote("tok", "up")
    set_call = redis_mock.set.call_args
    assert set_call.kwargs.get("ex") == 42000 or set_call[1].get("ex") == 42000


@pytest.mark.asyncio
async def test_multiple_votes_accumulate(svc, redis_mock):
    """Simulate multiple votes by chaining — each vote reads the previously stored payload."""
    payload = {"user_id": "u1", "outfit": {}, "votes": {"up": 0, "down": 0}}

    # First vote
    redis_mock.get.return_value = json.dumps(payload)
    result = await svc.vote("tok", "up")
    assert result == {"up": 1, "down": 0}

    # Feed updated payload back for second vote
    updated = {**payload, "votes": result}
    redis_mock.get.return_value = json.dumps(updated)
    result = await svc.vote("tok", "up")
    assert result == {"up": 2, "down": 0}

    # Third vote — down this time
    updated2 = {**payload, "votes": result}
    redis_mock.get.return_value = json.dumps(updated2)
    result = await svc.vote("tok", "down")
    assert result == {"up": 2, "down": 1}


# --- notify_owner ---


@pytest.mark.asyncio
async def test_notify_owner_calls_fn(svc, redis_mock):
    payload = {"user_id": "u42", "outfit": {}, "votes": {"up": 1, "down": 0}}
    redis_mock.get.return_value = json.dumps(payload)

    notify_fn = AsyncMock()
    await svc.notify_owner("tok", "up", notify_fn)

    notify_fn.assert_awaited_once()
    call_kwargs = notify_fn.call_args.kwargs
    assert call_kwargs["user_id"] == "u42"
    assert "message" in call_kwargs


@pytest.mark.asyncio
async def test_notify_owner_skips_missing_share(svc, redis_mock):
    redis_mock.get.return_value = None
    notify_fn = AsyncMock()
    await svc.notify_owner("missing", "up", notify_fn)
    notify_fn.assert_not_awaited()


@pytest.mark.asyncio
async def test_notify_owner_propagates_fn_error(svc, redis_mock):
    """notify_owner does NOT suppress notification_fn errors — they propagate.

    If silent handling is desired, wrap the call in try/except in ShareService.
    """
    payload = {"user_id": "u1", "outfit": {}, "votes": {"up": 0, "down": 0}}
    redis_mock.get.return_value = json.dumps(payload)

    notify_fn = AsyncMock(side_effect=Exception("network error"))
    with pytest.raises(Exception, match="network error"):
        await svc.notify_owner("tok", "down", notify_fn)
