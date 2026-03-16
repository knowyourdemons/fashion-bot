"""
Все уведомления через Redis queue.
Никогда не отправляем напрямую из сервисов — только через очередь.
"""
from typing import Any

import structlog

from core.queue import RedisQueue, QueuePriority

logger = structlog.get_logger()


class NotificationService:
    def __init__(self, queue: RedisQueue) -> None:
        self._queue = queue

    async def send_message(
        self,
        user_id: str,
        message: str,
        priority: QueuePriority = QueuePriority.NORMAL,
        **extra: Any,
    ) -> str:
        return await self._queue.push(
            task_type="send_message",
            payload={"user_id": user_id, "message": message, **extra},
            priority=priority,
        )

    async def send_morning_brief(
        self,
        user_id: str,
        brief_data: dict[str, Any],
    ) -> str:
        return await self._queue.push(
            task_type="send_morning_brief",
            payload={"user_id": user_id, **brief_data},
            priority=QueuePriority.HIGH,
        )

    async def send_growth_alert(self, user_id: str, child_id: str) -> str:
        return await self._queue.push(
            task_type="send_growth_alert",
            payload={"user_id": user_id, "child_id": child_id},
            priority=QueuePriority.NORMAL,
        )

    async def send_birthday_alert(self, user_id: str, child_id: str) -> str:
        return await self._queue.push(
            task_type="send_birthday_alert",
            payload={"user_id": user_id, "child_id": child_id},
            priority=QueuePriority.NORMAL,
        )

    async def send_subscription_expiry(self, user_id: str, days_left: int) -> str:
        return await self._queue.push(
            task_type="send_subscription_expiry",
            payload={"user_id": user_id, "days_left": days_left},
            priority=QueuePriority.NORMAL,
        )

    async def send_reminder(self, user_id: str, reminder_type: int) -> str:
        """reminder_type: 3, 7, или 30 (дней молчания)."""
        return await self._queue.push(
            task_type="send_reminder",
            payload={"user_id": user_id, "reminder_type": reminder_type},
            priority=QueuePriority.LOW,
        )

    async def send_upgrade_prompt(
        self,
        user_id: str,
        trigger: str,
        **kwargs: Any,
    ) -> str:
        return await self._queue.push(
            task_type="send_upgrade_prompt",
            payload={"user_id": user_id, "trigger": trigger, **kwargs},
            priority=QueuePriority.NORMAL,
        )
