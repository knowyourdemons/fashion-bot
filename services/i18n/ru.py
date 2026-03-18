"""Русские строки интерфейса."""

STRINGS: dict[str, str] = {
    # Общие
    "error.generic": "Что-то пошло не так. Попробуй ещё раз.",
    "error.rate_limit": "Превышен лимит запросов. Подожди немного.",
    "error.permission": "Эта функция недоступна на твоём плане.",
    "error.not_found": "Не найдено.",

    # Онбординг
    "onboarding.start": "Для кого будем подбирать образы? 👗\n\nВыбери один вариант — потом можно изменить",
    "onboarding.segment.mom_girl": "👧 Для дочки",
    "onboarding.segment.mom_boy": "👦 Для сына",
    "onboarding.segment.pregnant": "🤰 Жду малыша",
    "onboarding.segment.no_kids": "👩 Для себя",
    "onboarding.child_name": "Как зовут дочку?",
    "onboarding.child_birthdate": "Дата рождения? (дд.мм.гггг)",
    "onboarding.child_size": "Размер одежды ребёнка? 👗\n\nВведи размер (например: 86, 92, 104, 116)\nИли возраст (1–12), если не знаешь размер",
    "onboarding.child_shoe_size": "Размер обуви ребёнка? 👟\n\nВведи число (например: 26 или 26.5)",
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
    "wardrobe.empty": "Гардероб пуст. Пришли фото вещи для начала.",
    "wardrobe.list.header": "Твой гардероб ({count} вещей):",

    # Morning Brief
    "brief.header": "🌅 Доброе утро, {name}!",
    "brief.weather": "Сегодня {weather}",
    "brief.outfit": "Предлагаю образ:",
    "brief.wow": "✨ Такой образ обычно предлагают стилисты за $200+",
    "brief.feedback": "Как тебе образ?",
    "brief.no_brief_free": "Morning Brief доступен с плана Basic ($5/мес).",

    # Feedback
    "feedback.thanks_up": "Отлично! Рада, что понравилось 👍",
    "feedback.thanks_down": "Понятно, учту на следующий раз 👎",

    # Billing
    "billing.subscribe": "Выбери план:",
    "billing.basic": "Basic — $5/мес или $48/год",
    "billing.family": "Family — $12/мес или $115/год",
    "billing.premium": "Premium — $19/мес или $182/год",
    "billing.success": "Подписка оформлена! Спасибо ✨",
    "billing.cancelled": "Подписка отменена.",
    "billing.expiry.3days": "Подписка истекает через 3 дня. Продлить?",
    "billing.expiry.today": "Подписка истекает сегодня. Продлить?",

    # Напоминания
    "reminder.3days": "Привет! Не забывай про Morning Brief 👗",
    "reminder.7days": "Твой гардероб скучает — загляни?",
    "reminder.30days": "Давно не виделись! Есть новые вещи?",

    # Помощь
    "help.text": (
        "Я AI-стилист. Вот что я умею:\n\n"
        "📸 Пришли фото → добавлю в гардероб\n"
        "🌅 Morning Brief — образ на день по погоде\n"
        "👗 /wardrobe — список вещей\n"
        "💳 /subscribe — планы и оплата\n"
        "❓ /help — эта справка"
    ),
}


def t(key: str, **kwargs: str) -> str:
    """Возвращает строку по ключу с подстановкой параметров."""
    template = STRINGS.get(key, key)
    return template.format(**kwargs) if kwargs else template
