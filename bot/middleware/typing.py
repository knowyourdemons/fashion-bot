"""
Typing middleware: отправляет ChatAction.TYPING при обработке сообщений.
"""
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes


class TypingMiddleware:
    @staticmethod
    async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message:
            await context.bot.send_chat_action(
                chat_id=update.effective_chat.id,
                action=ChatAction.TYPING,
            )
