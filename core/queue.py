"""
Redis queue wrapper.
Очереди: high, normal, low, dead.
Используется для общения между bot/api и worker.
"""
import json
import uuid
from datetime import datetime
from enum import Enum
from typing import Any

import redis.asyncio as aioredis
import structlog

logger = structlog.get_logger()


class QueuePriority(str, Enum):
    HIGH = "queue:high"        # brief, анализ фото
    NORMAL = "queue:normal"    # аналитика
    LOW = "queue:low"          # отчёты
    DEAD = "queue:dead"        # ошибки


class TaskMessage:
    def __init__(
        self,
        task_type: str,
        payload: dict[str, Any],
        task_id: str | None = None,
        created_at: str | None = None,
        retry_count: int = 0,
    ) -> None:
        self.task_id = task_id or str(uuid.uuid4())
        self.task_type = task_type
        self.payload = payload
        self.created_at = created_at or datetime.utcnow().isoformat()
        self.retry_count = retry_count

    def to_json(self) -> str:
        return json.dumps({
            "task_id": self.task_id,
            "task_type": self.task_type,
            "payload": self.payload,
            "created_at": self.created_at,
            "retry_count": self.retry_count,
        })

    @classmethod
    def from_json(cls, data: str) -> "TaskMessage":
        d = json.loads(data)
        return cls(**d)


class RedisQueue:
    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client

    async def push(
        self,
        task_type: str,
        payload: dict[str, Any],
        priority: QueuePriority = QueuePriority.NORMAL,
    ) -> str:
        msg = TaskMessage(task_type=task_type, payload=payload)
        await self._redis.lpush(priority.value, msg.to_json())
        logger.info(
            "queue.push",
            task_id=msg.task_id,
            task_type=task_type,
            priority=priority.value,
        )
        return msg.task_id

    async def pop(
        self,
        queues: list[QueuePriority],
        timeout: int = 5,
    ) -> TaskMessage | None:
        """BLPOP с приоритетом — сначала high, потом normal, low."""
        keys = [q.value for q in queues]
        result = await self._redis.blpop(keys, timeout=timeout)
        if result is None:
            return None
        _, data = result
        return TaskMessage.from_json(data)

    async def move_to_dead(self, msg: TaskMessage, error: str) -> None:
        msg.payload["_error"] = error
        await self._redis.lpush(QueuePriority.DEAD.value, msg.to_json())
        logger.error(
            "queue.dead",
            task_id=msg.task_id,
            task_type=msg.task_type,
            error=error,
        )

    async def store_result(self, task_id: str, result: dict[str, Any]) -> None:
        key = f"task:result:{task_id}"
        await self._redis.set(key, json.dumps(result), ex=3600)

    async def get_result(self, task_id: str) -> dict[str, Any] | None:
        key = f"task:result:{task_id}"
        data = await self._redis.get(key)
        return json.loads(data) if data else None
