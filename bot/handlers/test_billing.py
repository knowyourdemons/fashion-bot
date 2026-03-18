"""
/test_subscribe — тестовый интерфейс платёжного флоу.
Только для ADMIN_TELEGRAM_IDS.
"""
import structlog
from datetime import datetime, timezone, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import settings

logger = structlog.get_logger()


def _admin_only(user) -> bool:
    return user and int(getattr(user, "telegram_id", -1)) in settings.admin_ids_list


async def _show_test_menu(
    update_or_message,
    user,
    result_msg: str = "",
) -> None:
    """Показать тестовое меню с текущим статусом."""
    from core.permissions import (
        get_effective_plan, get_limit,
        get_trial_days_left, is_trial_active, days_until_expiry,
    )

    ep = get_effective_plan(user)
    trial_days = get_trial_days_left(user)
    expire_days = days_until_expiry(user)

    lines = ["🧪 Test Subscribe Menu\n"]
    lines.append(f"Plan: <b>{ep}</b>  |  DB plan: {getattr(user, 'plan', '?')}")

    if is_trial_active(user) and trial_days is not None:
        lines.append(f"Trial: активен · осталось {trial_days} дн.")
    elif getattr(user, "trial_ends_at", None):
        lines.append("Trial: истёк")
    else:
        lines.append("Trial: нет")

    if expire_days is not None:
        lines.append(f"Подписка: до истечения {expire_days} дн.")

    lines.append(f"\nLimits (plan={ep}):")
    for key in ("photos_per_day", "chat_per_day", "outfit_req_per_day", "wardrobe_size"):
        lines.append(f"  {key}: {get_limit(key, ep)}")

    if result_msg:
        lines.append(f"\n✅ {result_msg}")

    text = "\n".join(lines)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎁 Trial 14д", callback_data="ts:trial"),
         InlineKeyboardButton("💎 Premium 30д", callback_data="ts:premium")],
        [InlineKeyboardButton("🔄 Сбросить в free", callback_data="ts:reset"),
         InlineKeyboardButton("📊 Лимиты", callback_data="ts:limits")],
        [InlineKeyboardButton("🔔 Запустить expiry", callback_data="ts:expiry"),
         InlineKeyboardButton("🌅 Evening push", callback_data="ts:evening")],
        [InlineKeyboardButton("💳 Stars invoice (тест)", callback_data="ts:stars_test")],
        [InlineKeyboardButton("🔄 Обновить", callback_data="ts:refresh")],
    ])

    if hasattr(update_or_message, "edit_text"):
        try:
            await update_or_message.edit_text(
                text, reply_markup=keyboard, parse_mode="HTML"
            )
            return
        except Exception:
            pass

    msg = update_or_message if hasattr(update_or_message, "reply_text") else None
    if msg:
        await msg.reply_text(text, reply_markup=keyboard, parse_mode="HTML")


