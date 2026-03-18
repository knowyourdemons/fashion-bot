"""Billing handlers."""
import sentry_sdk
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from exceptions import FashionBotError, PaymentError
from services.i18n.ru import t

PLAN_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton(t("billing.basic"), callback_data="plan:basic:monthly")],
    [InlineKeyboardButton(t("billing.family"), callback_data="plan:family:monthly")],
    [InlineKeyboardButton(t("billing.premium"), callback_data="plan:premium:monthly")],
])


async def handle_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = context.user_data.get("db_user")
    from core.permissions import (
        get_effective_plan, PRICES, ULTRA_FEATURES,
        get_trial_days_left, is_trial_active,
    )

    if not user:
        await update.message.reply_text(t("billing.subscribe"), reply_markup=PLAN_KEYBOARD)
        return

    effective_plan = get_effective_plan(user)

    if effective_plan == "admin":
        await update.message.reply_text("👑 У тебя admin план!")
        return

    if effective_plan == "premium" and getattr(user, "plan", "free") == "premium":
        await update.message.reply_text(
            "✅ У тебя Premium план!\nВсе функции доступны 🎉"
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
        f"Выбери план:\n"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"📅 {PRICES['premium_monthly']['label']}",
            callback_data="subscribe:monthly",
        )],
        [InlineKeyboardButton(
            f"📅 {PRICES['premium_quarterly']['label']}",
            callback_data="subscribe:quarterly",
        )],
        [InlineKeyboardButton(
            f"📅 {PRICES['premium_yearly']['label']} ⭐ Лучшая цена",
            callback_data="subscribe:yearly",
        )],
        [InlineKeyboardButton("🔒 Ultra — скоро!", callback_data="show_ultra")],
    ])
    await update.message.reply_text(text, reply_markup=keyboard)


async def handle_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = context.user_data.get("db_user")
    if not user:
        return
    await update.message.reply_text(f"Твой план: {user.plan}")


async def handle_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(t("billing.cancelled"))


async def handle_plan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    try:
        _, plan, period = query.data.split(":")
        await query.message.reply_text(f"Оформляю {plan}/{period}...")
    except Exception as e:
        await query.message.reply_text(t("error.generic"))
        sentry_sdk.capture_exception(e)

async def handle_stay_free(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Пользователь выбрал остаться на free после trial."""
    query = update.callback_query
    await query.answer("Хорошо! Ты всегда можешь вернуться к Premium 💎")
