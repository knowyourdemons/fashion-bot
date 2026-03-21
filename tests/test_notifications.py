"""Tests for services/notifications.py — NotificationService."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.queue import QueuePriority
from services.notifications import NotificationService


@pytest.fixture
def mock_queue():
    q = MagicMock()
    q.push = AsyncMock(return_value="task-abc-123")
    return q


@pytest.fixture
def svc(mock_queue):
    return NotificationService(queue=mock_queue)


# ── 1. send_message: correct payload ────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_message_payload(svc, mock_queue):
    result = await svc.send_message("u1", "hello")
    mock_queue.push.assert_awaited_once_with(
        task_type="send_message",
        payload={"user_id": "u1", "message": "hello"},
        priority=QueuePriority.NORMAL,
    )
    assert result == "task-abc-123"


# ── 2. send_message: custom priority ────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_message_custom_priority(svc, mock_queue):
    await svc.send_message("u1", "urgent", priority=QueuePriority.HIGH)
    mock_queue.push.assert_awaited_once_with(
        task_type="send_message",
        payload={"user_id": "u1", "message": "urgent"},
        priority=QueuePriority.HIGH,
    )


# ── 3. send_message: extra kwargs passed through ────────────────────────────

@pytest.mark.asyncio
async def test_send_message_extra_kwargs(svc, mock_queue):
    await svc.send_message("u1", "hi", reply_markup="btn", chat_id=999)
    mock_queue.push.assert_awaited_once_with(
        task_type="send_message",
        payload={"user_id": "u1", "message": "hi", "reply_markup": "btn", "chat_id": 999},
        priority=QueuePriority.NORMAL,
    )


# ── 4. send_morning_brief: payload and HIGH priority ────────────────────────

@pytest.mark.asyncio
async def test_send_morning_brief_payload(svc, mock_queue):
    brief = {"items": [1, 2, 3], "weather": "sunny"}
    result = await svc.send_morning_brief("u2", brief)
    mock_queue.push.assert_awaited_once_with(
        task_type="send_morning_brief",
        payload={"user_id": "u2", "items": [1, 2, 3], "weather": "sunny"},
        priority=QueuePriority.HIGH,
    )
    assert result == "task-abc-123"


# ── 5. send_morning_brief: empty brief_data ─────────────────────────────────

@pytest.mark.asyncio
async def test_send_morning_brief_empty_data(svc, mock_queue):
    await svc.send_morning_brief("u2", {})
    mock_queue.push.assert_awaited_once_with(
        task_type="send_morning_brief",
        payload={"user_id": "u2"},
        priority=QueuePriority.HIGH,
    )


# ── 6. send_growth_alert: payload and NORMAL priority ───────────────────────

@pytest.mark.asyncio
async def test_send_growth_alert(svc, mock_queue):
    result = await svc.send_growth_alert("u3", "child-1")
    mock_queue.push.assert_awaited_once_with(
        task_type="send_growth_alert",
        payload={"user_id": "u3", "child_id": "child-1"},
        priority=QueuePriority.NORMAL,
    )
    assert result == "task-abc-123"


# ── 7. send_birthday_alert: payload and NORMAL priority ─────────────────────

@pytest.mark.asyncio
async def test_send_birthday_alert(svc, mock_queue):
    result = await svc.send_birthday_alert("u4", "child-2")
    mock_queue.push.assert_awaited_once_with(
        task_type="send_birthday_alert",
        payload={"user_id": "u4", "child_id": "child-2"},
        priority=QueuePriority.NORMAL,
    )
    assert result == "task-abc-123"


# ── 8. send_subscription_expiry ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_subscription_expiry(svc, mock_queue):
    result = await svc.send_subscription_expiry("u5", 3)
    mock_queue.push.assert_awaited_once_with(
        task_type="send_subscription_expiry",
        payload={"user_id": "u5", "days_left": 3},
        priority=QueuePriority.NORMAL,
    )
    assert result == "task-abc-123"


# ── 9. send_reminder: LOW priority + reminder_type 3 ────────────────────────

@pytest.mark.asyncio
async def test_send_reminder_3_days(svc, mock_queue):
    result = await svc.send_reminder("u6", 3)
    mock_queue.push.assert_awaited_once_with(
        task_type="send_reminder",
        payload={"user_id": "u6", "reminder_type": 3},
        priority=QueuePriority.LOW,
    )
    assert result == "task-abc-123"


# ── 10. send_reminder: reminder_type 7 ──────────────────────────────────────

@pytest.mark.asyncio
async def test_send_reminder_7_days(svc, mock_queue):
    await svc.send_reminder("u6", 7)
    mock_queue.push.assert_awaited_once_with(
        task_type="send_reminder",
        payload={"user_id": "u6", "reminder_type": 7},
        priority=QueuePriority.LOW,
    )


# ── 11. send_reminder: reminder_type 30 ─────────────────────────────────────

@pytest.mark.asyncio
async def test_send_reminder_30_days(svc, mock_queue):
    await svc.send_reminder("u6", 30)
    mock_queue.push.assert_awaited_once_with(
        task_type="send_reminder",
        payload={"user_id": "u6", "reminder_type": 30},
        priority=QueuePriority.LOW,
    )


# ── 12. send_upgrade_prompt: payload + kwargs ────────────────────────────────

@pytest.mark.asyncio
async def test_send_upgrade_prompt(svc, mock_queue):
    result = await svc.send_upgrade_prompt("u7", "limit_reached", feature="chat")
    mock_queue.push.assert_awaited_once_with(
        task_type="send_upgrade_prompt",
        payload={"user_id": "u7", "trigger": "limit_reached", "feature": "chat"},
        priority=QueuePriority.NORMAL,
    )
    assert result == "task-abc-123"


# ── 13. Queue push failure propagates exception ─────────────────────────────

@pytest.mark.asyncio
async def test_queue_push_failure_propagates(svc, mock_queue):
    mock_queue.push = AsyncMock(side_effect=ConnectionError("Redis down"))
    with pytest.raises(ConnectionError, match="Redis down"):
        await svc.send_message("u1", "fail")


# ── 14. send_upgrade_prompt without extra kwargs ─────────────────────────────

@pytest.mark.asyncio
async def test_send_upgrade_prompt_no_kwargs(svc, mock_queue):
    await svc.send_upgrade_prompt("u8", "trial_ending")
    mock_queue.push.assert_awaited_once_with(
        task_type="send_upgrade_prompt",
        payload={"user_id": "u8", "trigger": "trial_ending"},
        priority=QueuePriority.NORMAL,
    )


# ── 15. Queue failure propagates for non-message methods ────────────────────

@pytest.mark.asyncio
async def test_queue_failure_propagates_morning_brief(svc, mock_queue):
    mock_queue.push = AsyncMock(side_effect=RuntimeError("queue full"))
    with pytest.raises(RuntimeError, match="queue full"):
        await svc.send_morning_brief("u1", {"items": []})
