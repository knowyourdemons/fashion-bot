# Fashion Bot — STATUS (21 марта 2026)

## Git: последние 20 коммитов
```
20b281b fix: brief card UX — 7 fixes from user feedback
1690ad3 fix: download photos before rendering collage, fix owner switch button
3779304 feat: Jinja2 HTML templates for brief cards via Playwright
d435b9f fix: remove --single-process flag from Chromium (crashes after 1st render)
f4b2af2 fix: renderer healthcheck (wget→node fetch), worker memory 512→768MB
eeb159c fix: renderer integration tests skip when Playwright not deployed
a3ee861 feat: migrate renderer from Satori to Playwright, improve outfit UX
ffd2baa templates added
938a29a fix: hybrid card layout matches design spec v3
3d9c972 fix: pass db_user to _rate_photos to fix NameError on context
6415422 Fix: register engagement task in slow_worker, clean .env duplicates
1d5f78c Add pre-push hook: run tests before every push
d30fe94 Fix wardrobe browser: add total count, align tests with new UI
0debc11 Redesign wardrobe browser: 3 screens with thumbnails, season editing, owner tabs
c07ab47 Fix tests: update chat_per_day free limit from 1 to 3
32af60e docs
89d1c09 Redesign wardrobe browsing UI with Satori 3x3 grid
e1f8337 Add colortype detection via selfie and adaptive Kassi tone
f51b452 Contextual chat improvements and trial degradation notifications
b35ef66 Serve landing page at root via FastAPI
```

## Тесты
- Всего: 957
- Passed: 952
- Skipped: 5 (renderer integration — require running Playwright)
- Failed: 0

## Контейнеры

| Контейнер | Статус | Uptime | Memory |
|-----------|--------|--------|--------|
| docker-app-1 | Up (healthy) | 4 мин | 113 MiB / 1.5 GiB |
| docker-worker-1 | Up (healthy) | 4 мин | 85 MiB / 768 MiB |
| docker-renderer-1 | Up (healthy) | 59 мин | 104 MiB / 768 MiB |
| docker-postgres-1 | Up (healthy) | 9 часов | 27 MiB / 512 MiB |
| docker-redis-1 | Up (healthy) | 46 часов | 4.5 MiB / 256 MiB |
| docker-cloudflared-1 | Up | 46 часов | 16 MiB |

## Renderer
- **Тип**: Playwright (Chromium headless). Satori заменён.
- **Health**: `{"status":"ok","connected":true}`
- **Время рендера**: ~83 мс (POST /render, 440px HTML→PNG)
- **Emoji**: цветные (NotoColorEmoji.ttf установлен в контейнере)
- **Кириллица**: работает (Nunito Regular/Bold + DejaVu + Inter)
- **Шрифты загружены**: Nunito-Regular.ttf, Nunito-Bold.ttf, Inter-Regular.otf, DejaVuSans.ttf, DejaVuSans-Bold.ttf
- **Шаблоны**: `tpl_hybrid.html`, `tpl_full.html`, `tpl_weather.html`, `tpl_morning.html`
- **Файл сервера**: `renderer/server.mjs` (224 строки, express + playwright)

## Коллаж (генерация образа)

### Файлы
| Файл | Строк | Роль |
|------|-------|------|
| `services/brief_card.py` | 396 | Точка входа: выбор шаблона по количеству фото |
| `services/brief_renderer.py` | 490 | Подготовка данных для шаблонов, рендер HTML→PNG |
| `services/image_builder.py` | 1175 | Satori JSON коллаж (старый путь), PIL fallback, утилиты |
| `services/collage_styles.py` | 1105 | 6 стилей Satori, палитра, зоны |

### Формат рендера
**Primary**: Jinja2 HTML → POST to Playwright → PNG (через `brief_renderer.py`)
**Legacy**: Satori JSON → POST to renderer → PNG (через `image_builder.py`, `collage_styles.py`)
**Fallback**: PIL 3-зонный layout (если рендерер недоступен)

### Три состояния карточки
| Фото | Шаблон | Содержимое |
|------|--------|------------|
| 0 | `tpl_weather.html` | Погода + слои одежды + совет Касси + CTA |
| 1–7 | `tpl_hybrid.html` | Фото + placeholder + missing + прогресс-бар + палитра + комментарий |
| 8+ | `tpl_full.html` | Flat-lay всех вещей + палитра + комментарий |

