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


def get_main_menu(user=None) -> ReplyKeyboardMarkup:
    """Main menu with owner-aware wardrobe icon."""
    wardrobe_icon = "👗"
    if user:
        segment = getattr(user, "segment", None)
        if segment == "mom_girl":
            wardrobe_icon = "👧"
        elif segment == "mom_boy":
            wardrobe_icon = "👦"
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("✨ Что надеть")],
            [KeyboardButton(f"{wardrobe_icon} Гардероб"), KeyboardButton("💬 Спросить Касси")],
            [KeyboardButton("👤 Профиль"), KeyboardButton("❓ Помощь")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def get_remove_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()
