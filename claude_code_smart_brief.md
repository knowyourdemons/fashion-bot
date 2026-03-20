# Fashion Bot — Умный бриф: два режима + погода + палитра

## ПЕРВЫМ ДЕЛОМ: Диагностика

```bash
# Что CC уже сделал?
cd /app
git log --oneline -15
cat CLAUDE.md | tail -50

# Satori сервер жив?
python3 -c "import requests; print(requests.get('http://172.18.0.1:3100/health', timeout=5).json())" 2>&1

# Текущий коллаж — PIL или Satori?
grep -n "satori\|SATORI\|collage_satori" /app/services/image_builder.py | head -5
grep -n "build_collage" /app/bot/handlers/wardrobe.py /app/worker/tasks/morning_brief.py | head -10

# Сколько вещей у тестового юзера
python3 -c "
from db.base import AsyncReadSession
from db.crud.wardrobe import get_owner_items
import asyncio
async def check():
    async with AsyncReadSession() as s:
        items = await get_owner_items(s, 'acf0100d-ca11-4fce-815e-c516af11e710', 'child')
        print(f'Items: {len(items)}')
        for i in items[:5]:
            has_photo = bool(getattr(i, 'photo_url', None) or getattr(i, 'telegram_file_id', None))
            print(f'  {i.type} {i.color} photo={has_photo}')
asyncio.run(check())
"
```

Написать мне результат диагностики прежде чем делать что-либо.

---

## КОНТЕКСТ ПРОБЛЕМЫ

Мама встаёт в 7 утра, видит бриф от Касси. Но в гардеробе мало вещей → коллаж из 80% placeholder. Это:
- Бесполезно (мама и так знает что нужна куртка при +4°C)
- Раздражает (пустые иконки = "у тебя нет вещей")
- Теряет доверие ("зачем мне этот бот если он показывает пустышки")

## РЕШЕНИЕ: Два режима брифа

### Режим A: "Полный гардероб" (реальных фото >= 3 И placeholder <= 50%)
Красивый коллаж из реальных вещей (Satori если работает, PIL fallback).
Как сейчас, но лучше.

### Режим B: "Мало вещей" (реальных фото < 3 ИЛИ placeholder > 50%)
НЕ коллаж. Вместо него — "Погодная карточка + палитра + совет".

---

## РЕЖИМ B: Погодная карточка

### Формат (Satori или текст+фото)

Карточка 440x500 PNG через Satori:

```
+----------------------------------+
|  Доброе утро!                    |  <- тёплый header
|  Алиса . садик . четверг         |
|                                  |
|  +----------------------------+  |
|  |  Утро    +4°C              |  |  <- погода на день
|  |  День    +8°C              |  |
|  |  Вечер   +3°C              |  |
|  |  Без осадков               |  |
|  +----------------------------+  |
|                                  |
|  Рекомендуемая палитра:          |
|  #### #### #### ####             |  <- 4 цветовых блока
|  тёпл  нейтр акцент  база       |
|                                  |
|  Совет Касси:                    |
|  "Куртка + шапка обязательно.    |
|  Под куртку - кофту или          |
|  лонгслив. На забирание          |
|  возьми шарф - похолодает."      |
|                                  |
|  Добавь ещё 3 вещи ->            |
|  соберу образ из ТВОИХ вещей!    |
|                                  |
|  Касси . твой личный стилист     |
+----------------------------------+
```

### Палитра цветов по погоде и сезону

