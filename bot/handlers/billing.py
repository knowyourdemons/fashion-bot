"""Billing handlers — Stars, Stripe, plan management."""
import sentry_sdk
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import ContextTypes
from services.i18n.ru import t
import structlog

logger = structlog.get_logger()

# Period → months
_PERIOD_MONTHS = {"monthly": 1, "quarterly": 3, "yearly": 12}


def _stars_keyboard() -> InlineKeyboardMarkup:
    from core.permissions import PRICES
    from config import settings

    rows = [
        [InlineKeyboardButton(
            f"⭐ {PRICES['premium_monthly']['label_stars']}",
            callback_data="pay_stars:monthly",
        )],
        [InlineKeyboardButton(
            f"⭐ {PRICES['premium_quarterly']['label_stars']}",
            callback_data="pay_stars:quarterly",
        )],
        [InlineKeyboardButton(
            f"⭐ {PRICES['premium_yearly']['label_stars']} — Лучшая цена",
            callback_data="pay_stars:yearly",
        )],
    ]
    if settings.stripe_secret_key:
        rows += [
            [InlineKeyboardButton(
                f"💳 {PRICES['premium_monthly']['label_usd']}",
                callback_data="pay_stripe:monthly",
            )],
            [InlineKeyboardButton(
                f"💳 {PRICES['premium_quarterly']['label_usd']}",
                callback_data="pay_stripe:quarterly",
            )],
            [InlineKeyboardButton(
                f"💳 {PRICES['premium_yearly']['label_usd']} — Лучшая цена",
                callback_data="pay_stripe:yearly",
            )],
        ]
    rows.append([InlineKeyboardButton("🔒 Ultra — скоро!", callback_data="show_ultra")])
    return InlineKeyboardMarkup(rows)


async def handle_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = context.user_data.get("db_user")
    from core.permissions import (
        get_effective_plan, get_trial_days_left, is_trial_active, days_until_expiry,
    )

    if not user:
        await update.message.reply_text(
            "✨ Касси Premium\n\nВойди через /start чтобы оформить подписку."
        )
        return

    effective_plan = get_effective_plan(user)

    if effective_plan == "admin":
        await update.message.reply_text("👑 У тебя admin план!")
        return

    if effective_plan in ("premium", "ultra") and getattr(user, "plan", "free") in ("premium", "ultra"):
        d = days_until_expiry(user)
        days_text = f"\nДо следующего списания: {d} дн." if d is not None else ""
        await update.message.reply_text(
            f"✅ У тебя {'Premium' if effective_plan == 'premium' else 'Ultra'} план!"
            f"{days_text}\nВсе функции доступны 🎉"
        )
        return

    trial_days = get_trial_days_left(user)
    if is_trial_active(user) and trial_days:
        trial_text = (
            f"🎁 У тебя активный trial!\n"
            f"Осталось дней: {trial_days}\n\n"
        )
    else:
        trial_text = ""

    text = (
        f"{trial_text}"
        f"✨ Касси Premium\n\n"
        f"📅 Бриф каждый день (включая выходные)\n"
        f"👗 Образ дня без ограничений\n"
        f"📸 30 фото в день в гардероб\n"
        f"⭐ 20 оценок образа в день\n"
        f"💬 20 вопросов стилисту в день\n"
        f"👧 До 3 детей\n\n"
        f"Выбери способ оплаты:"
    )
    await update.message.reply_text(text, reply_markup=_stars_keyboard())


