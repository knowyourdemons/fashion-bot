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
    await update.message.reply_text(t("billing.subscribe"), reply_markup=PLAN_KEYBOARD)


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
