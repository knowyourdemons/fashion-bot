"""Billing handlers — Stars, Stripe, plan management."""
import sentry_sdk
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import ContextTypes
from services.i18n.ru import t
import structlog

logger = structlog.get_logger()

# price_key → period months
_KEY_MONTHS = {
    "premium_monthly": 1,
    "premium_quarterly": 3,
    "premium_yearly": 12,
}
_KEY_LABEL = {
    "premium_monthly": "1 месяц",
    "premium_quarterly": "3 месяца",
    "premium_yearly": "1 год",
}


def _subscribe_keyboard() -> InlineKeyboardMarkup:
    from core.permissions import PRICES
    from config import settings

    rows = []

    # Stars секция — всегда
    rows += [
        [InlineKeyboardButton(
            f"⭐ {PRICES['premium_monthly']['label_stars']}",
            callback_data="pay_stars:premium_monthly",
        )],
        [InlineKeyboardButton(
            f"⭐ {PRICES['premium_quarterly']['label_stars']}",
            callback_data="pay_stars:premium_quarterly",
        )],
        [InlineKeyboardButton(
            f"⭐ {PRICES['premium_yearly']['label_stars']} 🏆",
            callback_data="pay_stars:premium_yearly",
        )],
    ]

    # Stripe — только если настроен
    if getattr(settings, "stripe_secret_key", ""):
        rows += [
            [InlineKeyboardButton(
                f"💳 {PRICES['premium_monthly']['label_usd']}",
                callback_data="pay_stripe:premium_monthly",
            )],
            [InlineKeyboardButton(
                f"💳 {PRICES['premium_quarterly']['label_usd']}",
                callback_data="pay_stripe:premium_quarterly",
            )],
            [InlineKeyboardButton(
                f"💳 {PRICES['premium_yearly']['label_usd']} 🏆",
                callback_data="pay_stripe:premium_yearly",
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
        await update.message.reply_text(
            "👑 Admin план\n\n"
            "Для тестирования платёжного флоу используй:\n"
            "/test_subscribe"
        )
        return

    # Защита от двойной оплаты
    expire_days = days_until_expiry(user)
    if effective_plan in ("premium", "ultra") and expire_days is not None and expire_days > 3:
        plan_label = "Premium" if effective_plan == "premium" else "Ultra"
        await update.message.reply_text(
            f"✅ У тебя уже активен {plan_label}!\n"
            f"Действует ещё {expire_days} дн.\n\n"
            f"Продлить заранее можно за 3 дня до истечения."
        )
        return

    # Статус trial
    trial_days = get_trial_days_left(user)
    if is_trial_active(user) and trial_days:
        status = (
            f"🎁 Trial активен · осталось {trial_days} дн.\n"
            f"Подпишись сейчас — продолжишь без перерыва!\n\n"
        )
    else:
        status = ""

    text = (
        f"{status}"
        f"✨ Касси Premium\n\n"
        f"📅 Бриф каждый день (включая выходные)\n"
        f"👗 Образ дня без ограничений\n"
        f"📸 30 фото в день в гардероб\n"
        f"⭐ 20 оценок образа в день\n"
        f"💬 20 вопросов стилисту в день\n"
        f"👧 До 3 детей\n\n"
        f"Выбери план:"
    )
    await update.message.reply_text(text, reply_markup=_subscribe_keyboard())


async def handle_pay_stars(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает подтверждение перед отправкой Stars invoice."""
    query = update.callback_query
    await query.answer()

    plan_key = query.data.split(":")[1]  # premium_monthly | premium_quarterly | premium_yearly

    from core.permissions import PRICES
    price = PRICES.get(plan_key)
    if not price:
        await query.answer("Неизвестный план", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"✅ Оплатить {price['stars']} ⭐",
            callback_data=f"confirm_stars:{plan_key}",
        ),
        InlineKeyboardButton(
            "◀️ Назад",
            callback_data="show_upgrade",
        ),
    ]])
    await query.edit_message_text(
        f"⭐ {price['label_usd']}\n\n"
        f"Стоимость: {price['stars']} Telegram Stars\n\n"
        f"После оплаты Premium активируется мгновенно!",
        reply_markup=keyboard,
    )


async def handle_confirm_stars(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет Stars invoice после подтверждения."""
    query = update.callback_query
    await query.answer()

    plan_key = query.data.split(":")[1]
    user = context.user_data.get("db_user")

    from core.permissions import PRICES
    price = PRICES.get(plan_key)
    if not price:
        return

    try:
        await query.message.delete()
    except Exception:
        pass

    telegram_id = getattr(user, "telegram_id", "unknown") if user else "unknown"

    await context.bot.send_invoice(
        chat_id=query.message.chat_id,
        title="Касси Premium",
        description=price["label_usd"],
        payload=f"premium:{plan_key}:{telegram_id}",
        provider_token="",  # пустой для Stars
        currency="XTR",
        prices=[LabeledPrice("Premium", price["stars"])],
    )


async def handle_pay_stripe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Создаёт Stripe Checkout сессию и отправляет ссылку."""
    query = update.callback_query
    await query.answer()

    plan_key = query.data.split(":")[1]  # premium_monthly | premium_quarterly | premium_yearly
    user = context.user_data.get("db_user")
    if not user:
        await query.message.reply_text("Сначала войди через /start")
        return

    from config import settings
    if not getattr(settings, "stripe_secret_key", ""):
        await query.message.reply_text("Оплата картой временно недоступна.")
        return

    # Маппинг ключей в period для StripeProvider
    period_map = {
        "premium_monthly": "monthly",
        "premium_quarterly": "quarterly",
        "premium_yearly": "yearly",
    }
    period = period_map.get(plan_key, "monthly")

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

    # payload = "premium:premium_monthly:<telegram_id>"
    payload = payment.invoice_payload

    # Тестовый payload — не активировать premium
    if payload.startswith("test:"):
        await update.message.reply_text(
            "✅ Тест Stars оплаты прошёл успешно!\n"
            "Premium не активирован — это тестовый платёж.\n\n"
            "В реальном флоу здесь активируется подписка."
        )
        return

    # "premium:premium_monthly:<telegram_id>"
    parts = payload.split(":")
    plan = parts[0] if len(parts) > 0 else "premium"
    plan_key = parts[1] if len(parts) > 1 else "premium_monthly"
    months = _KEY_MONTHS.get(plan_key, 1)
    period_label = _KEY_LABEL.get(plan_key, "1 месяц")

    user = context.user_data.get("db_user")
    if not user:
        logger.warning("successful_payment.no_db_user")
        await update.message.reply_text("✅ Оплата получена! Напиши /start для обновления.")
        return

    from datetime import datetime, timedelta, timezone
    from db.base import AsyncWriteSession, AsyncReadSession
    from db.crud.users import update_user_plan, get_by_id

    expires_at = datetime.now(timezone.utc) + timedelta(days=30 * months)
    async with AsyncWriteSession() as session:
        await update_user_plan(
            session=session,
            user_id=user.id,
            plan=plan,
            plan_expires_at=expires_at,
            subscription_id=None,
            payment_provider="stars",
        )

    # Reload user from DB to ensure context has fresh data
    async with AsyncReadSession() as session:
        refreshed = await get_by_id(session, user.id)
        if refreshed:
            user = refreshed
    context.user_data["db_user"] = user

    await update.message.reply_text(
        f"✅ Premium активирован на {period_label}!\n"
        f"Все функции доступны. Добро пожаловать! 🎉"
    )
    logger.info(
        "stars.payment_activated",
        user_id=str(user.id),
        plan=plan,
        plan_key=plan_key,
        expires_at=expires_at.isoformat(),
    )
    logger.info("metric.subscription_started",
        user_id=str(user.id),
        plan=plan,
        provider="stars",
    )


async def handle_pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отвечает на PreCheckoutQuery — обязателен для Stars (в течение 10 сек)."""
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


async def handle_stay_free(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Пользователь выбрал остаться на free после trial."""
    query = update.callback_query
    await query.answer("Хорошо! Ты всегда можешь вернуться к Premium 💎")


async def handle_compare_plans(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback: compare_plans → таблица Free vs Premium."""
    query = update.callback_query
    await query.answer()
    text = (
        "📊 Free vs Premium\n\n"
        "Free:\n"
        "  Образы: вт/чт\n"
        "  Переодень: —\n"
        "  Вечерний образ: —\n"
        "  Чат: 1/день\n\n"
        "Premium (700⭐ / $9/мес):\n"
        "  Образы: каждый день\n"
        "  Переодень: 3/день\n"
        "  Вечерний образ: ✅\n"
        "  Чат: 20/день\n"
    )
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("✨ Оформить Premium", callback_data="show_upgrade"),
    ]])
    await query.message.reply_text(text, reply_markup=markup)