### Два тона
- **mom** (mom_girl/mom_boy): тёплая розовая палитра (`#F5EDE8→#F0E8E4`, акцент `#C0607A`)
- **woman** (no_kids/pregnant): холодная синяя палитра (`#E8EDF5→#E4E8F0`, акцент `#5070B0`)

### Реальные фото в коллаже
- **Работает**: `photo_id` → download via Telegram Bot API → `_auto_trim()` → base64 → CSS `background-image`
- **Pipeline**: `_download_slot_photos()` в `brief_card.py` (httpx async, timeout 15s)
- **Если фото недоступно**: показывает emoji placeholder на пастельном фоне

### Placeholder
- Emoji (👚👖🧥👟) на пастельном градиенте по цвету (`bg-pink`, `bg-blue` и т.д.)
- Opacity 0.5, размер 36px (hybrid) / 28px (full)
- 23 PNG-иконки в `assets/silhouettes/` (для Satori path, не используются в Playwright path)

### Палитра-кружочки
- **Есть**: до 5 кружочков, position absolute right:6px top:6px
- **Источник**: `collect_palette()` из `collage_styles.py` — цвета реальных вещей + placeholder рекомендации + цветотип (Весна/Лето/Осень/Зима)
- **Размер**: 10px диаметр, border 1.5px white
- **Фикс 20b281b**: ранее использовался простой `collect_palette` из `brief_renderer.py` (только реальные вещи), теперь переключён на богатый вариант

### Прогресс-бар (только hybrid, 1-7 фото)
- **Есть**: в `tpl_hybrid.html`
- **Размер**: 10px высота (было 4px), border-radius 5px
- **Контрастность**: акцент `#C0607A` на фоне `#E8D8DE` (mom) — хорошо видно
- **Текст**: 11px bold (было 8px), цвет `--c` (тёмный, было `--cm` блёклый)
- **Формат**: `2/8 · 📸 Сфоткай куртку!`
- **Threshold**: 8 для мам, 12 для женщин

### Подписи
- **Только для placeholder** (после фикса 20b281b)
- Формат: "Тип цвет" (max 28 символов), без emoji
- На реальных фото подписей нет

### Комментарий Касси
- **Источник**: `warm_outfit_comment()` в `services/outfit_builder.py`
- Шаблонный (не Haiku) — `random.choice()` из ~15 вариантов по score bracket
- **Score >= 8.5**: 4 варианта ("Отличный образ...", "Собрала классный...", ...)
- **Score 7.0-8.5**: 5 вариантов
- **Score 5.0-7.0**: 3 варианта
- **Score < 5.0**: 2 варианта
- **1 вещь**: отдельные 4 шаблона хвалят конкретную вещь, не "образ"
- **Anti-repeat**: предыдущий комментарий сохраняется в Redis (`last_kassi_comment:{user_id}`), исключается из выбора
- **Suffix**: "Совет: добавь {X} и {Y} в гардероб!" если есть missing slots

## Утренний / вечерний бриф

### Утренний бриф
- **Есть**: `worker/tasks/morning_brief.py` (1737 строк)
- **Время**: 07:00 по местному времени пользователя
- **Расписание**: `schedule_all()` каждый час, фильтрует по timezone
- **Batching**: по 500 пользователей (LIMIT/OFFSET)
- **Lock**: Redis `lock:brief:{user_id}:{date}` предотвращает дубликаты
- **Что отправляет**:
  - Для мам: коллаж (Playwright) + текст с погодой + кнопки
  - Для женщин: коллаж или только совет (зависит от наличия вещей)
  - Haiku-совет для взрослых, шаблонный комментарий для детских
- **Формат текста** (мам):
  ```
  🌅 Доброе утро!
  ☀️ +5°C → +2°C вечером

  👧 Алиса (садик):
  🩲 Под одежду: трусики, майка, носки
  💬 [Комментарий Касси]
  ```

### Вечерний бриф
- **Есть**: `worker/tasks/evening_push.py`
- **Время**: 20:00 UTC
- **Что отправляет**: напоминание-nudge (без коллажа)
  ```
  🌅 Завтра утром Касси подготовит образ для {child_name}!
  Добавь новые вещи сегодня вечером 📸
  ```
