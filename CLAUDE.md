# Fashion Bot — CLAUDE.md

## Инфраструктура
- VPS: agent-farm-01, user=stas, ~/fashion-bot
- Containers: docker-app-1 (FastAPI+PTB), docker-worker-1, docker-postgres-1, docker-redis-1, docker-renderer-1 (Satori)
- GitHub: knowyourdemons/fashion-bot
- CI/CD: GitHub Actions (`.github/workflows/test.yml`) — тесты на каждый push/PR
- Tunnel: bot.fashioncastle.app (именованный Cloudflare tunnel)
- Webhook: https://bot.fashioncastle.app/api/v1/webhooks/telegram
- Тест-пользователи: Стас telegram_id=195169 (plan=admin), жена telegram_id=263775083 (plan=free, тестирует как обычный юзер)
- Алиса: owner_id=acf0100d-ca11-4fce-815e-c516af11e710 (3г, девочка, Лето, 25 вещей)

## Архитектура
- **FastAPI** (порт 8000) + python-telegram-bot в режиме webhook
- **Worker**: отдельный процесс (`python -m worker.consumer`), очередь через Redis (HIGH/LOW)
- **БД**: PostgreSQL 16 (asyncpg + SQLAlchemy 2.0 async), pool_pre_ping + recycle 10 мин
- **Кэш/Очередь**: Redis 7 через singleton `core/redis.py` (max_connections=32)
- **AI**: Anthropic API через `AnthropicPool` (`core/anthropic_client.py`)
  - Два API ключа в пуле с atomic round-robin (asyncio.Lock) + circuit breaker
  - Таймауты: 30s стандартные вызовы, 60s vision вызовы
- **Мониторинг**: Sentry (app + worker), watchdog (`scripts/watchdog.py`) с алертами в Telegram
- **Rate limiting**: API middleware 60 req/min per IP (`api/middleware/rate_limit.py`)

## Стек
- Python 3.12, PTB 22.x, SQLAlchemy 2.0, asyncpg
- Vision: claude-sonnet-4-6 (НЕ haiku — плохое качество!)
- Чат/бриф/текст: claude-haiku-4-5-20251001
- Удаление фона: **RMBG-1.4 quantized** (44MB, ~4 сек), fallback: silueta → remove.bg API → RGB
  - Модель: `/root/.u2net/rmbg14_quantized.onnx` (env: `BG_REMOVAL_MODEL=rmbg14`)
  - Fallback: `/root/.u2net/silueta.onnx` (43MB, ~1.3 сек, менее качественная)
- Prompt caching: ephemeral везде
- onnxruntime 1.24.4, numpy 1.26.4

