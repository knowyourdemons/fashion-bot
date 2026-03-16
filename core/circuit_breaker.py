"""
Circuit breaker паттерн через Redis.
States: closed → open → half_open → closed
После 5 ошибок: открыть на 60 сек.
"""
import time
from enum import Enum
from typing import Any, Callable, Awaitable

import redis.asyncio as aioredis
import structlog

from exceptions import CircuitBreakerOpenError

logger = structlog.get_logger()


class CBState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(
        self,
        redis_client: aioredis.Redis,
        service: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
    ) -> None:
        self._redis = redis_client
        self._service = service
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._key_state = f"circuit:{service}:state"
        self._key_failures = f"circuit:{service}:failures"
        self._key_last_failure = f"circuit:{service}:last_failure"

    async def get_state(self) -> CBState:
        state = await self._redis.get(self._key_state)
        if state is None:
            return CBState.CLOSED
        return CBState(state.decode())

    async def call(
        self,
        func: Callable[..., Awaitable[Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        state = await self.get_state()

        if state == CBState.OPEN:
            # Проверяем, прошло ли recovery_timeout
            last_failure = await self._redis.get(self._key_last_failure)
            if last_failure and (time.time() - float(last_failure)) > self._recovery_timeout:
                await self._set_state(CBState.HALF_OPEN)
            else:
                raise CircuitBreakerOpenError(
                    f"Сервис {self._service} временно недоступен. Попробуйте позже."
                )

        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
        except CircuitBreakerOpenError:
            raise
        except Exception as e:
            await self._on_failure()
            raise e

    async def _on_success(self) -> None:
        await self._redis.delete(self._key_failures)
        await self._set_state(CBState.CLOSED)

    async def _on_failure(self) -> None:
        failures = await self._redis.incr(self._key_failures)
        await self._redis.set(self._key_last_failure, time.time())

        if failures >= self._failure_threshold:
            await self._set_state(CBState.OPEN)
            logger.warning(
                "circuit_breaker.opened",
                service=self._service,
                failures=failures,
            )

    async def _set_state(self, state: CBState) -> None:
        await self._redis.set(self._key_state, state.value, ex=self._recovery_timeout * 2)
