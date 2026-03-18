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
    expires = getattr(user, "plan_expires_at", None)
    provider = getattr(user, "payment_provider", None)

    # ФИКС 1: статус с эмодзи
    if ep == "admin":
        status_emoji = "👑"
    elif ep == "premium" and is_trial_active(user):
        status_emoji = "🟡"  # trial
    elif ep == "premium":
        status_emoji = "🟢"  # полноценный premium
    else:
        status_emoji = "🔴"  # free

    trial_str = (
        f"активен · {trial_days} дн. осталось" if trial_days
        else ("истёк" if getattr(user, "trial_ends_at", None) else "нет")
    )

    lines = [
        "🧪 Тест подписки\n",
        f"{status_emoji} effective_plan: <b>{ep}</b>",
        f"plan в БД: {getattr(user, 'plan', '?')}",
        f"trial: {trial_str}",
        f"plan_expires: {str(expires)[:16] if expires else 'нет'}",
        f"provider: {provider or 'нет'}",
    ]

    if expire_days is not None:
        lines.append(f"до истечения: {expire_days} дн.")

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
        from core.permissions import LIMITS

        # ФИКС 2: сравнение всех планов
        brief_label = {
            str([1, 3]): "вт/чт",
            str([0, 1, 2, 3, 4, 5, 6]): "каждый день",
        }
        lines = ["📊 Сравнение лимитов:\n"]
        for plan_name, emoji in (("free", "🔴"), ("premium", "🟢"), ("ultra", "💎")):
            lim = LIMITS[plan_name]
            bd = brief_label.get(str(lim["brief_days"]), str(lim["brief_days"]))
            lines.append(
                f"{'—'*18}\n"
                f"{emoji} <b>{plan_name.upper()}</b>\n"
                f"  📸 фото/день: {lim['photos_per_day']}\n"
                f"  👗 гардероб: {lim['wardrobe_size']} вещей\n"
                f"  ⭐ оценки/день: {lim['rate_per_day']}\n"
                f"  💬 чат/день: {lim['chat_per_day']}\n"
                f"  🌤 образ дня: {lim['outfit_req_per_day']}\n"
                f"  📅 бриф: {bd}\n"
                f"  👧 детей: {lim['children_max']}"
            )
        await query.message.reply_text(
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="ts:refresh"),
            ]]),
        )
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

        plan_key = "premium_monthly"
        price = PRICES[plan_key]

        # ФИКС 3: красивое сообщение перед invoice
        await query.message.reply_text(
            f"⭐ Тест Stars оплаты\n\n"
            f"План: {price['label_usd']}\n"
            f"Стоимость: {price['stars']} Telegram Stars\n\n"
            f"👇 Нажми кнопку ниже чтобы оплатить:"
        )
        await context.bot.send_invoice(
            chat_id=query.message.chat_id,
            title="Касси Premium (тест)",
            description=price["label_usd"],
            payload=f"test:premium:{plan_key}:{user.telegram_id}",
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