## Структура проекта
```
bot/handlers/
  wardrobe.py      — Vision, коллаж, owner switching, генерация образа
                     _track_task() для tracked background tasks
                     Транзакционные границы: photo upload в единой сессии
  onboarding.py    — ConversationHandler онбординга
  subscription.py  — /subscribe, /test_subscribe, Stars/Stripe
  text.py          — Haiku чат стилиста (_get_text_system по сегменту)
  brief.py         — feedback на morning brief:
                     Детский: "Надели"/"Переодень"
                     Взрослый с коллажем: "Нравится"/"Другой вариант"
                     Взрослый без вещей: "Спасибо"/"Ещё совет"
                     Реролл для взрослых перегенерирует совет через Haiku
  error.py         — PTB global error handler → Sentry
  menu.py          — get_main_menu(), кнопки
  help.py          — /help текст
  start.py         — /start handler
bot/middleware/    — auth.py (загрузка user из БД), typing.py
api/middleware/
  rate_limit.py    — Redis-based 60 req/min per IP, skip health+webhooks
  request_id.py    — X-Request-ID correlation
core/
  redis.py         — singleton Redis client (init_redis/get_redis/close_redis)
  queue.py         — RedisQueue с at-least-once delivery (RPOPLPUSH + ack)
  anthropic_client.py — AnthropicPool: atomic round-robin, circuit breaker, таймауты
  rate_limiter.py  — atomic Lua script rate limiter (no race conditions)
  scheduler.py     — APScheduler (cron задачи)
  circuit_breaker.py
  permissions.py   — лимиты, планы, trial логика (ЦЕНТРАЛЬНЫЙ ФАЙЛ)
worker/tasks/
  morning_brief.py       — бриф детский + взрослый, paginated schedule_all (batch 500)
  style_config.py        — COLORTYPE_PALETTES, WOW_PHRASES, _needs_tights
                           get_temp_regime() → lazy import из outfit_selector (избегая circular)
  subscription_expiry.py — уведомления об окончании trial
  evening_push.py        — вечерний push в 20:00
worker/consumer.py — FastWorker (HIGH, 4 concurrent) + SlowWorker (LOW, 2 concurrent)
                     Sentry init при старте worker
db/models/         — SQLAlchemy модели
db/crud/           — CRUD операции
db/seeds/          — taxonomy_seed, scoring_matrix_seed, dev_seed
services/
  image_processor.py — resize, EXIF, phash, bg removal (RMBG-1.4 + silueta fallback)
                       Thread-safe singleton (threading.Lock + double-check) для каждой модели
  image_builder.py — Satori коллаж, PNG-иконки, фоны
                     _shadow_cache с LRU (max 32 entries)
                     Sentry capture на критических ошибках
  collage_styles.py — 6 стилей, atomic round-robin через Redis INCR (next_style_async)
  outfit_selector.py — КАНОНИЧЕСКАЯ _get_temp_regime() (единственный источник)
  scoring.py, weather.py, usage.py, i18n/
billing/           — stripe_provider.py (таймаут 30s), yukassa_provider.py (stub), paddle_provider.py (stub)
scripts/
  watchdog.py      — health check + worker heartbeat мониторинг, Telegram алерты
  watchdog.sh      — crontab wrapper, auto-restart, логи в logs/watchdog.log
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
- Удаление фона: RMBG-1.4 quantized (44MB, лучше качество, ~4 сек). Silueta (43MB, ~1.3 сек) как fallback
- App контейнер 1536MB (RMBG inference peak ~600MB + app ~110MB), worker 512MB
- ssl=disable в DATABASE_URL: postgres не настроен на SSL
- listen_addresses='*' в postgres.conf: иначе контейнеры не коннектятся
- Иконки и фоны в git assets/ (не R2) — мгновенный доступ, нет HTTP
- `_get_temp_regime()` каноническая в `services/outfit_selector.py`, `style_config.py` делегирует через lazy import (избегая circular import с `_needs_tights`)

## Мониторинг и алерты
- **Sentry**: app (FastAPI middleware) + worker (init в consumer.py) + PTB error handler
  - Все unhandled exceptions → Sentry с user/chat context
  - image_builder критические ошибки → Sentry capture
- **Watchdog** (`scripts/watchdog.py`): cron каждую минуту
  - Пингует `/health` каждые 30 сек
  - Проверяет worker heartbeats в Redis
  - 2 consecutive failures → алерт в Telegram (admin chat_id)
  - Recovery notification при восстановлении
- **PG slow queries**: `log_min_duration_statement=500` (>500ms логируются)
- **Health check** (`/health`): Redis ping + DB SELECT 1, 503 при сбое

## Коллаж (`services/image_builder.py`)
- **Primary: Satori renderer** (http://172.18.0.1:3100) — magazine layout, ~0.1 сек
- **Fallback: PIL** — 3-зонный layout (если Satori недоступен)
- Satori: тёмный header "LOOK OF THE DAY", пастельные карточки по цвету вещи, палитра footer
- `build_collage_satori()` → POST JSON → PNG; `_build_layered_layout()` → PIL fallback
- `_build_grid()` — старый grid (backward compat для photo_ids)
- PNG-иконки из assets/silhouettes/ (23 шт) для placeholder
- auto-trim: обрезка прозрачных краёв фото (5% padding)
- Подписи: "Тип цвет" без эмодзи, max 28 символов
- Satori constraints: display:'flex' обязателен, нет CSS grid/position:absolute/emoji
- Style rotation: atomic Redis INCR (`next_style_async()`), local fallback

## Взрослый бриф
```
🌅 Доброе утро, {name}!
{weather_line}

💡 Идея на сегодня:
{haiku_advice}

