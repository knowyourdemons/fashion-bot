"""Русские строки интерфейса."""

STRINGS: dict[str, str] = {
    # Общие
    "error.generic": "Что-то пошло не так. Попробуй ещё раз.",
    "error.rate_limit": "Превышен лимит запросов. Подожди немного.",
    "error.permission": "Эта функция недоступна на твоём плане.",
    "error.not_found": "Не найдено.",

    # Онбординг
    "onboarding.start": (
        "Привет! Я Касси 👗\n\n"
        "Помогу собрать стильный гардероб для всей семьи.\n"
        "Давай начнём — это займёт минуту!\n\n"
        "Для кого подбираем образы?"
    ),
    "onboarding.segment.mom_girl": "👧 Для дочки",
    "onboarding.segment.mom_boy":  "👦 Для сына",
    "onboarding.segment.pregnant": "🤰 Жду малыша",
    "onboarding.segment.no_kids":  "👩 Для себя",
    "onboarding.child_name": "Как зовут дочку?",
    "onboarding.child_birthdate": "Дата рождения? (дд.мм.гггг)",
    "onboarding.child_size": (
        "Размер одежды ребёнка? 👗\n\n"
        "Введи размер (например: 86, 92, 104, 116)\n"
        "Или возраст (1–12), если не знаешь размер"
    ),
    "onboarding.child_shoe_size": (
        "Размер обуви ребёнка? 👟\n\n"
        "Введи число (например: 26 или 26.5)"
    ),
    "onboarding.city": "Ваш город?",
    "onboarding.trimester": "Какой триместр?",
    "onboarding.body_type": "Тип фигуры? (можно пропустить)",
    "onboarding.colortype_photo": "Пришли селфи для определения цветотипа (можно пропустить)",
    "onboarding.done": "Отлично! Гардероб готов. Пришли фото вещи для начала 📸",

    # Гардероб
    "wardrobe.add.prompt": "Пришли фото вещи 📸",
    "wardrobe.add.no_clothing": "На фото не видно одежды. Пришли фото с одеждой.",
    "wardrobe.add.duplicate": "Такая вещь уже есть в гардеробе!",
    "wardrobe.add.success": "Добавила в гардероб ✅",
    "wardrobe.full": "Гардероб заполнен ({used}/{max} вещей).",
    "wardrobe.full.free": (
        "👗 Гардероб заполнен — {used}/{max} вещей.\n\n"
        "✨ Premium открывает до 500 вещей + безлимит фото в день.\n"
        "👉 /subscribe — 14 дней бесплатно"
    ),
    "wardrobe.empty": "Гардероб пуст. Пришли фото вещи для начала.",
    "wardrobe.list.header": "Твой гардероб ({count} вещей):",

    # Morning Brief
    "brief.header": "🌅 Доброе утро, {name}!",
    "brief.weather": "Сегодня {weather}",
    "brief.outfit": "Предлагаю образ:",
    "brief.wow": "✨ Такой образ обычно предлагают стилисты за $200+",
    "brief.feedback": "Как тебе образ?",
    "brief.no_brief_free": "Morning Brief доступен на Premium. 👉 /subscribe — 14 дней бесплатно",

    # Feedback
    "feedback.thanks_up": "Отлично! Рада, что понравилось 👍",
    "feedback.thanks_down": "Понятно, учту на следующий раз 👎",

    # Billing
    "billing.subscribe": "Выбери период подписки:",
    "billing.premium_monthly":   "💎 Premium — $9/мес (700 ⭐)",
    "billing.premium_quarterly": "💎 Premium — $22/квартал (1700 ⭐)",
    "billing.premium_yearly":    "💎 Premium — $72/год (5500 ⭐) 🏆",
    "billing.success": "Подписка оформлена! Спасибо ✨",
    "billing.cancelled": "Подписка отменена.",
    "billing.expiry.3days": "Подписка истекает через 3 дня. Продлить?",
    "billing.expiry.today": "Подписка истекает сегодня. Продлить?",

    # Trial
    "trial.activated": (
        "🎁 14 дней Premium — бесплатно!\n\n"
        "Все функции уже доступны:\n"
        "📅 Morning Brief каждый день\n"
        "📸 30 фото в гардероб\n"
        "💬 20 вопросов стилисту\n\n"
        "Наслаждайся! 🌟"
    ),
    "trial.expired": (
        "🎁 Пробный период завершён.\n\n"
        "Чтобы продолжить без ограничений — выбери план:\n"
        "👉 /subscribe"
    ),

    # Напоминания
    "reminder.3days": "Привет! Не забывай про Morning Brief 👗",
    "reminder.7days": "Твой гардероб скучает — загляни?",
    "reminder.30days": "Давно не виделись! Есть новые вещи?",

    # Шоппинг-лист
    "shopping.premium_only": (
        "🛍 Шоппинг-лист доступен на Premium.\n\n"
        "Касси проанализирует гардероб и скажет что купить "
        "с учётом сезона и цветотипа.\n\n"
        "👉 /subscribe — 14 дней бесплатно"
    ),
    "shopping.too_few_items": "Добавь хотя бы 5 вещей в гардероб, и я смогу сделать анализ 📸",
    "shopping.generating": "🔍 Анализирую гардероб...",
    "shopping.header": "🛍 Что стоит купить этой {season}:\n\n{list}",
    "shopping.empty_result": "Гардероб выглядит хорошо — пока ничего срочного докупать не нужно 👍",
    "shopping.error": "Не удалось проанализировать гардероб. Попробуй позже.",

    # Помощь
    "help.text": (
        "Я Касси — твой AI-стилист. Вот что умею:\n\n"
        "📸 Пришли фото → добавлю в гардероб\n"
        "🌅 Morning Brief — образ на день по погоде\n"
        "👗 /wardrobe — список вещей\n"
        "💳 /subscribe — Premium (14 дней бесплатно)\n"
        "❓ /help — эта справка"
    ),
}


def t(key: str, **kwargs: str) -> str:
    """Возвращает строку по ключу с подстановкой параметров."""
    template = STRINGS.get(key, key)
    return template.format(**kwargs) if kwargs else template
