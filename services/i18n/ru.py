"""Русские строки интерфейса."""

STRINGS: dict[str, str] = {
    # Общие
    "error.generic": "Что-то пошло не так. Попробуй ещё раз.",
    "error.rate_limit": "Превышен лимит запросов. Подожди немного.",
    "error.permission": "Эта функция недоступна на твоём плане.",
    "error.not_found": "Не найдено.",

    # Онбординг
    "onboarding.welcome": (
        "Привет! 👋 Я Касси — твой личный стилист.\n\n"
        "Каждое утро буду присылать готовый образ по погоде "
        "из вещей, которые уже есть в шкафу.\n\n"
        "Познакомимся за 2 минуты? 😊"
    ),
    "onboarding.child_birthdate": "Когда родилась {name}?\n\nНапиши дату (15.03.2023) или возраст (3 года)",
    "onboarding.child_birthdate_boy": "Когда родился {name}?\n\nНапиши дату (15.03.2023) или возраст (3 года)",
    "onboarding.child_birthdate_error": "Не поняла 🤔 Напиши дату (15.03.2023) или просто возраст цифрой",
    "onboarding.city": "В каком городе живёте? 🏙\n\nНужно для прогноза погоды",
    "onboarding.city_error": "Не нашла такой город 🤔 Попробуй написать по-другому",
    "onboarding.done": "🎉 Отлично!\n\nТеперь самое интересное — пришли 5 любимых вещей {target} и я соберу первый образ!\n\n📸 Фотографируй по одной вещи на светлом фоне",

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

    # Шоппинг-лист
    "shopping.premium_only": (
        "🛍 Шоппинг-лист доступен на Premium.\n\n"
        "Касси проанализирует гардероб и скажет что купить "
        "с учётом сезона и цветотипа.\n\n"
        "👉 /subscribe — 14 дней бесплатно"
    ),
    "shopping.too_few_items": "Добавь хотя бы 5 вещей в гардероб, и я смогу сделать анализ 📸",
    "shopping.generating": "🔍 Смотрю твой гардероб...",
    "shopping.header": "🛍 Что стоит купить {season}:\n\n{list}",
    "shopping.empty_result": "Гардероб выглядит хорошо — пока ничего срочного докупать не нужно 👍",
    "shopping.error": "Не удалось проанализировать гардероб. Попробуй позже.",

    # Помощь
    "help.text": (
        "Привет! Я Касси — твой личный стилист 👗\n\n"
        "📸 Пришли фото — добавлю в гардероб\n"
        "✨ Что надеть — соберу образ по погоде\n"
        "💬 Напиши вопрос — дам совет по стилю\n"
        "🛍 Подойдёт? — проверю покупку\n"
        "👤 Профиль — капсула, чемодан, настройки\n\n"
        "Каждое утро в 07:00 — готовый образ на день!\n\n"
        "Советы:\n"
        "• Фотографируй вещи по одной на светлом фоне\n"
        "• Чем больше вещей — тем интереснее образы\n"
        "• Нажми 👍 Надели — запомню и буду учитывать"
        "\n\nPremium:\n"
        "👗 /capsule — сезонная капсула\n"
        "🧳 /travel — собрать чемодан\n"
        "📊 Monthly report — приходит 1-го числа"
    ),

    # Реферальная программа
    "referral.info": (
        "🎁 Пригласи подругу!\n\n"
        "Твой код: {code}\n"
        "Поделись ссылкой — подруга получит 14 дней Premium бесплатно."
    ),

    # ── Wardrobe (photo upload, milestones) ──
    "wardrobe.looking": "✨ Смотрю что тут...",
    "wardrobe.looking_photo": "✨ Смотрю фото {n} из {total}...",
    "wardrobe.looking_multi": "✨ Получила {count} фото. Уже смотрю...",
    "wardrobe.looking_multi_limit": "✨ Получила {received} фото — возьму первые {total}. Уже смотрю...",
    "wardrobe.outfit_picking": "✨ Подбираю образ...",
    "wardrobe.outfit_ready": "Образ готов!",
    "wardrobe.outfit_timeout": "⏱ Подбор образа занял слишком долго. Попробуй ещё раз!",
    "wardrobe.outfit_busy": "⏳ Касси сейчас занята. Попробуй через пару минут!",
    "wardrobe.photo_timeout": "⏱ Фото не успело обработаться. Попробуй ещё раз.",
    "wardrobe.photo_expired": "⏱ Время вышло. Отправь фото ещё раз.",
    "wardrobe.photo_send_fail": "Не удалось загрузить фото. Попробуй ещё раз 📸",
    "wardrobe.photo_send_file": "Отправь фото, а не файл 📸",
    "wardrobe.photo_bad_network": "🌐 Проблема с сетью. Попробуй через минуту.",
    "wardrobe.photo_bad_quality": "😔 Не удалось разглядеть вещь. Попробуй переснять на светлом фоне.",
    "wardrobe.kassi_resting": "Касси сейчас отдыхает. Попробуй чуть позже!",
    "wardrobe.colortype_looking": "🔍 Смотрю на твой цветотип...",
    "wardrobe.need_start": "Сначала пройди настройку: /start",
    "wardrobe.evaluating": "⭐ Оцениваю...",
    "wardrobe.eval_failed": "Не удалось оценить образ. Попробуй ещё раз.",
    "wardrobe.photo_action": "Что делаем с фото?",
    "wardrobe.add_hint": "📸 Пришли фото — добавлю в гардероб!",
    "wardrobe.gap_analyzing": "📋 Смотрю твой гардероб...",
    "wardrobe.gap_running": "⏳ Уже смотрю, подожди немного...",
    "wardrobe.gap_complete": "✅ Гардероб укомплектован на этот сезон!",
    "wardrobe.remaining": "📸 Ещё {n} {suffix} — и я соберу первый образ!",
    "wardrobe.selfie_skip": "Хорошо! Когда будешь готова — зайди в Профиль → Цветотип 🎨",
    "wardrobe.colortype_set": "✨ {name} — {label}\nТеперь буду подбирать цвета под твой цветотип!",
    "wardrobe.milestone_3": "🎉 3 вещи есть! Собираю образ на завтра — секунду...",
    "wardrobe.milestone_3_mini": "🎉 Мини-образ разблокирован! Собираю...",
    "wardrobe.milestone_5": "🎉 5 вещей! Хочешь точнее подбирать цвета?\nПришли селфи — определю твой цветотип!",
    "wardrobe.milestone_7": "🎉 Первый полный образ!",
    "wardrobe.milestone_10": "🎉 10 вещей — классная база!",
    "wardrobe.milestone_done": "🎉 Гардероб собран! Завтра утром — первый образ.",

    # ── Billing ──
    "billing.unknown_plan": "Неизвестный план",
    "billing.need_start": "Сначала войди через /start",
    "billing.card_unavailable": "Оплата картой временно недоступна.",
    "billing.create_error": "Не получилось создать платёж. Попробуй ещё раз.",
    "billing.payment_received_no_user": "✅ Оплата получена! Напиши /start для обновления.",
    "billing.payment_db_error": "✅ Оплата получена, но произошла ошибка активации.\nНапиши /start — мы всё исправим.",
    "billing.activated": "✅ Premium активирован на {period}!\nВсе функции доступны. Добро пожаловать! 🎉",
    "billing.stay_free": "Хорошо! Ты всегда можешь вернуться к Premium 💎",
    "billing.your_plan": "Твой план: {plan}{days}",

    # ── Brief ──
    "brief.rerolling": "🔄 Подбираю другой вариант...",
    "brief.share_hint": "📤 Перешли картинку выше — на ней всё написано 👗",
    "brief.share_hint_short": "📤 Перешли картинку выше 👗",

    # ── Profile ──
    "profile.colortype_updated": "✅ Цветотип обновлён: {label}",
    "profile.girl_or_boy": "Девочка или мальчик? 🎀",
    "profile.child_name": "Как зовут {whom}? 👶\n(или «отмена»)",
    "profile.child_error": "Что-то пошло не так 🤔 Попробуй снова через /profile",
    "profile.save_error": "Ошибка при сохранении 😔 Попробуй снова",
    "profile.prefs_saved": "✅ Настройки сохранены! Образы будут точнее 🎯",

    # ── Onboarding ──
    "onboarding.resume": "Продолжить с места где остановилась?",
    "onboarding.who_for": "Привет! Я Касси — твой стилист 👗\nДля кого подбираем?",
    "onboarding.your_name": "Как тебя зовут?",
    "onboarding.child_name_ask": "Как зовут?",
    "onboarding.enter_name": "Введи имя:",
    "onboarding.child_age": "Сколько лет?",
    "onboarding.age_error": "Не поняла 🤔 Напиши возраст цифрой (например, 3)",
    "onboarding.enter_city": "Введи название города:",
    "onboarding.refine_city": "Уточни город:",

    # ── Ask friend ──
    "ask_friend.share_hint": "📤 Перешли картинку выше подруге 👗",
    "ask_friend.vote_unavailable": "Голосование недоступно 😔",
    "ask_friend.vote_closed": "Голосование завершено 😊",
    "ask_friend.load_failed": "Не удалось загрузить образ 😔",

    # ── Text handler ──
    "text.cancelled": "Отменено ✅",
    "text.city_not_found": "Не нашла такой город 🤔\nПопробуй по-другому или напиши «отмена»",
    "text.city_updated": "✅ Город обновлён: {city}",
    "text.size_clothing_range": "Размер одежды должен быть от 56 до 176",
    "text.size_shoe_range": "Размер обуви должен быть от 15 до 45",
    "text.size_parse_error": "Не поняла размер 🤔 Например: «104» или «104 27»",
    "text.size_save_error": "Ошибка сохранения размера. Попробуй ещё раз.",
    "text.size_updated": "✅ Размер обновлён: {details}",

    # ── Fitting ──
    "fitting.looking": "✨ Сейчас посмотрю...",

    # ── Boost ──
    "boost.evaluating": "✨ Оцениваю образ...",

    # ── Challenge / Quiz ──
    "challenge.later": "Ок, challenge подождёт! Напомню позже 💪",
    "quiz.later": "Ок, квиз подождёт! Напомню через пару дней 😊",

    # ── Shopping ──
    "shopping.already_running": "Уже смотрю, подожди немного...",

    # ── Browser ──
    "browser.item_not_found": "Вещь не найдена.",
    "browser.deleted": "Удалено",
    "browser.unknown_season": "Неизвестный сезон",

    # Capsule
    "capsule.premium_gate": (
        "👗 Сезонная капсула — фича Premium!\n\n"
        "Касси выберет лучшие вещи на сезон и покажет сколько образов можно собрать.\n\n"
        "👉 /subscribe — 14 дней бесплатно"
    ),
    "capsule.too_few": "Добавь хотя бы 5 вещей в гардероб — и я соберу капсулу 📸",
    "capsule.result": "👗 Капсула на {season}: {count} вещей → {combos} комбинаций!\n\nУбери остальное в коробку — и наслаждайся ✨",
    "capsule.title": "Капсула на",
    "capsule.your": "Твоя",
    "capsule.combos_word": "комбинаций",
    "capsule.share_btn": "📤 Поделиться",
    "capsule.ok_btn": "👍 Класс!",
    "capsule.thanks": "Рада, что нравится!",
    "capsule.share_hint": "Перешли карточку подруге — пусть тоже соберёт капсулу! 💫",
    "capsule.profile_btn": "👗 Моя капсула",

    # Travel
    "travel.premium_gate": (
        "🧳 Сборщик чемодана — фича Premium!\n\n"
        "Скажи куда едешь — соберу компактный чемодан из твоих вещей.\n\n"
        "👉 /subscribe — 14 дней бесплатно"
    ),
    "travel.ask_city": "🧳 Собираем чемодан!\n\nКуда едешь?",
    "travel.city_placeholder": "Город, напр. Барселона",
    "travel.invalid_city": "Напиши название города 🏙",
    "travel.ask_days": "🧳 {city} — отличный выбор!\n\n📅 Сколько дней?",
    "travel.ask_occasions": "🧳 {city}, {days} дней\n\nКакие планы? (нажми несколько)",
    "travel.build_btn": "✅ Собрать чемодан!",
    "travel.result_header": "🧳 Чемодан: {city}, {days} дней",

    # Monthly Report
    "report.caption": (
        "📊 Твой стиль: {month}\n\n"
        "{outfits} образов из {used} вещей — "
        "ты используешь {pct}% гардероба!\n\n"
        "💰 Примерная экономия: ~€{savings}"
    ),
    "report.share_btn": "📤 Поделиться",
    "report.ok_btn": "👍 Круто!",
    "report.teaser": (
        "📊 Твой monthly стиль-отчёт готов!\n\n"
        "В Premium — полная аналитика: сколько образов, экономия, стиль-тренды.\n\n"
        "👉 /subscribe"
    ),

    # Language
    "lang.choose": "🌍 Выбери язык:",
    "lang.changed": "✅ Язык изменён!",

    # Paywall — conversion-boosting messages
    "paywall.value_proof": (
        "За {days} дней ты надела {outfits} образов из {items} вещей.\n\n"
        "С Premium — ежедневные образы + капсула + чемодан.\n"
        "Стилист: ~$300. Касси: $9/мес.\n\n"
        "👉 /subscribe"
    ),
    "paywall.loss_aversion": (
        "Касси узнала тебя на {knows_pct}%.\n"
        "С Premium прогресс продолжится — образы станут ещё точнее.\n"
        "Без Premium — только вт и чт.\n\n"
        "👉 /subscribe"
    ),

    # Wardrobe diversity nudge
    "nudge.add_more_items": (
        "💡 {count} вещей → {combos} комбинаций.\n"
        "С {target} вещами будет ~{estimate}! Сфоткай ещё 📸"
    ),
}


def t(key: str, **kwargs: str) -> str:
    """Возвращает строку по ключу с подстановкой параметров."""
    template = STRINGS.get(key, key)
    return template.format(**kwargs) if kwargs else template
