"""Абстрактный PaymentProvider."""
from abc import ABC, abstractmethod
from typing import Any


class PaymentProvider(ABC):
    @abstractmethod
    async def create_invoice(
        self,
        user_id: str,
        plan: str,
        period: str,  # "monthly" | "annual"
    ) -> dict[str, Any]:
        """Создаёт платёж. Возвращает данные для отправки пользователю."""

    @abstractmethod
    async def verify_payment(self, payload: dict[str, Any]) -> bool:
        """Верифицирует входящий webhook/callback."""

    @abstractmethod
    async def cancel_subscription(self, subscription_id: str) -> bool:
        """Отменяет подписку."""

    @abstractmethod
    async def pause_subscription(self, subscription_id: str) -> bool:
        """Ставит подписку на паузу."""

    @abstractmethod
    async def resume_subscription(self, subscription_id: str) -> bool:
        """Возобновляет подписку."""