- **Отличие от утреннего**: только текст, нет генерации outfit

### Утренний update (погода изменилась)
- **Есть**: шаблон `tpl_morning.html`, функция `build_morning_update()` в `brief_card.py`
- Сравнивает утреннюю погоду с вечерним прогнозом
- Показывает что изменилось + мини-коллаж ключевых вещей

### Погода
- **3 значения**: temp_morning, temp_day, temp_evening
- **Источник**: Open-Meteo API через `services/brief_weather.py`
- **Geocoding**: Nominatim (город → координаты)
- **WMO codes** → emoji (☀️🌤⛅🌧❄️)

## Кнопки

### Под коллажем (inline keyboard)
| Состояние | Кнопки |
|-----------|--------|
| 0 фото | [📸 Сфоткать] [Потом] |
| 1-7 мама | [👍 Надели] [🔄 Другой] |
| 8+ мама | [👍 Надели] [🔄 Другой] [📤 Переслать] |
| 1-7 женщина | [👍 Нравится] [🔄 Другой] |
| 8+ женщина | [👍 Нравится] [🔄 Другой] [📤 Stories] |
| 0 женщина (advice only) | [Спасибо] [Ещё совет] |

### Re-roll
- **Outfit re-roll**: удаляет старое сообщение, отправляет новое (без засорения чата)
- **Advice re-roll**: редактирует текст существующего сообщения in-place
- **Лимит**: free=0, premium=3/день, admin=unlimited
- **Exclude set**: Redis SADD, накапливает показанные item_ids за день
- **Degradation**: day 12 trial → re-roll = 0

### Обрезка кнопок
- **Исправлено**: "Переодень" → "Другой", убрана 3-я кнопка из ряда мам 1-7
- Все кнопки умещаются в 2-3 в ряд (Telegram влезает)

## Обработка фото

### Pipeline
- **Async**: через PTB handler → `_analyze_and_save()` async
- **Media groups**: собираются 3 сек, потом обрабатываются батчем

### Прогрессивные сообщения
- Нет последовательных обновлений ("Анализирую..." → "Кофта!" → "Добавлена")
- **Одно финальное**: `✅ Добавила {count} вещей:` + список
- **Guided hints** (первые 3 вещи): "🎉 Первая! Ещё 2 — покажу мини-образ"
- **Стилист-комментарий** (Haiku, на 1-ю вещь)

### Время обработки
| Фаза | Время |
|------|-------|
| RMBG-1.4 inference | ~4 сек (1024×1024) |
| Vision API (Sonnet) | ~5-10 сек |
| Haiku comment | ~2-3 сек |
| **Итого** | **~12-20 сек** |

### RMBG
- **Primary**: RMBG-1.4 quantized (44MB, `/root/.u2net/rmbg14_quantized.onnx`)
- **Fallback**: silueta (43MB) → remove.bg API → оригинал RGB
- **Sync**: inference в том же процессе (threading.Lock + double-check singleton)
- **Не worker queue**: inline в app контейнере

## Онбординг

### Шаги (3 основных, 12 внутренних состояний)
1. **Для кого** → пол ребёнка → имя → возраст (мамы) ИЛИ имя (no_kids)
2. **Город** → geocoding → timezone
3. **Готово** → "Завтра в 07:00 пришлю образ"

### Данные
- segment: mom_girl / mom_boy / pregnant / no_kids
- child: name, gender, birthdate (из возраста)
- city, timezone
- **Цветотип**: НЕ спрашивается в онбординге (отдельно по milestone при 5 вещах)

### Post-onboarding
- "🎉 Отлично, {name}! Познакомились!"
- "Завтра в 07:00 пришлю погоду + совет по образу."
- Кнопки: [📸 Сфоткать первую вещь] [Потом]
- Progress bar: 🟪⬜⬜ визуальный

### Resume
- Если прервано: `/start` → "Продолжить / Начать заново"

## Меню

### Главное меню (ReplyKeyboard)
```
✨ Что надеть              ← full-width
👗 Гардероб  | 💬 Спросить Касси
👤 Профиль   | ❓ Помощь
```

