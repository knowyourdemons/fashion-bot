"""
"Спросить подругу" — share outfit по ссылке.
Share token хранится в Redis TTL=86400.
"""
import json
import uuid
from typing import Any

import redis.asyncio as aioredis
import structlog

logger = structlog.get_logger()

SHARE_BASE_URL = "https://fashionbot.app/ask"
SHARE_TTL = 86400  # 24 часа


class ShareService:
    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client

    async def create_share(
        self,
        user_id: str,
        outfit_data: dict[str, Any],
    ) -> str:
        """Создаёт share токен. Возвращает URL."""
        token = uuid.uuid4().hex
        key = f"share:outfit:{token}"

        payload = {
            "user_id": user_id,
            "outfit": outfit_data,
            "votes": {"up": 0, "down": 0},
        }
        await self._redis.set(key, json.dumps(payload), ex=SHARE_TTL)
        logger.info("share.created", user_id=user_id, token=token)
        return f"{SHARE_BASE_URL}/{token}"

    async def get_share(self, token: str) -> dict[str, Any] | None:
        key = f"share:outfit:{token}"
        data = await self._redis.get(key)
        return json.loads(data) if data else None

    async def vote(self, token: str, vote: str) -> dict[str, int] | None:
        """vote: 'up' или 'down'. Возвращает текущие голоса."""
        key = f"share:outfit:{token}"
        data = await self._redis.get(key)
        if not data:
            return None

        payload = json.loads(data)
        if vote in ("up", "down"):
            payload["votes"][vote] += 1

        # Сохраняем с тем же TTL (не сбрасываем)
        ttl = await self._redis.ttl(key)
        await self._redis.set(key, json.dumps(payload), ex=max(ttl, 1))
        return payload["votes"]

    async def notify_owner(
        self,
        token: str,
        vote: str,
        notification_fn: Any,  # callable
    ) -> None:
        """Уведомляет владельца о новом голосе."""
        data = await self.get_share(token)
        if not data:
            return
        await notification_fn(
            user_id=data["user_id"],
            message=f"Подруга проголосовала: {'👍' if vote == 'up' else '👎'}",
        )
