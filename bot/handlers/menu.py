from telegram import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

MAIN_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("✨ Что надеть")],
        [KeyboardButton("👗 Гардероб"), KeyboardButton("💬 Спросить Касси")],
        [KeyboardButton("🛍 Подойдёт?"), KeyboardButton("👤 Профиль")],
    ],
    resize_keyboard=True,
    is_persistent=True,
)


def get_main_menu(user=None, context=None) -> ReplyKeyboardMarkup:
    """Main menu with owner-aware wardrobe icon based on active owner."""
    wardrobe_icon = "👗"
    # Active owner from context (child vs self)
    if context and hasattr(context, "user_data"):
        _active_owner_type = context.user_data.get("active_owner_type", "child")
        _active_gender = context.user_data.get("active_owner_gender", "girl")
        if _active_owner_type == "child":
            wardrobe_icon = "👧" if _active_gender == "girl" else "👦"
        else:
            wardrobe_icon = "👩"
    elif user:
        segment = getattr(user, "segment", None)
        if segment == "mom_girl":
            wardrobe_icon = "👧"
        elif segment == "mom_boy":
            wardrobe_icon = "👦"
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("✨ Что надеть")],
            [KeyboardButton(f"{wardrobe_icon} Гардероб"), KeyboardButton("💬 Спросить Касси")],
            [KeyboardButton("🛍 Подойдёт?"), KeyboardButton("👤 Профиль")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def get_remove_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()
