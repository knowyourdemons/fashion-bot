# Fashion Bot — CLAUDE.md

## Инфраструктура
- VPS: agent-farm-01, user=stas, ~/fashion-bot
- Containers: docker-app-1 (FastAPI+PTB), docker-worker-1, docker-postgres-1, docker-redis-1
- GitHub: knowyourdemons/fashion-bot
- Tunnel: bot.fashioncastle.app (именованный Cloudflare tunnel)
- Webhook: https://bot.fashioncastle.app/api/v1/webhooks/telegram
- Тест-пользователи: Стас telegram_id=195169 (plan=admin), жена telegram_id=263775083 (plan=free, тестирует как обычный юзер)
- Алиса: owner_id=acf0100d-ca11-4fce-815e-c516af11e710 (3г, девочка, Лето, 25 вещей)

## Архитектура
- **FastAPI** (порт 8000) + python-telegram-bot в режиме webhook
- **Worker**: отдельный процесс (`python -m worker.consumer`), очередь через Redis (HIGH/LOW)
- **БД**: PostgreSQL 16 (asyncpg + SQLAlchemy 2.0 async)
- **Кэш/Очередь**: Redis 7
- **AI**: Anthropic API через `AnthropicPool` (`core/anthropic_client.py`)
- Два API ключа в пуле с watchdog (автопереключение при 429)

## Стек
- Python 3.12, PTB 22.x, SQLAlchemy 2.0, asyncpg
- Vision: claude-sonnet-4-6 (НЕ haiku — плохое качество!)
- Чат/бриф/текст: claude-haiku-4-5-20251001
- remove.bg size=small ($0.002/фото), fallback: RGB без удаления фона
- Prompt caching: ephemeral везде

## Структура проекта
```
bot/handlers/
  wardrobe.py      — Vision, коллаж, owner switching, генерация образа
  onboarding.py    — ConversationHandler онбординга
  subscription.py  — /subscribe, /test_subscribe, Stars/Stripe
  text.py          — Haiku чат стилиста (_get_text_system по сегменту)
  brief.py         — feedback "Надели"/"Другое" на morning brief
  menu.py          — get_main_menu(), кнопки
  help.py          — /help текст
  start.py         — /start handler
bot/middleware/    — auth.py (загрузка user из БД), typing.py
worker/tasks/
  morning_brief.py       — бриф детский + взрослый (no_kids/pregnant)
  style_config.py        — COLORTYPE_PALETTES, WOW_PHRASES, _needs_tights
  subscription_expiry.py — уведомления об окончании trial
  evening_push.py        — вечерний push в 20:00
worker/consumer.py — FastWorker (HIGH) + SlowWorker (LOW)
db/models/         — SQLAlchemy модели
db/crud/           — CRUD операции
db/seeds/          — taxonomy_seed, scoring_matrix_seed, dev_seed
services/
  image_builder.py — 3-зонный коллаж, PNG-иконки, фоны
  scoring.py, weather.py, image_processor.py, usage.py, i18n/
permissions.py     — лимиты, планы, trial логика (ЦЕНТРАЛЬНЫЙ ФАЙЛ)
billing/           — stripe_provider.py, yukassa_provider.py (stub), paddle_provider.py (stub)
assets/
  silhouettes/     — 23 PNG-иконки (300×300 RGBA, outline style)
  backgrounds/     — 4 PNG-фона (1024×1536 RGB: girl/boy/adult/winter)
```

## Ключевые технические решения (почему так)
- Vision модель: claude-sonnet-4-6 (Haiku плохо распознаёт вещи)
- Фото вертикально: качество распознавания значительно лучше
- Дедупликация: ОТКЛЮЧЕНА (мешала больше чем помогала, вернём в v1.2)
- PIL НЕ рендерит unicode emoji — все тексты на коллаже БЕЗ эмодзи
- Скор цифрой НЕ показывать юзеру — только текстовый комментарий Haiku или шаблон
- remove.bg fallback: если API 402/ошибка → фото без удаления фона (RGB)
- ssl=disable в DATABASE_URL: postgres не настроен на SSL
- listen_addresses='*' в postgres.conf: иначе контейнеры не коннектятся
- Иконки и фоны в git assets/ (не R2) — мгновенный доступ, нет HTTP

## Коллаж (`services/image_builder.py`)
- 3-зонный layout: outerwear 420px → top+bottom 280px → обувь+акс 170px
- `_build_layered_layout()` — новый, `_build_grid()` — старый (backward compat)
- PNG-иконки из assets/silhouettes/ вместо PIL-рисования
- Фоны из assets/backgrounds/ по полу (girl/boy/adult/winter)
- Подписи: "Тип цвет" без эмодзи, max 28 символов, умная обрезка
- Плейсхолдеры: PNG-иконка + тип вещи по temp ("Куртка"/"Ветровка")
- Header: "Чт, 19 мар · +6°C · Алиса, садик" (без эмодзи)
- Footer: "Касси — твой личный стилист"
- Комментарий стиль: "Симпатичный образ, Алиса! Комфортно весь день. Совет: добавь куртку"

