"""Tests for billing — Stars, Stripe, permissions prices."""
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

# Пропустить весь файл если основные зависимости не установлены (локальная среда)
structlog = pytest.importorskip("structlog", reason="structlog not installed")
telegram = pytest.importorskip("telegram", reason="python-telegram-bot not installed")


def _run(coro):
    """Запуск корутины синхронно."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Stars provider ────────────────────────────────────────────────────────────

class TestStarsProvider:

    def test_plan_prices_stars_amounts(self):
        from billing.stars import PLAN_PRICES_STARS
        assert PLAN_PRICES_STARS["premium_monthly"] == 700
        assert PLAN_PRICES_STARS["premium_quarterly"] == 1700
        assert PLAN_PRICES_STARS["premium_yearly"] == 5500

    def test_no_legacy_plans(self):
        from billing.stars import PLAN_PRICES_STARS
        assert "basic" not in PLAN_PRICES_STARS
        assert "family" not in PLAN_PRICES_STARS

    def test_create_invoice_premium_monthly(self):
        from billing.stars import StarsProvider
        p = StarsProvider()
        result = _run(p.create_invoice(user_id="195169", plan_key="premium_monthly"))
        assert result["currency"] == "XTR"
        assert result["prices"][0]["amount"] == 700
        assert result["provider_token"] == ""
        assert result["payload"] == "premium:premium_monthly:195169"

    def test_create_invoice_premium_yearly(self):
        from billing.stars import StarsProvider
        p = StarsProvider()
        result = _run(p.create_invoice(user_id="195169", plan_key="premium_yearly"))
        assert result["prices"][0]["amount"] == 5500

    def test_create_invoice_unknown_plan_raises(self):
        from billing.stars import StarsProvider
        p = StarsProvider()
        with pytest.raises(ValueError, match="Неизвестный plan_key"):
            _run(p.create_invoice(user_id="1", plan_key="basic"))

    def test_create_invoice_unknown_plan_legacy_raises(self):
        from billing.stars import StarsProvider
        p = StarsProvider()
        with pytest.raises(ValueError):
            _run(p.create_invoice(user_id="1", plan_key="premium"))  # без периода

    def test_payload_format(self):
        """Формат payload: premium:{plan_key}:{telegram_id}"""
        payload = "premium:premium_monthly:195169"
        parts = payload.split(":")
        assert parts[0] == "premium"
        assert parts[1] in ("premium_monthly", "premium_quarterly", "premium_yearly")
        assert parts[2].isdigit()


# ── Stripe provider ───────────────────────────────────────────────────────────

class TestStripeProvider:

    def test_no_legacy_prices(self):
        from billing.stripe_provider import StripeProvider
        # PLAN_PRICES_USD не должен существовать
        import billing.stripe_provider as sp
        assert not hasattr(sp, "PLAN_PRICES_USD"), "PLAN_PRICES_USD должен быть удалён"

    def test_stripe_prices_from_permissions_in_cents(self):
        from core.permissions import PRICES
        assert PRICES["premium_monthly"]["usd"] == 900    # центы!
        assert PRICES["premium_quarterly"]["usd"] == 2200
        assert PRICES["premium_yearly"]["usd"] == 7200

    def test_verify_payment_valid_signature(self):
        """HMAC верификация с правильной подписью."""
        import hmac as hmac_mod
        import hashlib
        from billing.stripe_provider import StripeProvider
        from unittest.mock import patch

        secret = "whsec_test_secret"
        body = b'{"type":"checkout.session.completed"}'
        ts = "1234567890"
        signed_payload = f"{ts}.".encode() + body
        sig = hmac_mod.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
        sig_header = f"t={ts},v1={sig}"

        with patch.object(StripeProvider, "__init__", lambda self: None):
            p = StripeProvider.__new__(StripeProvider)
            p._secret = "sk_test_key"
            p._webhook_secret = secret

        result = _run(p.verify_payment({"stripe_signature": sig_header, "body": body}))
        assert result is True

    def test_verify_payment_invalid_signature(self):
        """HMAC верификация с неправильной подписью."""
        from billing.stripe_provider import StripeProvider

        with patch.object(StripeProvider, "__init__", lambda self: None):
            p = StripeProvider.__new__(StripeProvider)
            p._secret = "sk_test_key"
            p._webhook_secret = "whsec_test"

        result = _run(p.verify_payment({"stripe_signature": "t=123,v1=badsignature", "body": b"body"}))
        assert result is False

    def test_verify_payment_empty_signature(self):
        """Пустая подпись → False."""
        from billing.stripe_provider import StripeProvider

        with patch.object(StripeProvider, "__init__", lambda self: None):
            p = StripeProvider.__new__(StripeProvider)
            p._secret = "sk_test"
            p._webhook_secret = "whsec_test"

        result = _run(p.verify_payment({"stripe_signature": "", "body": b""}))
        assert result is False


# ── Subscribe keyboard ────────────────────────────────────────────────────────

class TestSubscribeKeyboard:

    def test_keyboard_has_three_stars_rows(self):
        from bot.handlers.billing import _subscribe_keyboard
        kb = _subscribe_keyboard()
        stars_rows = [
            row for row in kb.inline_keyboard
            if any("pay_stars" in btn.callback_data for btn in row)
        ]
        assert len(stars_rows) == 3  # monthly, quarterly, yearly

    def test_keyboard_amounts_present(self):
        from bot.handlers.billing import _subscribe_keyboard
        kb = _subscribe_keyboard()
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        assert any("700" in l for l in labels), "700 stars (monthly) должен быть"
        assert any("1700" in l for l in labels), "1700 stars (quarterly) должен быть"
        assert any("5500" in l for l in labels), "5500 stars (yearly) должен быть"

    def test_keyboard_no_stripe_when_no_key(self):
        from bot.handlers.billing import _subscribe_keyboard
        with patch("config.settings") as mock_s:
            mock_s.stripe_secret_key = ""
            kb = _subscribe_keyboard()
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert not any("pay_stripe" in c for c in callbacks)

    def test_keyboard_has_ultra_button(self):
        from bot.handlers.billing import _subscribe_keyboard
        kb = _subscribe_keyboard()
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "show_ultra" in callbacks

    def test_double_payment_protection(self):
        """days_until_expiry > 3 → подписка считается активной."""
        from datetime import datetime, timezone, timedelta
        from core.permissions import days_until_expiry
        u = MagicMock()
        u.plan_expires_at = datetime.now(timezone.utc) + timedelta(days=10)
        assert days_until_expiry(u) > 3


# ── Billing strings ────────────────────────────────────────────────────────────

class TestBillingStrings:

    def test_no_basic_family_strings(self):
        from services.i18n.ru import STRINGS
        assert "billing.basic" not in STRINGS
        assert "billing.family" not in STRINGS

    def test_premium_period_strings_exist(self):
        from services.i18n.ru import STRINGS
        assert "billing.premium_monthly" in STRINGS
        assert "billing.premium_quarterly" in STRINGS
        assert "billing.premium_yearly" in STRINGS

    def test_premium_monthly_mentions_price(self):
        from services.i18n.ru import t
        text = t("billing.premium_monthly")
        assert "$9" in text or "9" in text

    def test_brief_no_brief_free_no_basic(self):
        """brief.no_brief_free не должен упоминать Basic."""
        from services.i18n.ru import t
        text = t("brief.no_brief_free")
        assert "Basic" not in text
        assert "$5" not in text
