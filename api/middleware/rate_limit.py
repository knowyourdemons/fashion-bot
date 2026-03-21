"""Redis-based per-IP rate limiting middleware for FastAPI.

Limits API endpoints (excluding webhooks and health check) to 60 req/min per IP.
Uses Redis INCR + EXPIRE for atomic counting. Falls back to allowing requests
if Redis is unavailable.
"""
import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = structlog.get_logger()

# 60 requests per 60-second window
RATE_LIMIT = 60
WINDOW_SECONDS = 60

# Paths that skip rate limiting
SKIP_PATHS = frozenset({"/health"})
# Path prefixes that skip rate limiting (webhooks)
SKIP_PREFIXES = ("/api/v1/webhooks/",)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip rate limiting for health checks and webhooks
        if path in SKIP_PATHS or any(path.startswith(p) for p in SKIP_PREFIXES):
            return await call_next(request)

        # Only rate-limit API paths
        if not path.startswith("/api/"):
            return await call_next(request)

        client_ip = _get_client_ip(request)
        key = f"ratelimit:{client_ip}"

        try:
            from core.redis import get_redis
            redis = get_redis()

            # Atomic increment + set expiry if new key
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, WINDOW_SECONDS)

            if count > RATE_LIMIT:
                ttl = await redis.ttl(key)
                logger.warning(
                    "rate_limit.exceeded",
                    client_ip=client_ip,
                    count=count,
                    path=path,
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "Too Many Requests",
                        "retry_after": max(ttl, 1),
                    },
                    headers={"Retry-After": str(max(ttl, 1))},
                )
        except Exception:
            # If Redis is down, allow the request through
            logger.debug("rate_limit.redis_unavailable", client_ip=client_ip)

        return await call_next(request)


def _get_client_ip(request: Request) -> str:
    """Extract client IP, respecting X-Forwarded-For from Cloudflare tunnel."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip
    return request.client.host if request.client else "unknown"
