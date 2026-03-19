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
- **БД**: PostgreSQL 16 (asyncpg + SQLAlchemy 2.0 async), pool_pre_ping + recycle 10 мин
- **Кэш/Очередь**: Redis 7 через singleton `core/redis.py` (max_connections=32)
- **AI**: Anthropic API через `AnthropicPool` (`core/anthropic_client.py`)
- Два API ключа в пуле с atomic round-robin (asyncio.Lock) + circuit breaker

## Стек
- Python 3.12, PTB 22.x, SQLAlchemy 2.0, asyncpg
- Vision: claude-sonnet-4-6 (НЕ haiku — плохое качество!)
- Чат/бриф/текст: claude-haiku-4-5-20251001
- Удаление фона: **local ONNX silueta** (1.3 сек), fallback: remove.bg API ($0.002), fallback: RGB
- Prompt caching: ephemeral везде
- onnxruntime 1.24.4, numpy 1.26.4 (модель: /root/.u2net/silueta.onnx, 43MB)

## Структура проекта
```
bot/handlers/
  wardrobe.py      — Vision, коллаж, owner switching, генерация образа
                     _track_task() для tracked background tasks
  onboarding.py    — ConversationHandler онбординга
  subscription.py  — /subscribe, /test_subscribe, Stars/Stripe
  text.py          — Haiku чат стилиста (_get_text_system по сегменту)
  brief.py         — feedback "Надели"/"Другое" на morning brief
  menu.py          — get_main_menu(), кнопки
  help.py          — /help текст
  start.py         — /start handler
bot/middleware/    — auth.py (загрузка user из БД), typing.py
core/
  redis.py         — singleton Redis client (init_redis/get_redis/close_redis)
  queue.py         — RedisQueue с at-least-once delivery (RPOPLPUSH + ack)
  anthropic_client.py — AnthropicPool: atomic round-robin, circuit breaker
  rate_limiter.py  — atomic Lua script rate limiter (no race conditions)
  scheduler.py     — APScheduler (cron задачи)
  circuit_breaker.py
  permissions.py   — лимиты, планы, trial логика (ЦЕНТРАЛЬНЫЙ ФАЙЛ)
worker/tasks/
  morning_brief.py       — бриф детский + взрослый, paginated schedule_all (batch 500)
  style_config.py        — COLORTYPE_PALETTES, WOW_PHRASES, _needs_tights
  subscription_expiry.py — уведомления об окончании trial
  evening_push.py        — вечерний push в 20:00
worker/consumer.py — FastWorker (HIGH, 4 concurrent) + SlowWorker (LOW, 2 concurrent)
db/models/         — SQLAlchemy модели
db/crud/           — CRUD операции
db/seeds/          — taxonomy_seed, scoring_matrix_seed, dev_seed
services/
  image_processor.py — resize, EXIF, phash, ONNX silueta bg removal (thread-safe singleton)
  image_builder.py — 3-зонный коллаж, PNG-иконки, фоны
  scoring.py, weather.py, usage.py, i18n/
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
- Удаление фона: silueta.onnx (43MB) local, ~1.3 сек. НЕ u2net.onnx (176MB, не хватает RAM)
- App контейнер 1024MB (inference peak ~480MB + app ~110MB), worker 512MB
- ssl=disable в DATABASE_URL: postgres не настроен на SSL
- listen_addresses='*' в postgres.conf: иначе контейнеры не коннектятся
- Иконки и фоны в git assets/ (не R2) — мгновенный доступ, нет HTTP

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
# 585 тестов (март 2026)
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
  - `ix_wardrobe_items_owner` (owner_id, owner_type) WHERE deleted_at IS NULL
  - `ix_children_user_id` WHERE deleted_at IS NULL
  - `ix_brief_log_user_date`, `ix_outfit_log_user_date`, `ix_events_user_id`
  - `ix_users_active_onboarded` для schedule_all()
- **Health check** (`/health`): проверяет Redis ping + DB SELECT 1, 503 при сбое
- **ONNX thread safety**: threading.Lock + double-check pattern

### Инфраструктура: Фаза 2 (надёжность)
- **Queue at-least-once** (`core/queue.py`): RPOPLPUSH → processing list → LREM on ack
  - `recover_processing()` на старте worker'а — восстанавливает orphaned задачи
- **Exponential backoff**: retry задержки 1s → 4s → 16s вместо мгновенного retry
- **Background task tracking** (`wardrobe.py`): `_track_task()` вместо fire-and-forget
  - Graceful shutdown: ждёт до 10 сек завершения in-flight задач
- **Pagination schedule_all()**: batch по 500 пользователей (LIMIT/OFFSET)
- **Atomic Anthropic pool**: asyncio.Lock + counter вместо itertools.cycle

### Инфраструктура: Фаза 3 (масштабирование)
- **Atomic rate limiter** (`core/rate_limiter.py`): Lua script (нет GET→INCR race)
- **CASCADE → SET NULL** (миграция d4e5f6a7b8c9): brief_log, outfit_log, events
  - Soft-delete user больше не удаляет логи
- **Worker concurrency**: asyncio.Semaphore (fast=4, slow=2 параллельных задач)
  - Drain in-flight задач при shutdown (30 сек)
- **Correlation ID**: ContextVar + structlog.contextvars, все логи включают request_id
- **Pool tuning**: pool_pre_ping=True, pool_recycle=600 (detect stale connections)

### Satori Collage Renderer — 6 стилей с ротацией
- `build_collage_satori()` с round-robin по 6 стилям (`services/collage_styles.py`)
- **magazine**: тёмный header, цветные карточки, палитра footer
- **editorial**: белый фон, minimal, hero крупно, strip мелких
- **story_card**: градиент из цветов образа, translucent карточки
- **polaroid**: тёплый бежевый фон, белые рамки с тенью
- **palette_first**: крупные цветовые блоки + вещи под ними
- **pro_stylist**: flat lay стиль, минимум декора, offset layout
- Каждый стиль: ~0.08-0.23 сек, auto-trim, pastel bg, silhouette placeholder
- PIL fallback если Satori недоступен

### Roadmap фичи (v1.0 + v1.1)
- **Текст брифа**: уже компактный (5-7 строк), fix температуры round() (убрал `.0`)
- **Меню**: уже в целевой структуре (Что надеть full-width, Спросить Касси, Гардероб, Профиль, Помощь)
- **Контекстный чат**: wardrobe summary уже в system prompt Haiku (get_wardrobe_summary_cached)
- **Вечерний образ 20:00**: schedule_evening уже работает (cron :30, premium users)
- **Trial degradation дни 12-14**: get_effective_limits() подключён к handlers
  - День 12: reroll = 0 (brief.py)
  - День 13: evening_brief = False (schedule_evening)
  - День 14: chat = 1, outfit = 1 (text.py, help.py)

### Тесты: 425 → 585 (+160)
- `test_infra.py` (12) — Redis singleton, health check, ONNX safety, DB indexes
- `test_phase2.py` (17) — queue ack/recovery, backoff, task tracking, pagination, atomic pool
- `test_phase3.py` (22) — Lua rate limiter, cascade, concurrency, correlation ID, pool tuning
- `test_satori.py` (32) — 6 styles, round-robin, palette, zones, auto-trim, fallback, integration
- `test_trial_wiring.py` (5) — trial degradation wired into brief, text, help, evening schedule

## Роадмап

### v1.0 remaining (до запуска жене)
- Онбординг UX (Касси, fuzzy дата, "Для обоих", прогресс-бар)
- ~~Меню: "Что надеть" full-width + "Спросить Касси"~~ — ГОТОВО
- ~~Текст брифа 15→5 строк~~ — ГОТОВО (уже компактный + round temp fix)
- Visual polish: центрирование, иконки, контекст

### v1.1 (апрель)
- ~~Контекстный чат (wardrobe summary в system prompt)~~ — ГОТОВО
- Re-roll "переодень" (кнопка + exclude + Redis counter)
- ~~Вечерний образ 20:00 (scheduler по timezone)~~ — ГОТОВО
- ~~Trial отключение дни 12-14~~ — ГОТОВО (get_effective_limits в handlers)
- /profile + /add_child
- Оценка образа по фото (вещь vs outfit detection)
- Gap analysis + growth alert WHO
- Тизеры, engagement push, "переслать бабушке"
- ~~rembg u2net~~ — ГОТОВО (silueta.onnx local)
- Sentry, CI/CD

### v1.2 (май)
- Шоппинг-лист + affiliate (Admitad/Skimlinks, H&M, Lamoda)
- ЮKassa (после ИП), Paddle
- Антибот, реферальная программа

### v2.0 (июль)
- Ultra план, семейный аккаунт, EN, маркетинг
