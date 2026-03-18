"""Tests for webhook security — Telegram secret token + Stripe HMAC."""
import hmac
import hashlib
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi.testclient import TestClient
from fastapi import FastAPI


# ── Вспомогательный mini-app для тестирования ────────────────────────────────

def _make_test_app(telegram_secret: str = "test_secret_token"):
    """Создаёт тестовое FastAPI приложение с webhook router."""
    from api.routes.webhooks import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/webhooks")

    # Fake tg_app в state
    tg_app_mock = MagicMock()
    tg_app_mock.bot = AsyncMock()
    tg_app_mock.process_update = AsyncMock()
    app.state.tg_app = tg_app_mock

    return app, tg_app_mock


# ── Telegram webhook security ─────────────────────────────────────────────────

class TestTelegramWebhookSecurity:

    def test_valid_secret_returns_200(self):
        """Правильный X-Telegram-Bot-Api-Secret-Token → 200."""
        app, _ = _make_test_app()
        with patch("config.settings") as mock_s:
            mock_s.telegram_webhook_secret = "test_secret_token"
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/webhooks/telegram",
                    json={"update_id": 1},
                    headers={"X-Telegram-Bot-Api-Secret-Token": "test_secret_token"},
                )
        assert resp.status_code == 200

    def test_invalid_secret_returns_403(self):
        """Неправильный токен → 403."""
        app, _ = _make_test_app()
        with patch("config.settings") as mock_s:
            mock_s.telegram_webhook_secret = "test_secret_token"
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/webhooks/telegram",
                    json={"update_id": 1},
                    headers={"X-Telegram-Bot-Api-Secret-Token": "wrong_token"},
                )
        assert resp.status_code == 403

    def test_no_secret_header_returns_403(self):
        """Без заголовка → 403 (если secret задан в настройках)."""
        app, _ = _make_test_app()
        with patch("config.settings") as mock_s:
            mock_s.telegram_webhook_secret = "test_secret_token"
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/webhooks/telegram",
                    json={"update_id": 1},
                )
        assert resp.status_code == 403

    def test_no_secret_configured_allows_all(self):
        """Если telegram_webhook_secret не задан → запросы проходят."""
        app, _ = _make_test_app()
        with patch("config.settings") as mock_s:
            mock_s.telegram_webhook_secret = ""
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/webhooks/telegram",
                    json={"update_id": 1},
                )
        # Без секрета пропускает всё (не 403)
        assert resp.status_code != 403


# ── Stripe webhook security ───────────────────────────────────────────────────

class TestStripeWebhookSecurity:

    def _make_sig(self, secret: str, body: bytes, ts: str = "1234567890") -> str:
        signed = f"{ts}.".encode() + body
        sig = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        return f"t={ts},v1={sig}"

    def test_valid_stripe_signature_returns_200(self):
        """Корректная Stripe подпись → 200."""
        app, _ = _make_test_app()
        secret = "whsec_test"
        body = json.dumps({"type": "payment_intent.created"}).encode()
        sig_header = self._make_sig(secret, body)

        with patch("config.settings") as mock_s:
            mock_s.stripe_webhook_secret = secret
            mock_s.telegram_webhook_secret = ""
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/webhooks/stripe",
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        "stripe-signature": sig_header,
                    },
                )
        assert resp.status_code == 200

    def test_invalid_stripe_signature_returns_400(self):
        """Неправильная Stripe подпись → 400."""
        app, _ = _make_test_app()
        body = json.dumps({"type": "checkout.session.completed"}).encode()

        with patch("config.settings") as mock_s:
            mock_s.stripe_webhook_secret = "whsec_real_secret"
            mock_s.telegram_webhook_secret = ""
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/webhooks/stripe",
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        "stripe-signature": "t=123,v1=invalidsig",
                    },
                )
        assert resp.status_code == 400

    def test_no_stripe_secret_skips_verification(self):
        """Без stripe_webhook_secret верификация пропускается."""
        app, _ = _make_test_app()
        body = json.dumps({"type": "payment_intent.created"}).encode()

        with patch("config.settings") as mock_s:
            mock_s.stripe_webhook_secret = ""
            mock_s.telegram_webhook_secret = ""
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/webhooks/stripe",
                    content=body,
                    headers={"Content-Type": "application/json"},
                )
        assert resp.status_code == 200

    def test_checkout_completed_triggers_activation(self):
        """checkout.session.completed → вызывает _activate_premium_after_payment."""
        app, _ = _make_test_app()
        event = {
            "type": "checkout.session.completed",
            "data": {"object": {
                "metadata": {"user_id": "195169", "plan": "premium", "period": "monthly"},
                "subscription": "sub_123",
            }},
        }
        body = json.dumps(event).encode()

        with patch("config.settings") as mock_s:
            mock_s.stripe_webhook_secret = ""
            mock_s.telegram_webhook_secret = ""
            with patch("api.routes.webhooks._activate_premium_after_payment", new_callable=AsyncMock) as mock_activate:
                with TestClient(app) as client:
                    resp = client.post(
                        "/api/v1/webhooks/stripe",
                        content=body,
                        headers={"Content-Type": "application/json"},
                    )
        assert resp.status_code == 200
        mock_activate.assert_called_once()
        call_kwargs = mock_activate.call_args
        assert call_kwargs.kwargs.get("telegram_user_id") == 195169


# ── HMAC верификация (unit) ───────────────────────────────────────────────────

class TestHMACVerification:
    """Unit тесты HMAC логики без HTTP."""

    def test_hmac_correct(self):
        secret = "test_secret"
        body = b"payload"
        ts = "1000"
        signed = f"{ts}.".encode() + body
        sig = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        sig_header = f"t={ts},v1={sig}"

        parts = {p.split("=", 1)[0]: p.split("=", 1)[1] for p in sig_header.split(",") if "=" in p}
        signed_payload = f"{parts['t']}.".encode() + body
        expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
        assert hmac.compare_digest(expected, parts["v1"]) is True

    def test_hmac_wrong_body(self):
        secret = "test_secret"
        ts = "1000"
        body = b"real_payload"
        signed = f"{ts}.".encode() + body
        sig = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()

        # Пытаемся верифицировать с другим телом
        wrong_body = b"tampered"
        signed_payload = f"{ts}.".encode() + wrong_body
        expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
        assert hmac.compare_digest(expected, sig) is False

    def test_hmac_wrong_secret(self):
        ts = "1000"
        body = b"payload"
        signed = f"{ts}.".encode() + body
        sig = hmac.new(b"real_secret", signed, hashlib.sha256).hexdigest()
        expected = hmac.new(b"wrong_secret", signed, hashlib.sha256).hexdigest()
        assert hmac.compare_digest(expected, sig) is False
