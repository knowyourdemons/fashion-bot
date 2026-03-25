"""
Пул API ключей Anthropic с автофейловером и circuit breaker.
PRIMARY: claude-haiku-4-5-20251001
FALLBACK: claude-sonnet-4-6
"""
import asyncio
from typing import Any

import anthropic
import redis.asyncio as aioredis
import structlog

from config import settings
from core.circuit_breaker import CircuitBreaker
from core.rate_limiter import RateLimiter
from exceptions import CircuitBreakerOpenError, RateLimitError

logger = structlog.get_logger()

PRIMARY_MODEL = "claude-haiku-4-5-20251001"
FALLBACK_MODEL = "claude-sonnet-4-6"
MAX_RETRIES = 3


class AnthropicPool:
    """Пул Anthropic клиентов с round-robin + failover."""

    def __init__(self, redis_client: aioredis.Redis) -> None:
        keys = settings.anthropic_keys_list
        if not keys:
            raise ValueError("ANTHROPIC_API_KEYS не задан")

        self._clients = [anthropic.AsyncAnthropic(api_key=k) for k in keys]
        self._key_ids = [f"key_{i}" for i in range(len(keys))]
        self._counter = 0
        self._lock = asyncio.Lock()
        self._rate_limiter = RateLimiter(redis_client)
        self._circuit_breakers = {
            kid: CircuitBreaker(redis_client, f"anthropic_{kid}")
            for kid in self._key_ids
        }

    async def _next_client(self) -> tuple[anthropic.AsyncAnthropic, str]:
        async with self._lock:
            idx = self._counter % len(self._clients)
            self._counter += 1
        return self._clients[idx], self._key_ids[idx]

    async def create_message(
        self,
        *,
        messages: list[dict[str, Any]],
        max_tokens: int = 1024,
        model: str = PRIMARY_MODEL,
        use_cache: bool = False,
        system: str | list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> anthropic.types.Message:
        """Отправляет запрос с автофейловером по ключам."""
        if isinstance(system, str):
            system = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]

        last_error: Exception | None = None

        # Vision calls process images and need more time
        has_vision = any(
            isinstance(m.get("content"), list)
            and any(c.get("type") == "image" for c in m["content"] if isinstance(c, dict))
            for m in messages
        )
        timeout_seconds = 60 if has_vision else 30

        for attempt in range(MAX_RETRIES):
            client, key_id = await self._next_client()
            cb = self._circuit_breakers[key_id]

            try:
                await self._rate_limiter.check_api_key_rpm(key_id)

                call_kwargs = dict(kwargs)
                if system is not None:
                    call_kwargs["system"] = system

                async with asyncio.timeout(timeout_seconds):
                    response = await cb.call(
                        client.messages.create,
                        model=model,
                        max_tokens=max_tokens,
                        messages=messages,
                        **call_kwargs,
                    )
                cache_read = getattr(response.usage, "cache_read_input_tokens", 0)
                cache_write = getattr(response.usage, "cache_creation_input_tokens", 0)
                logger.info(
                    "anthropic.request.ok",
                    model=model,
                    key_id=key_id,
                    attempt=attempt,
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                )
                if cache_read or cache_write:
                    logger.info("anthropic.cache", cache_read=cache_read, cache_write=cache_write)

                # Persist usage to Redis (survives container restarts)
                try:
                    from datetime import date
                    day = date.today().isoformat()
                    inp = response.usage.input_tokens
                    out = response.usage.output_tokens
                    pipe = self._redis.pipeline(transaction=False)
                    pipe.hincrby(f"api_usage:{day}", f"{model}:calls", 1)
                    pipe.hincrby(f"api_usage:{day}", f"{model}:input", inp)
                    pipe.hincrby(f"api_usage:{day}", f"{model}:output", out)
                    pipe.hincrby(f"api_usage:{day}", f"{model}:cache_read", cache_read or 0)
                    pipe.hincrby(f"api_usage:{day}", f"{model}:cache_write", cache_write or 0)
                    pipe.expire(f"api_usage:{day}", 90 * 86400)  # keep 90 days
                    await pipe.execute()
                except Exception:
                    pass  # don't break on tracking failure

                return response

            except TimeoutError:
                logger.warning(
                    "anthropic.request.timeout",
                    key_id=key_id,
                    attempt=attempt,
                    timeout=timeout_seconds,
                )
                last_error = TimeoutError(f"Anthropic API timeout ({timeout_seconds}s)")
                continue

            except RateLimitError:
                logger.warning("anthropic.key.rate_limited", key_id=key_id)
                last_error = RateLimitError(f"Ключ {key_id} исчерпан")
                continue

            except CircuitBreakerOpenError:
                logger.warning("anthropic.key.circuit_open", key_id=key_id)
                last_error = CircuitBreakerOpenError(f"Ключ {key_id} недоступен")
                continue

            except anthropic.RateLimitError:
                logger.warning("anthropic.api.rate_limit", key_id=key_id)
                last_error = RateLimitError("Anthropic API: превышен лимит запросов")
                await asyncio.sleep(1)
                continue

            except anthropic.APIStatusError as e:
                if e.status_code == 529:
                    logger.warning("anthropic.api.overloaded", key_id=key_id, attempt=attempt)
                    last_error = e
                    await asyncio.sleep(2 ** attempt)
                    continue
                logger.error("anthropic.request.api_error", key_id=key_id, status=e.status_code, error=str(e))
                last_error = e
                continue

            except Exception as e:
                logger.error("anthropic.request.error", key_id=key_id, error=str(e))
                last_error = e
                continue

        # Последняя попытка с fallback моделью
        if model == PRIMARY_MODEL:
            logger.warning("anthropic.fallback_model", fallback=FALLBACK_MODEL)
            return await self.create_message(
                messages=messages,
                max_tokens=max_tokens,
                model=FALLBACK_MODEL,
                **kwargs,
            )

        raise last_error or RuntimeError("Все Anthropic ключи недоступны")

    async def has_clothing(self, photo_bytes: bytes) -> bool:
        """Предфильтр: есть ли одежда на фото (~100 токенов)."""
        import base64

        response = await self.create_message(
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": base64.standard_b64encode(photo_bytes).decode(),
                        },
                    },
                    {"type": "text", "text": "Есть одежда на фото? Ответь только: да или нет"},
                ],
            }],
            max_tokens=10,
        )
        text = response.content[0].text.lower() if response.content else ""
        return "да" in text


# Singleton — инициализируется в main.py
_pool: AnthropicPool | None = None


def get_anthropic_pool() -> AnthropicPool:
    if _pool is None:
        raise RuntimeError("AnthropicPool не инициализирован. Вызовите init_anthropic_pool().")
    return _pool


def init_anthropic_pool(redis_client: aioredis.Redis) -> AnthropicPool:
    global _pool
    _pool = AnthropicPool(redis_client)
    return _pool