async def handle_pay_stars(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет Telegram Stars invoice."""
    query = update.callback_query
    await query.answer()

    period = query.data.split(":")[1]  # monthly | quarterly | yearly
    months = _PERIOD_MONTHS.get(period, 1)

    from core.permissions import PRICES
    price_key = f"premium_{period}"
    stars_amount = PRICES[price_key]["stars"]
    period_label = {
        "monthly": "1 месяц",
        "quarterly": "3 месяца",
        "yearly": "1 год",
    }.get(period, period)

    user = context.user_data.get("db_user")
    user_id = str(user.id) if user else "unknown"

    await context.bot.send_invoice(
        chat_id=query.message.chat_id,
        title="Касси Premium",
        description=f"Подписка на {period_label}",
        payload=f"premium:{period}:{user_id}",
        currency="XTR",
        prices=[LabeledPrice(f"Premium {period_label}", stars_amount)],
        provider_token="",  # пустой для Stars
    )


async def handle_pay_stripe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Создаёт Stripe Checkout сессию и отправляет ссылку."""
    query = update.callback_query
    await query.answer()

    period = query.data.split(":")[1]  # monthly | quarterly | yearly
    user = context.user_data.get("db_user")
    if not user:
        await query.message.reply_text("Сначала войди через /start")
        return

    from config import settings
    if not settings.stripe_secret_key:
        await query.message.reply_text("Оплата картой временно недоступна.")
        return

    from billing.stripe_provider import StripeProvider
    provider = StripeProvider()

    try:
        invoice = await provider.create_invoice(
            user_id=str(user.telegram_id),
            plan="premium",
            period=period,
        )
        url = invoice.get("url", "")
        if not url:
            raise ValueError("No URL in Stripe response")

        await query.message.reply_text(
            f"💳 Оплата картой:\n{url}\n\n"
            f"После оплаты Premium активируется автоматически."
        )
    except Exception as e:
        logger.error("pay_stripe.error", error=str(e))
        await query.message.reply_text("Ошибка при создании платежа. Попробуй позже.")
        sentry_sdk.capture_exception(e)


async def handle_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Stars SUCCESSFUL_PAYMENT — активирует premium."""
    payment = update.message.successful_payment
    if not payment:
        return

    payload = payment.invoice_payload  # "premium:monthly:<user_id>"
    parts = payload.split(":")
    plan = parts[0] if len(parts) > 0 else "premium"
    period = parts[1] if len(parts) > 1 else "monthly"
    months = _PERIOD_MONTHS.get(period, 1)

    user = context.user_data.get("db_user")
    if not user:
        logger.warning("successful_payment.no_db_user")
        await update.message.reply_text("✅ Оплата получена! Напиши /start для обновления.")
        return

    from datetime import datetime, timedelta, timezone
    from db.base import AsyncWriteSession
    from db.crud.users import update_user_plan

    expires_at = datetime.now(timezone.utc) + timedelta(days=30 * months)
    async with AsyncWriteSession() as session:
        await update_user_plan(
            session=session,
            user_id=user.id,
            plan=plan,
            plan_expires_at=expires_at,
            subscription_id=None,  # Stars не даёт subscription_id
            payment_provider="stars",
        )

    # Обновить кэш
    user.plan = plan
    user.plan_expires_at = expires_at
    context.user_data["db_user"] = user

    period_label = {"monthly": "месяц", "quarterly": "3 месяца", "yearly": "год"}.get(period, period)
    await update.message.reply_text(
        f"✅ Premium активирован на {period_label}!\n"
        f"Все функции доступны. Добро пожаловать! 🎉"
    )
    logger.info(
        "stars.payment_activated",
        user_id=str(user.id),
        plan=plan,
        period=period,
        expires_at=expires_at.isoformat(),
    )


async def handle_pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отвечает на PreCheckoutQuery — обязателен для Stars."""
    await update.pre_checkout_query.answer(ok=True)


async def handle_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = context.user_data.get("db_user")
    if not user:
        return
    from core.permissions import get_effective_plan, days_until_expiry
    ep = get_effective_plan(user)
    d = days_until_expiry(user)
    days_text = f", осталось {d} дн." if d is not None else ""
    await update.message.reply_text(f"Твой план: {ep}{days_text}")


async def handle_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(t("billing.cancelled"))


async def handle_plan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Legacy handler для plan: callback_data."""
    query = update.callback_query
    await query.answer()
    try:
        parts = query.data.split(":")
        plan = parts[1] if len(parts) > 1 else "premium"
        period = parts[2] if len(parts) > 2 else "monthly"
        await query.message.reply_text(f"Оформляю {plan}/{period}...")
    except Exception as e:
        await query.message.reply_text(t("error.generic"))
        sentry_sdk.capture_exception(e)


async def handle_stay_free(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Пользователь выбрал остаться на free после trial."""
    query = update.callback_query
    await query.answer("Хорошо! Ты всегда можешь вернуться к Premium 💎")