```python
def _season_palette(temp: float, month: int) -> list[dict]:
    """Рекомендуемая палитра по температуре и сезону."""

    if temp < 0:  # Зима, мороз
        return [
            {"hex": "#8B4513", "name": "тёплый", "desc": "куртка/пуховик"},
            {"hex": "#F5F5DC", "name": "база", "desc": "флис/кофта"},
            {"hex": "#CD5C5C", "name": "акцент", "desc": "шапка/шарф"},
            {"hex": "#696969", "name": "нейтр", "desc": "штаны/обувь"},
        ]
    elif temp < 10:  # Прохладно
        return [
            {"hex": "#D2B48C", "name": "тёплый", "desc": "куртка/ветровка"},
            {"hex": "#F0E68C", "name": "светлый", "desc": "кофта/лонгслив"},
            {"hex": "#8FBC8F", "name": "акцент", "desc": "юбка/шарф"},
            {"hex": "#778899", "name": "база", "desc": "леггинсы/обувь"},
        ]
    elif temp < 20:  # Тепло
        return [
            {"hex": "#FFB6C1", "name": "нежный", "desc": "платье/топ"},
            {"hex": "#E6E6FA", "name": "светлый", "desc": "кофта"},
            {"hex": "#98FB98", "name": "свежий", "desc": "юбка/шорты"},
            {"hex": "#FFDEAD", "name": "тёплый", "desc": "сандалии"},
        ]
    else:  # Жарко
        return [
            {"hex": "#FFFFFF", "name": "белый", "desc": "футболка"},
            {"hex": "#87CEEB", "name": "голубой", "desc": "шорты"},
            {"hex": "#FFD700", "name": "яркий", "desc": "акцент"},
            {"hex": "#F5DEB3", "name": "песочный", "desc": "сандалии"},
        ]
```

### Совет Касси — через Haiku

```python
async def _generate_weather_advice(child_name, temp_morning, temp_day, temp_evening, precip, day_type) -> str:
    """Haiku генерирует совет по одежде на основе погоды."""
    prompt = f"""Ты Касси — детский стилист. Коротко (3-4 предложения) посоветуй что надеть ребёнку {child_name}.

Погода:
- Утро: {temp_morning}°C
- День: {temp_day}°C
- Вечер: {temp_evening}°C
- Осадки: {"дождь" if precip > 0.3 else "нет"}

Контекст: {day_type} (садик/школа/прогулка)

Формат: практичный совет, как подруга. Не перечисляй все вещи — выдели главное.
Упомяни если к вечеру похолодает (надо взять что-то с собой)."""

    response = await call_haiku(prompt)
    return response
```

---

## ПОГОДА: Расширить до утро/день/вечер

### Текущий weather.py — что есть

```bash
grep -n "def.*weather\|temp\|forecast\|hourly" /app/services/weather.py | head -15
cat /app/services/weather.py | head -50
```

### Что нужно добавить

Текущий API (OpenWeatherMap или какой используется) возвращает forecast. Нужно:

```python
async def get_day_weather(city: str) -> dict:
    """Погода на утро/день/вечер."""
    forecast = await _fetch_forecast(city)

    return {
        "temp_morning": forecast_at_hour(forecast, 7),   # 07:00
        "temp_day": forecast_at_hour(forecast, 14),       # 14:00
        "temp_evening": forecast_at_hour(forecast, 18),   # 18:00
        "temp_current": forecast["current"]["temp"],
        "precip_prob": max(f["pop"] for f in forecast["hourly"][:12]),
        "description": forecast["current"]["description"],
    }
```

Если API не поддерживает hourly — взять текущую + daily high/low:
```python
return {
    "temp_morning": current_temp,
    "temp_day": daily_high,
    "temp_evening": daily_low,
    ...
}
```

---

## УТРЕННИЙ vs ВЕЧЕРНИЙ БРИФ

### Утренний бриф (schedule_all, 07:00 local):

```python
async def generate_morning_brief(user, child, items, weather):
    real_photos = sum(1 for i in items if _has_photo(i))
    total = len(items)
    placeholder_ratio = 1 - (real_photos / max(total, 1))

    if real_photos >= 3 and placeholder_ratio <= 0.5:
        # Режим A: полный коллаж
        return await _generate_full_collage(user, child, items, weather)
    else:
        # Режим B: погодная карточка + палитра + совет
        return await _generate_weather_card(user, child, items, weather)
```

### Вечерний бриф (20:00 local, premium):

Всегда полный коллаж (если есть вещи). Это "подготовка на завтра".
Текст: "Образ на завтра для Алисы. Погода: утром +2, днём +6. Подготовь с вечера!"