### Маппинг → handlers
| Кнопка | Handler | Файл | Работает? |
|--------|---------|------|-----------|
| ✨ Что надеть | `handle_what_to_wear()` | wardrobe.py:2094 | ✅ |
| 👗 Гардероб | `handle_wardrobe_menu()` | wardrobe.py | ✅ |
| 💬 Спросить Касси | `handle_ask_kassi()` | wardrobe.py:2102 | ✅ |
| 👤 Профиль | `handle_profile()` | (profile handler) | ✅ |
| ❓ Помощь | `handle_help()` | help.py | ✅ |

**Прошлый баг "Что надеть → handle_rate_menu"**: ИСПРАВЛЕН, маппинг корректный.

## Гардероб

### Формат: visual browser (3 экрана)
1. **Overview** (`w:ov`): текстовые счётчики по категориям + фильтры
2. **Category Grid** (`w:cat:{cat}:{page}`): Satori 3×3 grid (9 thumbnails/page), PIL fallback
3. **Item Detail** (`w:it:{index}`): фото + метаданные + кнопки

### Фильтры
- **Сезон**: ❄️🌸☀️🍂 / все (toggle кнопки)
- **Owner**: 👩 мама / 👧👦 ребёнок (switch tabs)
- **Категория**: 12 категорий в фиксированном порядке

### Кэш
- Thumbnails: Redis, TTL 24ч (`_THUMB_TTL = 86400`)

## Чат "Спросить Касси"

### Реализован: ДА
- **Модель**: claude-haiku-4-5-20251001
- **Контекстный**: ДА — system prompt включает:
  - Segment, timezone, city, colortype, body_type
  - Текущая погода (WeatherService)
  - Wardrobe summary (cached, 1h TTL)
- **max_tokens**: 512

### Лимиты
| План | Сообщений/день |
|------|---------------|
| free | 3 |
| premium | 20 |
| admin | 9999 |
| trial day 14 | 3 |

### Rate limiting
- Redis key `chat_limit:{user_id}:{date}` → INCR + 86400 TTL
- Показывает остаток если ≤2 сообщения

## Подписки и trial

### Trial
- **Работает**: ДА
- **Активация**: при первом фото (`trial_started_at` = now)
- **Длительность**: 14 дней
- **Уровень**: полный premium

### Degradation (последние 3 дня trial)
| День | Осталось | Ограничение |
|------|----------|-------------|
| 12 | ≤2 дня | re-roll = 0 |
| 13 | ≤1 день | evening_brief = false |
| 14 | 0 дней | chat = 3/день, outfit = 1/день |

### Уведомления
- **День 12**: "Пробный период заканчивается через 2 дня" + кнопка подписки
- **День 14**: "Пробный период завершён! Бесплатный план: образ вт/чт, 3 сообщения/день."
- Redis dedup: `trial_warn_d12:{user_id}`, `trial_expired_d14:{user_id}`

### Stripe
- **Зарегистрирован**: `/subscribe`, callback `pay_stripe:`, timeout 30s
- **Статус**: реализован (billing/stripe_provider.py), webhook обработка

### Stars (Telegram Stars)
- **Зарегистрирован**: `pay_stars:`, `confirm_stars:`, `SUCCESSFUL_PAYMENT`
- **Статус**: реализован, PreCheckout + payment flow

### Цены
```
premium_monthly:   $9 / 700 Stars
premium_quarterly: $22 / 1700 Stars
premium_yearly:    $72 / 5500 Stars
```

## Milestones

### Реализованы: ДА (4 штуки)
| Milestone | Условие | Действие |
|-----------|---------|----------|
| `mini_outfit` | ≥3 вещей | "🎉 Мини-образ!" + генерация коллажа |
| `colortype_prompt` | ≥5 вещей | "Хочешь точнее подбирать цвета?" + кнопка селфи |
| `full_outfit` | ≥8 вещей (мамы) | "🎉 Первый полный образ!" + генерация |
| `wardrobe_collected` | ≥10 вещей (женщины) | "🎉 Гардероб собран!" |

### milestones_reached
- **Поле**: `User.milestones_reached` — JSONB list
- **Миграция**: `e5f6a7b8c9d0_add_milestones_reached_to_users.py`
- **Логика**: `check_milestones()` в `wardrobe.py:230-308`

## Инфра

### Sentry
- **Настроен**: ДА
- **DSN**: `https://bcc6aec7...@o4511082039934976.ingest.de.sentry.io/4511082045177936`
- **Интеграция**: app (FastAPI middleware), worker (init в consumer.py), PTB error handler, image_builder

