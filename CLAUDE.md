# Fashion Bot — CLAUDE.md

## Инфраструктура
- VPS: agent-farm-2, user=stas, ~/fashion-bot, IP: 46.225.210.62
- Containers: docker-app-1 (FastAPI+PTB), docker-worker-1, docker-postgres-1, docker-redis-1, docker-renderer-1 (Satori), docker-watchdog-1, docker-cloudflared-1
- GitHub: knowyourdemons/fashion-bot
- CI/CD: GitHub Actions — Tests (pytest on push) → Deploy (SSH → docker compose build → recreate)
- Deploy: `./scripts/deploy.sh` (build-based, не docker cp). systemd fashionbot.service (auto-start on reboot)
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
  wardrobe_browser.py — просмотр гардероба, пагинация, удаление вещей
  onboarding.py    — ConversationHandler онбординга
  billing.py       — /subscribe, Stars/Stripe, платёжные callbacks
  text.py          — Haiku чат стилиста (_get_text_system по сегменту)
  brief.py         — feedback на morning brief:
                     Детский: "Надели"/"Другой"
                     Взрослый с коллажем: "Нравится"/"Другой"
                     Взрослый без вещей: "Спасибо"/"Ещё совет"
                     Реролл: outfit → delete old + send new; advice → edit in-place
  profile.py       — /profile, style preferences, colortype display
  debug.py         — /debug_eval, /debug_gaps, /debug_style, /debug_wardrobe (admin-only)
  shopping.py      — шоппинг-лист, gap-based рекомендации
  feedback.py      — сбор обратной связи от пользователей
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
  rmbg_task.py           — async bg removal: EXIF rotate → crop bbox → rembg → edge softening
                           → thumbnail 400×400 → Redis cache (7 дней)
  style_config.py        — COLORTYPE_PALETTES, WOW_PHRASES, _needs_tights
                           get_temp_regime() → lazy import из outfit_selector (избегая circular)
  subscription_expiry.py — уведомления об окончании trial
  evening_push.py        — вечерний push в 20:00
  engagement.py          — тизеры и engagement push
  reminders.py           — напоминания (3/7/30 дней без фото)
  birthday_alert.py      — алерт о скором дне рождения ребёнка (размеры)
  growth_alert.py        — алерт о росте ребёнка (пересмотр гардероба)
  gap_analysis.py        — AI gap insights в бриф
  daily_reset.py         — ежедневный сброс счётчиков usage
  analytics_report.py    — аналитика использования
  capsule_season.py      — сезонная ротация капсулы
  wardrobe_analysis.py   — анализ гардероба (versatility, orphans)
  taxonomy_review.py     — ревью неизвестных типов вещей
  unknown_items_report.py — отчёт о нераспознанных вещах
  cleanup_r2.py          — очистка старых файлов в R2
  declutter.py           — предложения по разбору гардероба
worker/consumer.py — FastWorker (HIGH, 4 concurrent) + SlowWorker (LOW, 2 concurrent)
                     Sentry init при старте worker
