from telegram import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

MAIN_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("✨ Что надеть")],
        [KeyboardButton("👗 Гардероб"), KeyboardButton("💬 Спросить Касси")],
        [KeyboardButton("👤 Профиль"), KeyboardButton("❓ Помощь")],
    ],
    resize_keyboard=True,
    is_persistent=True,
)


def get_main_menu() -> ReplyKeyboardMarkup:
    return MAIN_MENU


def get_remove_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()