### Auto-backup БД
- **Скрипт**: `backup.sh` (pg_dump → gzip → `/home/stas/backups/`)
- **Retention**: 7 дней
- **НЕ в crontab** — только ручной запуск ⚠️

### Health-check cron
- **Настроен**: `* * * * * /home/stas/fashion-bot/scripts/watchdog.sh`
- Пингует `/health` каждые 30 сек
- Worker heartbeat проверка
- 2 consecutive failures → алерт в Telegram

### Metrics digest
- **Не настроен** — нет Prometheus/Grafana (шаблон в docker-compose закомментирован)

### Деплой
- **Текущий**: `docker cp` + `docker restart` (быстро, но теряется при rebuild)
- **Rebuild**: `docker compose up --build -d` (полный, все docker cp теряются)
- **Pre-push hook**: `.githooks/pre-push` — запускает тесты перед push

## Известные баги

### Критические
- (нет)

### Средние
1. **backup.sh не в crontab** — бэкапы БД только вручную

### Косметические (известные, не критичные)
3. **SAWarning**: `Child.wardrobe_items` overlaps `User.wardrobe_items` — нужно `overlaps="wardrobe_items"`
4. **PTBUserWarning**: `per_message=False` в ConversationHandler — косметика
5. **RMBG inference ~4 сек** (1024×1024) — можно ускорить до ~1.5 сек при 512×512
6. **photo_url пустой** — фото только через Telegram file_id
7. **Онбординг**: размер обуви только int → нужен float (26.5)
8. **Помощь**: текст может содержать устаревшие пункты

### Не реализовано (из roadmap v1.0)
9. Прогрессивные сообщения при обработке фото ("Анализирую..." → "Кофта!")
10. Иконки/фото не заполняют ячейку (80% вместо ~60%)

## Файлы изменённые за последние 20 коммитов

```
 .githooks/pre-push                  |   22 +
 api/app.py                          |   14 +
 bot/app.py                          |   16 +-
 bot/handlers/brief.py               |  121 +++-
 bot/handlers/text.py                |   77 ++-
 bot/handlers/wardrobe.py            |  538 ++++++++++++---
 bot/handlers/wardrobe_browser.py    | 1227 ++++++++++++++++++++++++++++-------
 core/permissions.py                 |    4 +-
 docker/docker-compose.yml           |    8 +-
 docs/prompt_wardrobe_redesign.md    |  107 +++
 docs/roadmap_backlog.md             |  109 ++++
 renderer/Dockerfile                 |   21 +-
 renderer/package.json               |    9 +-
 renderer/server.mjs                 |  224 ++-----
 renderer/templates/tpl_full.html    |  120 ++++
 renderer/templates/tpl_hybrid.html  |  151 +++++
 renderer/templates/tpl_morning.html |  106 +++
 renderer/templates/tpl_weather.html |   97 +++
 requirements.txt                    |    1 +
 services/brief_card.py              | 1047 ++++++++----------------------
 services/brief_renderer.py          |  490 ++++++++++++++
 services/image_builder.py           |  131 +++-
 services/outfit_builder.py          |   32 +-
 services/scoring_comment.py         |  119 +++-
 tests/test_brief_renderer.py        |  666 +++++++++++++++++++
 tests/test_satori.py                |  215 +++++-
 tests/test_smoke.py                 |    2 +-
 tests/test_trial_degradation.py     |    2 +-
 tests/test_unit.py                  |    4 +-
 tests/test_wardrobe_browser.py      |   65 +-
 worker/slow_worker.py               |    2 +-
 worker/tasks/engagement.py          |    2 +-
 worker/tasks/morning_brief.py       |   34 +-
 worker/tasks/subscription_expiry.py |  141 +++-
 34 files changed, 4480 insertions(+), 1444 deletions(-)
```

### Ключевые изменения за сессию
- **Renderer**: Satori → Playwright (Chromium headless). 4 HTML шаблона.
- **Wardrobe browser**: полный редизайн, 3 экрана с thumbnails
- **Brief card**: 3 состояния (0/1-7/8+), 2 темы, палитра, прогресс-бар
- **UX фиксы**: прогресс-бар видимый, подписи убраны с фото, кнопки короче, палитра полная, re-roll без засорения чата
- **Тесты**: ~600 → 957 (+350)