[Нравится] [Другой вариант] [Переслать]   ← с коллажем
[Спасибо] [Ещё совет]                      ← без вещей
```
- Реролл для взрослых: перегенерация совета через Haiku (не outfit)
- Callback: `reroll_advice` (без brief_id) или `reroll:{brief_id}` (детский)

## Детский бриф (целевой формат)
```
👧 Алиса (садик):
🩲 Под одежду: трусики, майка, носки

💬 [Haiku-комментарий Касси с советом]

Как тебе образ?
[Надели] [Переодень]
```
Видимые вещи — на коллаже. Текст — только невидимые + комментарий.

## Меню (целевая структура)
```
✨ Что надеть              ← full-width, генерация образа
👗 Гардероб  | 💬 Спросить Касси
👤 Профиль   | ❓ Помощь
```

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
- Дни 12-14: постепенно отключаем re-roll → вечерний → чат

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
# 882 теста, pytest-forked для изоляции (21 марта 2026)
# CI: GitHub Actions запускает тесты на каждый push/PR
```

## Известные баги / TODO (v1.0)
- "Что надеть" в меню вызывает handle_rate_menu вместо генерации образа → фикс маппинга
- Помощь: старый текст с "Оценить образ" → обновить
- Подписи на коллаже не центрированы для реальных фото (placeholder — ок)
- Иконки/фото не заполняют ячейку (80% вместо текущих ~60%)
- Онбординг: размер обуви только int → нужен float (26.5)
- Онбординг: лимиты применяются при загрузке первых 5 вещей → не применять
- photo_url пустой — фото только в Telegram file_id
- SAWarning про Child.wardrobe_items overlaps — косметика
- PTBUserWarning про per_message — косметика
- RMBG-1.4 inference ~4 сек (1024x1024 input) — можно попробовать 512x512 для ~1.5 сек

## Что сделано (19 марта 2026)

### Локальное удаление фона (ONNX silueta)
- **Проблема:** sess.run() зависал навсегда — выглядело как threading deadlock
- **Причина:** OOM — контейнер 512MB, inference peak ~480MB + app ~110MB = 590MB > 512MB
- **Решение:** memory 512→1024MB, silueta.onnx (43MB, не u2net 176MB)
- `services/image_processor.py`: _run_silueta() → PNG с прозрачностью, 1.3 сек
- Fallback chain: local ONNX → remove.bg API → оригинал RGB
- Thread-safe singleton (threading.Lock + double-check)
- `docker/Dockerfile`: curl + скачивание silueta.onnx при build

### Инфраструктура: Фаза 1 (критические фиксы)
- **Redis singleton** (`core/redis.py`): заменены 17 отдельных `from_url()` на один пул (32 conn)
- **DB индексы** (миграция c3d4e5f6a7b8): 6 индексов
- **Health check** (`/health`): проверяет Redis ping + DB SELECT 1, 503 при сбое
- **ONNX thread safety**: threading.Lock + double-check pattern

### Инфраструктура: Фаза 2 (надёжность)
- **Queue at-least-once** (`core/queue.py`): RPOPLPUSH → processing list → LREM on ack
- **Exponential backoff**: retry задержки 1s → 4s → 16s
- **Background task tracking** (`wardrobe.py`): `_track_task()` вместо fire-and-forget
- **Pagination schedule_all()**: batch по 500 пользователей (LIMIT/OFFSET)
- **Atomic Anthropic pool**: asyncio.Lock + counter

### Инфраструктура: Фаза 3 (масштабирование)
- **Atomic rate limiter** (`core/rate_limiter.py`): Lua script (нет GET→INCR race)
- **CASCADE → SET NULL** (миграция d4e5f6a7b8c9): brief_log, outfit_log, events
- **Worker concurrency**: asyncio.Semaphore (fast=4, slow=2)
- **Correlation ID**: ContextVar + structlog.contextvars
- **Pool tuning**: pool_pre_ping=True, pool_recycle=600

### Satori Collage Renderer — 6 стилей с ротацией
- `build_collage_satori()` с atomic round-robin (Redis INCR, local fallback)
- 6 стилей: magazine, editorial, story_card, polaroid, palette_first, pro_stylist
- PIL fallback если Satori недоступен

### Цветотип через селфи (онбординг)
- Claude Vision (sonnet-4-6) анализирует селфи → Весна/Лето/Осень/Зима
- Кнопка "Пропустить" → ручной выбор