### CTA в режиме B:

```python
needed = max(0, 8 - len(items))
cta = f"Добавь ещё {needed} вещей — и Касси соберёт образ из ТВОИХ вещей!"

keyboard = InlineKeyboardMarkup([
    [InlineKeyboardButton("Добавить вещи", callback_data="add_items_hint")],
])
```

---

## ТЕКСТОВЫЕ ФИКСЫ (попутно)

1. "Переслать бабушке" → "Переслать" (нейтрально — бабушке, няне, мужу)
2. "AI-стилист" → "твой личный стилист" — везде в коде:
```bash
grep -rn "AI.стилист\|AI-стилист\|AI стилист" /app/ --include="*.py" | head -10
# Заменить на "твой личный стилист"
```

---

## ПОРЯДОК ВЫПОЛНЕНИЯ (5 итераций)

### Итерация 1 — Диагностика + текстовые фиксы
1. git log, CLAUDE.md — что уже сделано?
2. Проверить Satori сервер
3. Текстовые фиксы: "переслать", "AI-стилист"
4. Проверить weather.py — что API отдаёт
СТОП: показать git log + что в weather API

### Итерация 2 — Расширить погоду
1. get_day_weather() → утро/день/вечер/осадки
2. Обновить header коллажа: "+4->+8->+3°C" вместо "+4°C"
СТОП: print(await get_day_weather("Vilnius"))

### Итерация 3 — Режим B: погодная карточка
1. _season_palette() по температуре
2. _generate_weather_advice() через Haiku
3. Satori шаблон погодной карточки (или текст если Satori не интегрирован)
4. Определение режима: real_photos >= 3 AND placeholder_ratio <= 0.5 → A, иначе → B
СТОП: тестовый юзер с мало вещей → получает погодную карточку вместо коллажа

### Итерация 4 — Интеграция в morning_brief
1. generate_morning_brief() с двумя режимами
2. CTA "Добавь ещё N вещей" с inline кнопкой
3. Вечерний бриф = всегда коллаж + "подготовь с вечера"
СТОП: утренний бриф для юзера с 3 вещами → погодная карточка. Для юзера с 10 вещами → коллаж.

### Итерация 5 — Тесты + деплой
1. Pytest
2. Ручной тест: отправить /debug_brief → проверить режим
3. Worker sync
СТОП: отчёт

---

## ПОСЛЕ ЗАВЕРШЕНИЯ (ОБЯЗАТЕЛЬНО)
1. Обновить CLAUDE.md "Что сделано"
2. git add -A && git commit -m "feat: smart brief modes + weather card + palette" && git push
3. Краткий отчёт: что сделано / что пропущено / что сломалось

## ФИКС: Кнопка "Переслать"

Текущее поведение: кнопка "Переслать" генерирует новое фото без кнопок → юзер потом всё равно жмёт нативный Forward.

Новое поведение: убрать отдельную кнопку "Переслать". Вместо этого:

1. Под коллажем только 2 кнопки: "Надели" и "Переодень"
2. Третья кнопка: "Переслать" с параметром `switch_inline_query_chosen_chat`:

```python
InlineKeyboardButton(
    "Переслать",
    switch_inline_query_chosen_chat=SwitchInlineQueryChosenChat(
        query=f"outfit:{brief_id}",
        allow_user_chats=True,
        allow_group_chats=True,
    )
)
```

АЛЬТЕРНАТИВА (если inline mode не настроен): отправить коллаж отдельным сообщением БЕЗ inline кнопок, с caption "Образ для {child_name} на сегодня". Telegram нативно позволяет переслать → Forward → выбор контакта. Проще и не требует inline mode.

Caption: "Образ для {child_name} на сегодня. Собрала Касси — твой личный стилист" (НЕ "AI-стилист").

## НЕ ТРОГАТЬ
- Satori server (renderer/server.mjs)
- scoring, permissions
- PIL код коллажа (fallback)
- Если Satori 6 стилей УЖЕ интегрированы предыдущим промтом — использовать их для режима A