db/models/         — SQLAlchemy модели
db/crud/           — CRUD операции
db/seeds/          — taxonomy_seed, scoring_matrix_seed, dev_seed
services/
  color_harmony.py — HSL матрица 100+ цветов, color_compatibility(), score_outfit_colors()
  normalize.py     — 250+ типов + 150+ цветов: normalize_type(), normalize_color()
  photo_quality.py — Pre-Vision проверка: brightness, blur, contrast, auto-correction
  image_processor.py — resize, EXIF, phash, bg removal (RMBG-1.4 + silueta fallback)
                       Thread-safe singleton (threading.Lock + double-check) для каждой модели
                       Smart thumbnail pipeline: exif_rotate → auto_brightness → rembg
                       → soften_edges → pad_square_resize(400) → make_collage_thumbnail()
  brief_card.py    — Точка входа коллажа: 3 состояния (0/1-7/8+ фото)
                     Thumb cache: Redis thumb:{item_id} (7 дней)
                     Inline fallback: make_collage_thumbnail() если кэша нет
  brief_renderer.py — Jinja2 шаблоны → Playwright → PNG (440px)
  brief_formatter.py — форматирование текста брифа (детский/взрослый)
  brief_weather.py — геокодинг + погода для утреннего брифа
  weather_card.py  — PIL-рендеринг погодной карточки 440x520
  image_builder.py — Satori коллаж (legacy), PNG-иконки, фоны
                     _shadow_cache с LRU (max 32 entries)
                     Sentry capture на критических ошибках
  collage_styles.py — 6 стилей, atomic round-robin через Redis INCR (next_style_async)
  outfit_selector.py — КАНОНИЧЕСКАЯ _get_temp_regime() (единственный источник)
  outfit_engine.py — AI outfit selection (Haiku), 4 возрастных промпта
  outfit_builder.py — Slot assembly, base layer filter, collage params
  outfit_evaluator.py — оценка образа по фото: 6 измерений, cross-validation
  vision.py        — Claude Sonnet Vision, multi-item, bbox, post-validation
  scoring.py       — item/outfit scoring, capsule analysis, gap detection
  scoring_comment.py — fallback Haiku-комментарии (шаблоны)
  gap_analysis.py  — AI shopping list, пробелы гардероба
  share.py         — "спросить подругу" — share + голосование
  notifications.py — notification service
  weather.py, usage.py, i18n/
  storage/         — R2/Telegram storage providers
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
# 2133 теста (1487 функций + parametrize), pytest-forked для изоляции (22 марта 2026)
# CI: GitHub Actions запускает тесты на каждый push/PR
# Pre-push hook: .githooks/pre-push блокирует push если тесты не проходят
```

> **Правило**: после добавления тестов или значительных изменений — обновить CLAUDE.md (секция "Что сделано") и docs/STATUS.md.

## Известные баги / TODO (v1.0)
- "Что надеть" в меню вызывает handle_rate_menu вместо генерации образа → фикс маппинга
- Помощь: старый текст с "Оценить образ" → обновить
- ~~Носки/базовый слой видны в коллаже~~ — ИСПРАВЛЕНО (base layer filter)
- ~~Нет проверки минимального набора для образа~~ — ИСПРАВЛЕНО (has_minimum_outfit)
- ~~Vision не получает контекст (возраст/погода)~~ — ИСПРАВЛЕНО (vision context)
- ~~Шорты при +2° не переклассифицируются~~ — ИСПРАВЛЕНО (post-validation)
- ~~Комментарий "отличный образ" при 1 вещи~~ — ИСПРАВЛЕНО (item_count)
- Подписи на коллаже не центрированы для реальных фото (placeholder — ок)
- Иконки/фото не заполняют ячейку (80% вместо текущих ~60%)
- Онбординг: размер обуви только int → нужен float (26.5)
- Онбординг: лимиты применяются при загрузке первых 5 вещей → не применять
- photo_url пустой — фото только в Telegram file_id
- SAWarning про Child.wardrobe_items overlaps — косметика
- PTBUserWarning про per_message — косметика
- RMBG-1.4 inference ~4 сек (1024x1024 input) — можно попробовать 512x512 для ~1.5 сек

## Git log: 151 коммит за 20-22 марта 2026

### 22 марта (13 коммитов)
- `8d2f597` feat: 12-season colortype, style preferences, debug commands, 61 TA tests
- `8b91767` feat: professional outfit evaluation — 6 dimensions, cross-validation, 89 tests
- `dd7fcd8` feat: implement reminders, birthday alerts, gap insights in brief
- `31d958e` feat: expert panel simulation (50 tests) + 3 bug fixes
- `b9beccf` feat: pre-Vision photo quality assessment + auto-correction
- `6bdf970` feat: expand normalization to 250+ type synonyms, 150+ color synonyms
- `f4d00e9` feat: professional styling system — 12 improvements across 10 files
- `f93c45f` feat: 470 synthetic wardrobe tests + 2 outfit selector fixes
- + 5 docs/fix коммитов

### 21 марта (75 коммитов) — ключевые
**Фичи:** Outfit Engine v2 (AI Haiku), Playwright renderer (замена Satori), bbox crop, warmth filtering, adaptive onboarding, brief card system, evening brief, colortype selfie, contextual chat, cold user reminders
**Инфра:** CI/CD GitHub Actions, Sentry, API timeouts, rate limiting, RMBG-1.4 1536MB, async bg removal, pre-push hook
**Фиксы:** outfit generation 5 fixes, chat clutter, collage photos without bg, brief card UX 7 fixes, reroll crash
**Тесты:** +45 outfit fixes, +77 error paths + worker tasks, +19 dead code cleanup

### 20 марта (63 коммита) — ключевые
**Фичи:** smart brief (2 modes), morning brief Satori card, brief card redesign, 3 collage styles (flat_lay/story/moodboard по Miro), colortype placeholder dots, onboarding redesign, weather icons, wardrobe browser, Надели/Переодень кнопки
**Инфра:** Satori renderer в docker-compose, geocoding cache (7d Redis), weather cache (15min)
**Фиксы:** Open-Meteo weather, shopping list context-aware, gap analysis prompt, ~25 visual polish (palette, icons, layout, owner switching)
**Тесты:** +27 regression, +storage providers

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

### Outfit Engine v2: AI-powered selection
- **Новый модуль** `services/outfit_engine.py` — Haiku выбирает комбинацию из кандидатов
- **Единый вызов**: AI возвращает И выбор вещей И комментарий Касси (вместо двух раздельных вызовов)
- **Два промпта по сегменту**:
  - Мама: удобно, тепло, практично, без платья в садик при <10°
  - Женщина: стильно, цветовая гармония, неожиданные сочетания, цветотип
- **Ротация**: не повторять вчерашний top+bottom, не повторять образ за 5 дней (BriefLog)
- **Fallback**: если AI не ответил → rule-based `_select_outfit()` + template comment
- **Post-validation**: шорты при <10° → замена на штаны
- **Стоимость**: ~$0.00025/вызов (Haiku), дешевле прежних двух вызовов
- **Тесты**: 37 тестов (`test_outfit_engine.py`)

### Outfit generation: 5 фундаментальных фиксов
- **Фильтрация базового слоя**: носки, трусики, колготки, майки → НИКОГДА фото в коллаже. Только текст "🩲 трусики, носки". `_is_base_layer_item()` в `outfit_builder.py`, фильтр в `build_outfit_slots()`
- **Минимальный образ**: `has_minimum_outfit()` / `has_minimum_wardrobe()` — без top+bottom или one_piece → погодная карточка + CTA "сфоткай ещё". Применяется в wardrobe handler и morning brief
- **Vision с контекстом**: `_call_vision()` принимает age, season, temp, city. Контекст в user message помогает Vision не путать шорты/штаны
- **Post-validation Vision**: `_post_validate_vision()` — "шорты" при <10°C → "штаны", "сандалии" при <5°C → "кроссовки"
- **Адекватный комментарий**: `generate_outfit_comment()` + `item_count` — при 1-2 вещах НЕ хвалит "образ", мотивирует сфоткать ещё; при 3-5 про сочетание; при 6+ полный стилистический
- **Тесты**: 45 тестов (`test_outfit_fixes.py`)

## Что сделано (22 марта 2026)

### Профессиональная стилистика: 12 улучшений
- **Цветовая гармония в AI-промптах**: правило 60-30-10, 3 цвета max, monochrome/analogous/complementary
- **HSL матрица совместимости цветов** (`services/color_harmony.py`): 100+ русских цветов, score -2..+2
- **12-сезонная система цветотипов**: Bright/True/Light Spring, Light/True/Soft Summer и т.д. (72 палитры)
- **Body type в AI-промпте**: 5 типов фигуры → конкретные стилистические правила
- **4 возрастных промпта для детей**: 0-3 (безопасность), 3-7 (самостоятельность), 7-12 (баланс), 12-16 (самовыражение)
- **Occasion filtering**: фильтр по day_type (садик/школа/работа/прогулка/гости)
- **Wind chill + UV**: `calc_wind_chill()`, UV≥6 → шапка обязательна
- **Warmth consistency в rule-based selector**: нет пуховик+шорты
- **Item freshness**: +1.0 бонус для вещей не ношенных >7 дней
- **Capsule wardrobe**: versatility score, gap analysis, orphan detection
- **Scoring refactor**: color_harmony 2→3, occasion_fit 1→2, body_type_fit, safety (дети)
- **User style_preferences**: JSONB поле для avoid/prefer/style

### Нормализация типов и цветов (`services/normalize.py`)
- **250+ типов вещей**: капор→шапка, балаклава→шапка, кеды→кроссовки, баска→блузка, и т.д.
- **150+ цветов**: маренго→тёмно-серый, марсала→бордовый, цвет морской волны→бирюзовый
- **Детская одежда**: ползунки, распашонка, человечек, конверт, царапки
- **Обувь**: мюли, эспадрильи, лоферы, оксфорды, берцы, ботфорты
- **Интеграция**: нормализация при сохранении в wardrobe.py ДО записи в БД

### Pre-Vision проверка качества фото (`services/photo_quality.py`)
- **Яркость**: тёмные фото авто-осветляются перед Vision (экономия API)
- **Размытие**: Laplacian variance <30 → "держи телефон ровно"
- **Разрешение**: <200px → "отправь оригинал, не превью"
- **Контраст**: stddev <15 → "положи на контрастный фон"
- **Aspect ratio**: >4:1 → "похоже на скриншот"

### Оптимизация outfit selector
- **Сезонный fallback**: если нет top+bottom после фильтра → используй ВСЕ вещи
- **Score-based preference**: `_first()` сортирует по score_item desc
- **body_type передаётся** в select_outfit_ai из wardrobe handler и morning_brief

### Оценка образа по фото (`services/outfit_evaluator.py`)
- **6 измерений**: цвет (25%), пропорции (25%), стиль (20%), уместность (15%), детали (10%), креатив (5%)
- **Детская оценка**: безопасность, комфорт, цвета, погода, возраст (другие веса)
- **5 tier-ов**: Wow / Отличный / Хороший / Есть потенциал / Давай усилим!
- **Cross-validation**: HSL-матрица перепроверяет Vision на цветовые клэши
- **JSON-промпт**: Vision → JSON → cross-validation → formatted text
- **Контекст**: colortype, body_type, segment, child_age, wardrobe для замен
- **Правило пропорций, зеркальные селфи** — в промпте
- **CTA после оценки** + truncated fallback

### 12-season цветотип через селфи
- Vision prompt определяет 12 подтипов (Bright Spring, True Summer, etc.)
- Sub_season → COLORTYPE_PALETTES для точной палитры
- Backward-compatible: base season для карточки

### Style preferences (профиль)
- Кнопка 💅 в /profile → стиль + avoid list
- Сохраняется в user.style_preferences JSONB
- Используется в outfit_engine для персонализации

### Debug commands (admin-only)
- /debug_eval — настройки оценки, tiers, контекст юзера
- /debug_gaps — пробелы гардероба, категории, баланс
- /debug_style — colortype + палитра + preferences
- /debug_wardrobe — скоры, роли, versatility, orphans

### Тесты: 1053 → 2133 (+1080)
- 60 тестовых файлов, 1487 test-функций, 2133 кейса (с parametrize)
- Крупнейшие: test_outfit_evaluator (89), test_unit (88), test_morning_brief (56)
- Parametrize-интенсивные: test_wardrobe_optimizer (33 функций → ~470 кейсов), test_normalize (24 → ~175)
- Обновлены: test_outfit_engine, test_core2, test_regression

## Что сделано (23 марта 2026)

### Инфра: Morning Brief фикс + Deploy система
- **Бриф не приходил**: `schedule_all` зависала (cold_reminders без timeout) → `asyncio.timeout(120)` + `misfire_grace_time=300` + `max_instances=2`
- **Погода "сейчас"**: Open-Meteo `temp_now` вместо `temp_morning` (прогноз на 07:00 отличался от реальности)
- **Deploy скрипт**: `./scripts/deploy.sh` — build image → recreate containers (вместо docker cp). `--quick` без тестов, `--hotfix` для emergency

### UI подключение: Capsule, Travel, Monthly Report, EN
- **Capsule** (`bot/handlers/capsule.py`): /capsule + кнопка в профиле, premium gate, Satori PNG карточка
- **Travel** (`bot/handlers/travel.py`): 3-step inline flow (город → дни → occasions multi-select)
- **Monthly Report** (`worker/tasks/analytics_report.py`): cron 1-е число, PNG карточка premium, тизер free
- **EN localization**: `language` колонка, auto-detect из Telegram, language picker для unknown locale
- **i18n 100%**: 80+ ключей RU+EN, все хендлеры используют `t(key, lang)`

### Аксессуары Phase 1+2
- **category_group "bag"**: 21 тип сумок (рюкзак, клатч, кроссбоди, тоут, хобо, мини-сумка...)
- **Formality 1-5** для ВСЕХ категорий: 60+ типов в `FORMALITY_LEVELS` dict
- **Formality coherence check**: post-validation в outfit_engine (±1, creative styles ±2)
- **Jewelry**: 20 типов (серьги-гвоздики, колье, чокер, кулон...), `detect_metal_tone()`
- **Belt**: body-type aware, neckline+necklace rules в AI prompt
- **One statement rule** + `_count_statement_pieces()`
- **Gap analysis**: "нет сумок → рекомендуй кроссбоди"

### Скоринг v3: 8 измерений
- `color_harmony` (20%), `proportions` (20%), `style_coherence` (20%), `occasion_fit` (15%), `accessory_completeness` (10%, NEW), `shoe_bag_harmony` (5%, NEW), `details_polish` (5%), `creativity` (5%)
- **Segment overrides**: mom → occasion важнее; no_kids → accessories важнее
- **Body type** (`services/body_type.py`): 5 типов × clothing/shoes/bags правила

### Professional Styling: Contrast + Kibbe + Essence
- **Contrast level** (HIGH/MEDIUM/LOW) из селфи → outfit contrast matching
- **Kibbe family** (DRAMATIC/NATURAL/CLASSIC/GAMINE/ROMANTIC) → силуэт + ткани
- **Style essence** → настроение образа
- `build_full_styling_context()` — единая функция для AI prompt
- `fabric_kibbe_score()` — совместимость ткани с типом тела
- Всё из ТОГО ЖЕ селфи ($0 extra API cost)

### USP Features: Progressive Learning + Streak + Memory + Mood
- **Preference Learner** (`services/preference_learner.py`): implicit learning из BriefLog feedback, liked/disliked colors+types, avoid items, wore_rate. Cache Redis 24h
- **Streak** (`services/streak.py`): daily streak, freeze 1/week, milestones 3-100 дней, "Касси знает тебя на X%"
- **Kassi Memory** (`services/kassi_memory.py`): автофакты + explicit memory из чата ("не люблю жёлтый")
- **Mood** (`services/mood.py`): weather + weekday → outfit mood (дождь=warm, пятница=bright)
- **Landing**: "Стилист который учится на тебе" (repositioning)

### Conversion Optimization
- **Wardrobe nudge**: при < 8 вещей → "5 вещей → 4 combo. С 8 будет ~12!"
- **Smart paywall**: value_proof (реальные цифры use) + loss_aversion ("Касси знает на 47%")
- **Language picker**: non-RU/EN юзеры видят выбор на /start

### Критические баги — исправлены
- `photo_results` NameError → `photo_lines`
- `daily_requests_used` race condition → atomic INCR с RETURNING
- Payment без try/catch → transaction safety + Sentry + honest error message
- Photo counter не инкрементился → `redis.incr(photos_day:...)` после upload
- Chat/reroll limit race → atomic INCR-then-check
- Redis `aclose()` в worker tasks → убрано (singleton)
- `{knows_pct}` raw placeholder → formatted
- Mood energy string comparison → numeric `_max_energy()`
- N+1 query в preference_learner → batch query

### Техдолг
- 25 silent `except Exception: pass` → `logger.warning()` с контекстом
- Позиционирование Касси: 11 "AI/Анализирую" → подруга-тон
- Контекстные ошибки: timeout / сеть / перегрузка (не generic)
- Dead code `if False` block удалён
- **Antibot** (`bot/middleware/antibot.py`): per-user rate limiting + temp ban
- **Loki+Grafana**: сервисы в docker-compose (json-file logging, plugin optional)
- **4 worker tasks**: wardrobe_analysis, declutter, taxonomy_review, unknown_items_report
- **UV sunglasses**: "☀️ UV высокий — не забудь очки!" при UV≥6

### Онбординг UX + Pre-generation + Color Depth
- **Photo reactions**: персонализированная реакция Касси на каждое фото + прогресс-бар 🟩⬜
- **5-photo threshold**: minimum wardrobe снижен с 8 до 5 (с проверкой top+bottom)
- **Photo instruction**: текстовая инструкция при первом фото
- **Pre-generate briefs**: worker task `pre_generate_brief.py` (02:00 local, weather cache 12h TTL)
- **Color depth**: tonal_depth, chroma, color_flow_to, flow_strength (16-season equiv)

### Style Passport Stories + Selfie-first
- **Style Passport** (1080×1920): tpl_style_passport.html, dark gradient + gold, /style_passport command
- **Selfie-first**: no_kids/pregnant → селфи после города → паспорт → bridge к фото вещей
- **Animated status**: "Определяю цветотип..." → "Смотрю на черты лица..." → "Формирую палитру..."
- **Redo selfie**: кнопка "📸 Переснять селфи" в профиле
- **Jewelry hint для мам**: заколка/ободок/бантик (не взрослые серьги)

### Selfie refactor + Beta prep
- **Рефактор**: selfie analysis → `services/selfie_analysis.py` (7 функций из wardrobe.py)
- **Referral tracking**: `t.me/fashioncastle_bot?start=ref_SOURCE` → Redis analytics
- **Day 3/7 feedback**: автоматический запрос "Что нравится? Что улучшить?"
- **`/stats`**: admin dashboard (юзеры, streak, referral sources)

### Оркестрация + Мониторинг
- **systemd**: `fashionbot.service` — auto-start docker compose on reboot
- **Watchdog upgrade**: restart loop detection + log tail в Telegram alert + recovery notification
- **Healthcheck**: `start_period: 30s` grace для контейнеров
- **CI/CD**: Tests → Deploy via SSH (native, base64 key) → Telegram notification

### Критические баги — всего 12 исправлено
- `photo_results` NameError, `daily_requests_used` race condition, payment без try/catch
- Photo counter не инкрементился, chat/reroll limit race → atomic INCR
- Redis `aclose()` в workers, `{knows_pct}` placeholder, mood energy comparison
- N+1 query preference_learner, "Анализирую" в user text, deploy SSH key

### Тесты: 122 в test_e2e_flows.py, 4371 total
- Payment (9), Photo Pipeline (14), i18n (7), Scoring v3 (15), Accessories (5)
- Phase 3 (4), Preference (6), Streak (9), Mood (10), Memory (6)
- Conversion (6), Language (1), Comprehensive (11), Professional Styling (10)
- Style Passport (3), Pre-gen (2), Selfie Onboarding (2), Alembic (2), Antibot (2)

### Юнит-экономика (актуальная)
- **API cost**: $0.15/юзер/мес (prompt caching включён, маржа 98.4%)
- **Breakeven**: 1 paying user ($7.60/мес infra)
- **10 юзеров**: $1.50/мес API, $90 revenue (если все paid)
- **100 юзеров**: $14.50/мес API, $900 revenue

## Документация
- **WORKFLOW.md** — методология + deploy rules + red flags
- **claude_code_smart_brief.md** — спецификация умного брифа
- **docs/simulation_1000_users.md** — симуляция 1000 юзеров, unit economics, breakeven

## Деплой
```bash
./scripts/deploy.sh          # полный: test → build → restart → health check
./scripts/deploy.sh --quick  # без тестов
./scripts/deploy.sh --hotfix file1.py  # emergency docker cp
```
systemd: `sudo systemctl restart fashionbot` (auto-start on reboot enabled)

## Роадмап

### v1.0-v1.1 ✅ ГОТОВО
- Все базовые + продвинутые фичи, CI/CD, monitoring, i18n, deploy

### v1.2 ✅ ГОТОВО (23 марта — 1 сессия)
- ~~Антибот~~ — rate limiting + temp ban
- ~~4 worker tasks~~ — wardrobe_analysis, declutter, taxonomy_review, unknown_items_report
- ~~Professional styling~~ — contrast + Kibbe + essence + fabric-body harmony
- ~~Scoring v3~~ — 8 измерений + segment overrides
- ~~Аксессуары Phase 2~~ — jewelry, belt, metal tone, neckline rules
- ~~USP~~ — preference learning, streak, memory, mood, style passport
- ~~Онбординг UX~~ — reactions, progress, 5-photo, selfie-first, photo instruction
- ~~Pre-generate briefs~~ — overnight weather cache
- ~~Color depth~~ — tonal, chroma, flow seasons (16-season equiv)
- ~~Conversion~~ — smart paywall, nudge, language picker, referral tracking
- ~~Beta prep~~ — /stats, day 3/7 feedback, referral deep links
- ~~12 critical bugs~~ — fixed
- ~~Alembic migration~~ — 10 new columns

### v1.3 (апрель-май)
- ЮKassa для RU юзеров (после ИП)
- Шоппинг-лист + affiliate (Admitad/Skimlinks)
- Реферальная программа ("Пригласи подругу = +7 дней")
- A/B test paywall timing
- Prometheus dashboards

### v2.0 (июль)
- Ultra план, семейный аккаунт
- Маркетинг: TikTok/Reels, Telegram каналы для мам
- Беременность: триместр в онбординге
