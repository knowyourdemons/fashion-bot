"""FastAPI application."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration

from config import settings
from api.middleware.request_id import RequestIdMiddleware
from api.routes import auth, wardrobe, brief, onboarding, billing, webhooks


def create_app() -> FastAPI:
    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            integrations=[FastApiIntegration()],
            environment=settings.environment,
        )

    app = FastAPI(
        title="Fashion Bot API",
        version="1.0.0",
        docs_url="/docs" if settings.environment == "dev" else None,
    )

    app.add_middleware(RequestIdMiddleware)
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

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app