## Меню (целевая структура)
```
✨ Что надеть              ← full-width, генерация образа
👗 Гардероб  | 💬 Спросить Касси
👤 Профиль   | ❓ Помощь
```

## Текстовый бриф (целевой формат)
```
👧 Алиса (садик):
🩲 Под одежду: трусики, майка, носки

💬 [Haiku-комментарий Касси с советом]

Как тебе образ?
[Надели] [Другое]
```
Видимые вещи — на коллаже. Текст — только невидимые + комментарий.

## Скоринг
- 15 матриц: 8 boy/girl (по возрастам) + 4 взрослых + 3 беременных
- Haiku-комментарий ($0.002) — тёплый стиль Касси
- Fallback: _warm_outfit_comment() шаблоны с советами
- Цифра скора — ТОЛЬКО внутри для ранжирования, юзеру НЕ показывать

## Система планов и лимитов (`permissions.py`)

### `get_effective_plan(user) -> str`
Приоритет: **admin > paid subscription > trial > free**

### LIMITS
```
free:    photos=3, wardrobe=30, chat=1/день, outfit=1/день, brief=[вт,чт]
premium: photos=30, wardrobe=500, chat=20/день, outfit=5/день, brief=ежедн., re-roll=3/день
ultra:   ОТЛОЖЕН до v2.0
admin:   все=9999
```

### PRICES
```
premium_monthly:   usd=9,  stars=700
premium_quarterly: usd=22, stars=1700
premium_yearly:    usd=72, stars=5500
```

### Trial
- 14 дней полный premium с первого фото
- Дни 12-14: постепенно отключаем re-roll → вечерний → чат (TODO)

## Модели БД
```python
User:
  telegram_id (unique), name, city, timezone
  plan: "free" | "premium" | "ultra" | "admin"
  segment: "mom_girl" | "mom_boy" | "pregnant" | "no_kids"
  colortype, body_type
  plan_expires_at, trial_started_at, trial_ends_at
  payment_provider: "stars" | "stripe" | "test"
  onboarding_completed, onboarding_step

Child: user_id, name, birthdate, gender, colortype, current_size, shoe_size

WardrobeItem:
  owner_id (UUID), owner_type: "user" | "child"
  category_group, type, color, season
  photo_id, photo_url, photo_hash
  score_item, score_breakdown (JSONB), score_version="v2.0"
  show_in_collage (alpha ratio ≥15%)

ScoringMatrix: name, criteria (JSONB), max_score, is_active
BriefLog: user_id, date, outfit_items[], feedback, is_wow
```

## Деплой
```bash
# ВАЖНО: после изменений ВСЕГДА синхронизировать worker:
docker cp docker-app-1:/app/CHANGED_FILE /tmp/F
docker cp /tmp/F docker-worker-1:/app/CHANGED_FILE
docker restart docker-app-1 docker-worker-1

# Миграции
docker exec docker-app-1 alembic upgrade head

# Полный rebuild (ВСЕ docker cp теряются!)
docker compose -f ~/fashion-bot/docker/docker-compose.yml up --build -d
```

## Тестирование
```bash
docker exec docker-app-1 python3 -m pytest /app/tests/ -v --tb=short
# 425+ тестов
```

## Известные баги / TODO (v1.0)
- "Что надеть" в меню вызывает handle_rate_menu вместо генерации образа → фикс маппинга
- Помощь: старый текст с "Оценить образ" → обновить
- Температура с десятыми "+5.6°C" → round до целых
- Подписи на коллаже не центрированы для реальных фото (placeholder — ок)
- Иконки/фото не заполняют ячейку (80% вместо текущих ~60%)
- Онбординг: размер обуви только int → нужен float (26.5)
- Онбординг: лимиты применяются при загрузке первых 5 вещей → не применять
- photo_url пустой — фото только в Telegram file_id
- SAWarning про Child.wardrobe_items overlaps — косметика
- PTBUserWarning про per_message — косметика

## Роадмап

### v1.0 remaining (до запуска жене)
- Онбординг UX (Касси, fuzzy дата, "Для обоих", прогресс-бар)
- Меню: "Что надеть" full-width + "Спросить Касси" + handlers
- Текст брифа 15→5 строк
- Visual polish: центрирование, иконки, контекст

### v1.1 (апрель)
- Контекстный чат (wardrobe summary в system prompt)
- Re-roll "переодень" (кнопка + exclude + Redis counter)
- Вечерний образ 20:00 (scheduler по timezone)
- Trial отключение дни 12-14
- /profile + /add_child
- Оценка образа по фото (вещь vs outfit detection)
- Gap analysis + growth alert WHO
- Тизеры, engagement push, "переслать бабушке"
- rembg u2net (когда VPS 8GB)
- Sentry, CI/CD

### v1.2 (май)
- Шоппинг-лист + affiliate (Admitad/Skimlinks, H&M, Lamoda)
- ЮKassa (после ИП), Paddle
- Антибот, реферальная программа

### v2.0 (июль)
- Ultra план, семейный аккаунт, EN, маркетинг