async def handle_test_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /test_subscribe — только для admin."""
    user = context.user_data.get("db_user")
    if not _admin_only(user):
        await update.message.reply_text("⛔ Только для admin.")
        return
    await _show_test_menu(update.message, user)


async def handle_test_subscribe_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик кнопок тестового меню (callback ts:*)."""
    query = update.callback_query
    await query.answer()

    user = context.user_data.get("db_user")
    if not _admin_only(user):
        await query.answer("⛔ Только для admin", show_alert=True)
        return

    action = query.data.split(":")[1]
    result_msg = ""

    from db.base import AsyncWriteSession
    from db.models.user import User as UserModel
    from sqlalchemy import update as sql_update, select

    # ── Активировать trial ─────────────────────────────────────────────────
    if action == "trial":
        now = datetime.now(timezone.utc)
        async with AsyncWriteSession() as session:
            await session.execute(
                sql_update(UserModel)
                .where(UserModel.id == user.id)
                .values(
                    plan="free",
                    plan_expires_at=None,
                    trial_started_at=now,
                    trial_ends_at=now + timedelta(days=14),
                )
            )
            await session.commit()
        user.plan = "free"
        user.plan_expires_at = None
        user.trial_started_at = now
        user.trial_ends_at = now + timedelta(days=14)
        context.user_data["db_user"] = user
        result_msg = "Trial 14 дней активирован"

    # ── Активировать premium ───────────────────────────────────────────────
    elif action == "premium":
        now = datetime.now(timezone.utc)
        expires = now + timedelta(days=30)
        async with AsyncWriteSession() as session:
            await session.execute(
                sql_update(UserModel)
                .where(UserModel.id == user.id)
                .values(
                    plan="premium",
                    plan_expires_at=expires,
                    payment_provider="test",
                )
            )
            await session.commit()
        user.plan = "premium"
        user.plan_expires_at = expires
        context.user_data["db_user"] = user
        result_msg = "Premium 30 дней активирован"

    # ── Сбросить в free ────────────────────────────────────────────────────
    elif action == "reset":
        async with AsyncWriteSession() as session:
            await session.execute(
                sql_update(UserModel)
                .where(UserModel.id == user.id)
                .values(
                    plan="free",
                    plan_expires_at=None,
                    trial_started_at=None,
                    trial_ends_at=None,
                    payment_provider=None,
                )
            )
            await session.commit()
        user.plan = "free"
        user.plan_expires_at = None
        user.trial_started_at = None
        user.trial_ends_at = None
        context.user_data["db_user"] = user
        result_msg = "Сброшено в free"

    # ── Показать лимиты ────────────────────────────────────────────────────
    elif action == "limits":
        from core.permissions import get_effective_plan, get_limit, LIMITS
        ep = get_effective_plan(user)
        lines = [f"Лимиты для плана <b>{ep}</b>:"]
        for k, v in LIMITS.get(ep, LIMITS["free"]).items():
            lines.append(f"  {k}: {v}")
        await query.message.reply_text("\n".join(lines), parse_mode="HTML")
        return

    # ── Запустить expiry уведомление (только для текущего пользователя) ────
    elif action == "expiry":
        try:
            now = datetime.now(timezone.utc)
            async with AsyncWriteSession() as session:
                await session.execute(
                    sql_update(UserModel)
                    .where(UserModel.id == user.id)
                    .values(
                        trial_started_at=now - timedelta(days=15),
                        trial_ends_at=now - timedelta(hours=1),
                        plan="free",
                    )
                )
                await session.commit()

            user.trial_ends_at = now - timedelta(hours=1)
            user.plan = "free"
            context.user_data["db_user"] = user

            from worker.tasks.subscription_expiry import notify_single_user_trial_expiry
            await notify_single_user_trial_expiry(user.telegram_id)
            result_msg = "Expiry уведомление отправлено"
        except Exception as e:
            logger.error("test_billing.expiry_error", error=str(e))
            result_msg = f"Ошибка: {e}"

    # ── Evening push для текущего пользователя ────────────────────────────
    elif action == "evening":
        try:
            from core.permissions import get_effective_plan, is_brief_day_tomorrow
            ep = get_effective_plan(user)
            tz = getattr(user, "timezone", None) or "Europe/Vilnius"
            tomorrow_has_brief = is_brief_day_tomorrow(ep, tz)
            if tomorrow_has_brief:
                from telegram import Bot
                bot = Bot(token=settings.telegram_bot_token)
                await bot.send_message(
                    chat_id=user.telegram_id,
                    text=(
                        "🌙 Завтра Касси пришлёт тебе утренний образ!\n"
                        "Подготовь гардероб — добавь новые вещи если нужно 👗"
                    ),
                )
                result_msg = "Evening push отправлен"
            else:
                result_msg = f"Завтра бриф не запланирован (plan={ep})"
        except Exception as e:
            result_msg = f"Ошибка: {e}"

    # ── Тест Stars invoice ─────────────────────────────────────────────────
    elif action == "stars_test":
        from telegram import LabeledPrice
        from core.permissions import PRICES
        price = PRICES["premium_monthly"]
        await context.bot.send_invoice(
            chat_id=query.message.chat_id,
            title="Касси Premium (тест)",
            description=price["label_usd"],
            payload=f"premium:premium_monthly:{user.telegram_id}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice("Premium", price["stars"])],
        )
        return

    # ── Обновить меню ──────────────────────────────────────────────────────
    elif action == "refresh":
        pass  # просто перерисуем меню ниже

    # Перечитать пользователя из БД для актуального статуса
    from db.base import AsyncReadSession
    async with AsyncReadSession() as session:
        result = await session.execute(
            select(UserModel).where(UserModel.id == user.id)
        )
        fresh_user = result.scalar_one_or_none()
        if fresh_user:
            context.user_data["db_user"] = fresh_user
            user = fresh_user

    await _show_test_menu(query.message, user, result_msg)
