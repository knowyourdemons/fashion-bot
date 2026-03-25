"""FastAPI application."""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration

from config import settings
from api.middleware.rate_limit import RateLimitMiddleware
from api.middleware.request_id import RequestIdMiddleware
from api.routes import auth, wardrobe, brief, onboarding, billing, webhooks


def create_app() -> FastAPI:
    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            integrations=[FastApiIntegration()],
            environment=settings.environment,
            send_default_pii=True,
        )

    app = FastAPI(
        title="Fashion Bot API",
        version="1.0.0",
        docs_url="/docs" if settings.environment == "dev" else None,
    )

    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(RateLimitMiddleware)
    # В продакшене разрешаем только внутренние/webhook источники.
    # Telegram и Stripe используют server-side запросы — CORS им не нужен.
    cors_origins = ["*"] if settings.environment == "dev" else []
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=["POST", "GET"],
        allow_headers=["Content-Type", "X-Request-ID"],
    )

    app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
    app.include_router(wardrobe.router, prefix="/api/v1/wardrobe", tags=["wardrobe"])
    app.include_router(brief.router, prefix="/api/v1/brief", tags=["brief"])
    app.include_router(onboarding.router, prefix="/api/v1/onboarding", tags=["onboarding"])
    app.include_router(billing.router, prefix="/api/v1/billing", tags=["billing"])
    app.include_router(webhooks.router, prefix="/api/v1/webhooks", tags=["webhooks"])

    @app.post("/api/v1/test-survey")
    async def test_survey(request: Request) -> dict:
        """Receive test survey results and forward to admin via Telegram."""
        try:
            import json
            import httpx
            body = await request.json()
            # Format for Telegram
            text = "📋 Результаты тестирования:\n\n"
            for key, val in body.items():
                if isinstance(val, (dict, list)):
                    val = json.dumps(val, ensure_ascii=False)[:200]
                text += f"**{key}**: {val}\n"
            # Truncate to Telegram limit
            text = text[:4000]
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                    json={"chat_id": "195169", "text": text, "parse_mode": "Markdown"},
                )
            return {"status": "ok"}
        except Exception as e:
            import structlog
            structlog.get_logger().warning("test_survey.error", error=str(e))
            return {"status": "ok"}  # Don't show error to user

    @app.get("/health")
    async def health() -> dict:
        checks: dict = {"status": "ok"}
        try:
            from core.redis import get_redis
            redis = get_redis()
            await redis.ping()
            checks["redis"] = "ok"
        except Exception as e:
            checks["redis"] = str(e)
            checks["status"] = "degraded"
        try:
            from sqlalchemy import text
            from db.base import AsyncReadSession
            async with AsyncReadSession() as session:
                await session.execute(text("SELECT 1"))
            checks["db"] = "ok"
        except Exception as e:
            checks["db"] = str(e)
            checks["status"] = "degraded"
        status_code = 200 if checks["status"] == "ok" else 503
        from fastapi.responses import JSONResponse
        return JSONResponse(content=checks, status_code=status_code)

    # Landing page at root
    landing_dir = Path(__file__).resolve().parent.parent / "landing"
    if landing_dir.is_dir():
        from fastapi.responses import FileResponse

        @app.get("/")
        async def landing():
            return FileResponse(landing_dir / "index.html")

        @app.get("/test.html")
        async def test_page():
            path = landing_dir / "test.html"
            if path.exists():
                return FileResponse(path)
            from fastapi.responses import PlainTextResponse
            return PlainTextResponse("Not found", status_code=404)

        app.mount("/static", StaticFiles(directory=str(landing_dir)), name="landing")

    return app