### Умный бриф: два режима + погодная карточка + палитра
- **Mode A** (полный гардероб): Satori коллаж
- **Mode B** (мало вещей): погодная карточка 440x520 PNG

## Что сделано (21 марта 2026)

### Технический аудит и фиксы
- **API таймауты**: asyncio.timeout 30/60s на Anthropic, httpx timeout на Stripe/weather/Telegram
- **Sentry полная интеграция**: PTB error handler, worker init, image_builder capture
- **Watchdog**: health check + worker heartbeat мониторинг, Telegram алерты, crontab
- **PG slow queries**: log_min_duration_statement=500 в docker-compose
- **API rate limiting**: 60 req/min per IP, Redis-based, skip health+webhooks
- **Loki/Grafana**: шаблон в docker-compose (закомментирован, готов к раскомментированию)

### RMBG-1.4 (удаление фона)
- Замена silueta на RMBG-1.4 quantized (44MB, значительно лучше качество на одежде)
- Fallback chain: RMBG-1.4 → silueta → remove.bg API → оригинал
- App контейнер 1024→1536MB (RMBG peak ~600MB)
- `BG_REMOVAL_MODEL=rmbg14` в .env

### Взрослый бриф: новый UX
- "Совет дня" → "Идея на сегодня"
- Кнопки: "Нравится"/"Другой вариант" (с коллажем), "Спасибо"/"Ещё совет" (без вещей)
- Реролл перегенерирует совет через Haiku (не outfit)

### Code quality
- Дедупликация `_get_temp_regime()`: единый источник в `outfit_selector.py`
- LRU cache для `_shadow_cache` (max 32)
- Atomic style counter через Redis INCR (`next_style_async`)
- User cache invalidation после оплаты/debug commands
- Transaction boundaries: photo upload в единой сессии

### Тесты: 595 → 882 (+287)
- `test_error_paths.py` (37) — API таймауты, Redis/DB failures, handler edge cases
- `test_worker_tasks.py` (40) — engagement, growth alerts, reminders, daily reset
- `test_vision.py` (34) — vision API parsing, crop quality
- `test_share_service.py` (14) — share voting, TTL
- `test_storage.py` (21) — R2/Telegram storage providers
- `test_notifications.py` (15) — notification service
- `test_brief_formatter.py` (29) — brief text formatting
- `test_brief_weather2.py` (26) — weather cards
- `test_crud.py` (25) — CRUD operations
- pytest-forked для изоляции тестов
- CI/CD: GitHub Actions на каждый push/PR

## Документация
- **WORKFLOW.md** — методология защитного проектирования (7 линз, 5 итераций, Three-Pass)
- **claude_code_smart_brief.md** — спецификация умного брифа: два режима + погода + палитра

## Роадмап

### v1.0 remaining (до запуска жене)
- Онбординг UX (Касси, fuzzy дата, "Для обоих", прогресс-бар)
- Visual polish: центрирование, иконки, контекст
- ~~Умный бриф~~ — ГОТОВО
- ~~Текстовые фиксы~~ — ГОТОВО
- ~~Sentry, CI/CD~~ — ГОТОВО
- ~~Удаление фона: RMBG-1.4~~ — ГОТОВО

### v1.1 (апрель)
- ~~Контекстный чат~~ — ГОТОВО
- ~~Re-roll~~ — ГОТОВО (детский + взрослый)
- ~~Вечерний образ 20:00~~ — ГОТОВО
- ~~Trial отключение дни 12-14~~ — ГОТОВО
- ~~rembg~~ — ГОТОВО (RMBG-1.4 quantized)
- ~~Sentry, CI/CD~~ — ГОТОВО
- /profile + /add_child
- Оценка образа по фото (вещь vs outfit detection)
- Gap analysis + growth alert WHO
- Тизеры, engagement push

### v1.2 (май)
- Шоппинг-лист + affiliate (Admitad/Skimlinks, H&M, Lamoda)
- ЮKassa (после ИП), Paddle
- Антибот, реферальная программа
- Prometheus + Grafana dashboards
- Loki log aggregation (шаблон готов в docker-compose)

### v2.0 (июль)
- Ultra план, семейный аккаунт, EN, маркетинг
