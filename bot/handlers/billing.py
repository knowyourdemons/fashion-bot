"""Billing handlers — Stars, Stripe, plan management."""
import sentry_sdk
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import ContextTypes
from services.i18n import t, get_user_lang
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

    from core.permissions import premium_features_text
    _pf = premium_features_text()
    text = (
        f"{status}"
        f"✨ Касси Premium\n\n"
        f"📅 Бриф каждый день (включая выходные)\n"
        f"👗 Образ дня без ограничений\n"
        f"📸 {_pf['photos']} фото в день в гардероб\n"
        f"⭐ {_pf['rate']} оценок образа в день\n"
        f"💬 {_pf['chat']} вопросов стилисту в день\n"
        f"👧 До {_pf['children']} детей\n\n"
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
        lang = get_user_lang(context.user_data.get("db_user"))
        await query.answer(t("billing.unknown_plan", lang), show_alert=True)
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
        lang = get_user_lang(context.user_data.get("db_user"))
        await query.message.reply_text(t("billing.need_start", lang))
        return

    from config import settings
    if not getattr(settings, "stripe_secret_key", ""):
        await query.message.reply_text(t("billing.card_unavailable", lang))
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
        await query.message.reply_text(t("billing.create_error", lang))
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
        lang = get_user_lang(context.user_data.get("db_user"))
        await update.message.reply_text(t("billing.payment_received_no_user", lang))
        return

    from datetime import datetime, timedelta, timezone
    from db.base import AsyncWriteSession, AsyncReadSession
    from db.crud.users import update_user_plan, get_by_id
    from core.redis import get_redis as _get_redis_billing

    # Idempotency: prevent double-charge on Telegram webhook retry
    _payment_id = payment.telegram_payment_charge_id if hasattr(payment, "telegram_payment_charge_id") else ""
    if _payment_id:
        _redis_b = _get_redis_billing()
        _dedup_key = f"payment_processed:{_payment_id}"
        if await _redis_b.set(_dedup_key, "1", ex=86400 * 7, nx=True) is None:
            logger.warning("stars.duplicate_payment", payment_id=_payment_id, user_id=str(user.id))
            await update.message.reply_text("✅ Оплата уже обработана!")
            return

    # Extend from existing expiry if user has active plan (don't lose paid days)
    existing_expiry = getattr(user, "plan_expires_at", None)
    now = datetime.now(timezone.utc)
    if existing_expiry:
        if hasattr(existing_expiry, "tzinfo") and existing_expiry.tzinfo is None:
            existing_expiry = existing_expiry.replace(tzinfo=timezone.utc)
        if existing_expiry > now:
            expires_at = existing_expiry + timedelta(days=30 * months)
            logger.info("stars.extending_from_prior", prior=existing_expiry.isoformat(),
                        new=expires_at.isoformat())
        else:
            expires_at = now + timedelta(days=30 * months)
    else:
        expires_at = now + timedelta(days=30 * months)

    try:
        async with AsyncWriteSession() as session:
            await update_user_plan(
                session=session,
                user_id=user.id,
                plan=plan,
                plan_expires_at=expires_at,
                subscription_id=None,
                payment_provider="stars",
            )
            # Clear trial fields — user is now a paying customer
            from sqlalchemy import update as sa_update
            from db.models.user import User
            await session.execute(
                sa_update(User)
                .where(User.id == user.id)
                .values(trial_ends_at=None, trial_started_at=None)
            )
            await session.commit()
    except Exception as e:
        logger.error("stars.payment_db_failed", user_id=str(user.id), plan_key=plan_key, error=str(e))
        import sentry_sdk
        sentry_sdk.capture_exception(e)
        await update.message.reply_text(
            "✅ Оплата получена, но произошла ошибка активации.\n"
            "Напиши /start — мы всё исправим. Если проблема сохранится, напиши в поддержку."
        )
        return

    # Reload user from DB to ensure context has fresh data
    async with AsyncReadSession() as session:
        refreshed = await get_by_id(session, user.id)
        if refreshed:
            user = refreshed
    context.user_data["db_user"] = user

    lang = get_user_lang(user)
    await update.message.reply_text(t("billing.activated", lang, period=period_label))
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
    lang = get_user_lang(context.user_data.get("db_user"))
    await query.answer(t("billing.stay_free", lang))


async def handle_compare_plans(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback: compare_plans → таблица Free vs Premium."""
    query = update.callback_query
    await query.answer()
    from core.permissions import get_limit, PRICES
    _fc = get_limit("chat_per_day", "free")
    _pc = get_limit("chat_per_day", "premium")
    _pr = get_limit("reroll", "premium")
    _stars = PRICES["premium_monthly"]["stars"]
    _usd_label = PRICES["premium_monthly"]["label_usd"]
    text = (
        "📊 Free vs Premium\n\n"
        "Free:\n"
        "  Образы: вт/чт\n"
        "  Переодень: —\n"
        "  Вечерний образ: —\n"
        f"  Чат: {_fc}/день\n\n"
        f"Premium ({_stars}⭐ / {_usd_label}):\n"
        "  Образы: каждый день\n"
        f"  Переодень: {_pr}/день\n"
        "  Вечерний образ: ✅\n"
        f"  Чат: {_pc}/день\n"
    )
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("✨ Оформить Premium", callback_data="show_upgrade"),
    ]])
    await query.message.reply_text(text, reply_markup=markup)
