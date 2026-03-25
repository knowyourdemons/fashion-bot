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
- Алиса: owner_id=acf0100d-ca11-4fce-815e-c516af11e710 (3г, девочка, Лето, 9 вещей)

## Архитектура
- **FastAPI** (порт 8000) + python-telegram-bot в режиме webhook
- **Worker**: отдельный процесс (`python -m worker.consumer`), очередь через Redis (HIGH/LOW)
- **БД**: PostgreSQL 16 (asyncpg + SQLAlchemy 2.0 async), pool_pre_ping + recycle 10 мин
- **Кэш/Очередь**: Redis 7 через singleton `core/redis.py` (max_connections=32)
- **AI**: Anthropic API через `AnthropicPool` (`core/anthropic_client.py`)
  - Два API ключа в пуле с atomic round-robin (asyncio.Lock) + circuit breaker
  - Таймауты: 30s стандартные вызовы, 60s vision вызовы
- **Мониторинг**: Sentry (app + worker), watchdog (`scripts/watchdog.py`) с алертами в Telegram
- **Rate limiting**: API middleware 60 req/min per IP (`api/middleware/rate_limit.py`), Vision 30 calls/day per user
- **Memory auto-scale**: watchdog bumps container memory при >80% usage (cap 3GB, 1GB host reserve)
- **Shared validation**: `services/validation.py` — единый модуль валидации Vision output, wardrobe items

## Стек
- Python 3.12, PTB 22.x, SQLAlchemy 2.0, asyncpg
- Vision: claude-sonnet-4-6 (НЕ haiku — плохое качество!)
- Чат/бриф/текст: claude-haiku-4-5-20251001
- Удаление фона: **Оптимизированный пайплайн** (24 марта 2026)
  - **Single-item** (bbox_area ≥ 0.55): CLAHE → RMBG-1.4 + postprocess → cloth-seg → GrabCut → remove.bg API
  - **Multi-item** (bbox_area < 0.55): sibling bbox masking → crop → cloth-seg first → RMBG fallback → intersection
  - Модели: `/root/.u2net/rmbg14_quantized.onnx` (44MB) + `/root/.u2net/cloth_seg_u2net.onnx` (168MB)
  - ISNet и silueta удалены (не используются, экономия 222MB в Docker image)
  - Тестовый скрипт: `scripts/mama_test.py` — 7 реальных групповых фото, 35 вещей
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
  image_processor.py — resize, EXIF, phash, bg removal (RMBG-1.4 + cloth-seg)
                       Thread-safe singleton (threading.Lock + double-check) для каждой модели
                       Smart thumbnail pipeline: exif_rotate → auto_brightness → rembg
                       → soften_edges → pad_square_resize(400) → make_collage_thumbnail()
                       Texture refinement: _refine_bbox_by_color() — Sobel gradient + LAB color
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
- Дедупликация: ОТКЛЮЧЕНА (мешала больше чем помогала)
- PIL НЕ рендерит unicode emoji — все тексты на коллаже БЕЗ эмодзи
- Скор цифрой НЕ показывать юзеру — только текстовый комментарий Haiku или шаблон
- Удаление фона: RMBG-1.4 quantized (44MB) + cloth-seg U2Net (168MB). ISNet и silueta удалены
- App контейнер 3072MB (cloth-seg 168MB + RMBG inference peak ~600MB + app ~110MB), worker 3072MB
- ssl=disable в DATABASE_URL: postgres не настроен на SSL
- listen_addresses='*' в postgres.conf: иначе контейнеры не коннектятся
- Иконки и фоны в git assets/ (не R2) — мгновенный доступ, нет HTTP
- `_get_temp_regime()` каноническая в `services/outfit_selector.py`, `style_config.py` делегирует через lazy import (избегая circular import с `_needs_tights`)
- cloth-seg ONNX output уже [0,1] — НЕ применять sigmoid повторно
- _postprocess_mask сохраняет компоненты ≥15% — иначе рукава удаляются как "шум"
- _detect_upside_down порог 3x (не 1.5x) — юбка шире плеч = нормально для платья
- bbox padding 4% для multi-item (2% обрезает края, 5% захватывает соседей)
- Sibling masking: цвет фона из углов изображения, заполнение bbox соседних вещей

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
# 4420 тестов (4371 технических + 48 продуктовых + 1 validation), pytest-forked (24 марта 2026)
# CI: GitHub Actions запускает тесты на каждый push/PR
# Pre-push hook: .githooks/pre-push блокирует push если тесты не проходят

# Product quality tests (regression после изменения промптов):
docker exec docker-app-1 python3 -m pytest /app/tests/test_product_quality.py -v
# 48 тестов: weather, formality, color, base_layer, duplicates, occasion, slots, outerwear
# 4 синтетические персоны × 7 температур × 8 checks
```

> **Правило**: после добавления тестов или значительных изменений — обновить CLAUDE.md (секция "Что сделано") и docs/STATUS.md.

## Известные баги / TODO
- photo_url пустой — фото только в Telegram file_id → нужен R2 pipeline
- Подписи на коллаже не центрированы для реальных фото
- Онбординг: размер обуви только int → нужен float (26.5)
- SAWarning про Child.wardrobe_items overlaps — косметика
- PTBUserWarning про per_message — косметика
- ~~Vision: носок определяется как "шапка с бантом"~~ — ИСПРАВЛЕНО (_reclassify_items: bbox ≤0.25 + no outerwear context → носки; force base_layer для носки/колготки/гольфы)
- Bg removal: тёмные вещи на тёмном полу — ограничение моделей, рекомендация "контрастный фон"
- Bg removal: мелкие перекрывающиеся вещи (трусики под платьем) — нужен instance segmentation

## Валидации (24 марта, полное покрытие)

### Outfit Engine: 23 post-validation правила
| Правило | Тип | Действие |
|---------|-----|----------|
| Slot exclusions (one_piece→no top/bottom) | Hard | Remove |
| Warmth consistency (spread ≤2) | Hard | Fallback |
| Style compatibility (sport≠formal) | Hard | Fallback |
| Formality coherence (±1, creative ±2) | Hard | Fallback |
| Minimum outfit (top+bottom or one_piece) | Hard | Fallback |
| Color harmony (HSL score <3/10) | Hard | Fallback |
| Shorts at cold (<10°) | Auto-swap | Replace |
| Rain priority (precip >50%) | Auto-swap | Replace |
| Colortype compliance | Soft | Warning |
| Statement pieces limit (max 1) | Soft | Warning |
| Bag-shoes formality (±1) | Soft | Warning |
| Metal tone consistency | Soft | Warning |
| Tights needed (<15° + skirt/dress) | Soft | Warning |
| Occasion-formality (садик≠каблуки) | Soft | Warning |
| Wind outerwear (≥15 km/h) | Soft | Warning |

### Vision: 7 валидаций на input
| Поле | Валидация |
|------|-----------|
| category_group | Whitelist (9 values), fallback через normalize_type() |
| season | Whitelist (4 values), invalid → filtered |
| occasion | Whitelist (9 values), invalid → filtered |
| warmth_level | Clamped 1-5 |
| formality_level | Clamped 1-5 |
| color | Empty → "неизвестный" |
| score_breakdown | Values clamped 1-3 |

### Security валидации
- **Payment idempotency**: Redis dedup by charge_id (7-day TTL)
- **Cross-user access**: owner_id check в get_by_id() + soft_delete()
- **Vote dedup**: voter_id tracking (anon → random ID)
- **Feedback enum**: VALID_FEEDBACK whitelist
- **Memory injection**: sanitize newlines, 200 char limit
- **Admin antibot exemption**: admin_ids не банятся
- **Vision cost guard**: 30 calls/day per user

## Коллаж: Magazine Flat-Lay (25 марта 2026)
- **Шаблон**: `tpl_flatlay.html` — Playwright рендер, белый фон, absolute positioning
- **Layout**: Row 1 (top + outerwear с перекрытием), Row 2 (bottom центр), Row 3 (bag + shoes)
- **Слоты**: top, top_2, outerwear, bottom, one_piece, footwear_1, bag, accessory_1, accessory_2, hat, scarf, tights
- **Placeholders**: пунктирные рамки для незаполненных слотов (🧥+куртку, 👟+обувь, 👜+сумку, 🕶+очки, 📿+ремень)
- **Progress bar**: "3/7 · Сфоткай куртку, обувь" (footer)
- **Vision `flat_lay_rotation`**: 0/90/180/270 — ориентация для flat-lay (пояс сверху, горловина сверху)
  - Сохраняется в bbox JSONB, пробрасывается через outfit_builder → prepare_items_flatlay
  - 5-zone CV fallback если Vision вернул 0 для portrait item
- **Ориентация по слоту**: top → landscape (рукава в стороны), bottom/outerwear → portrait
- **Переснятие**: кнопка "📸 Переснять" в detail view → Vision валидация → замена фото
- **Авто-ротация**: `_auto_rotate_to_vertical` выпрямляет наклонённые вещи (3-35°)
- **Bbox refinement**: сравнение с фоном (углы фото), 25% guard, background-aware trimming
- Подключён ко всем 6 точкам через `build_brief_card()`: "Что надеть", morning/evening brief, онбординг

## Тесты
- 4450 тестов (4371 + 26 flatlay/bbox/reclassify/rotate/resize + 48 продуктовых + 1 validation + 5 skipped), pytest-forked
- Юнит-экономика (25 марта 2026, реальные данные):
  - Vision Sonnet call: **~$0.03/фото** (после resize 768px)
  - Haiku call: **$0.0003** (outfit engine, chat, comments)
  - Free user: **~$0.12/мес** (3 фото + 1x "что надеть"/день + brief 2x/нед)
  - Premium user: **~$1.13/мес** (30 фото + 5x "что надеть" + brief ежедн + chat)
  - Infra: $7.60/мес (VPS)
  - Breakeven: 3-4% конверсия при 200+ users
  - 90% API cost = Vision Sonnet (фото). Haiku = копейки
  - Resize 768px внедрён (-40%), Haiku для Vision отклонён (плохое качество)

## Тестовая анкета
- `landing/test.html` — 7-шаговый опросник для бета-тестеров
- `POST /api/v1/test-survey` — результаты → Telegram (admin chat_id=195169)
- localStorage для auto-save прогресса между сессиями
- Кнопка "Отправить результаты" на последнем шаге

## Роадмап

### v1.0-v1.2 ✅ ГОТОВО
- Все базовые + продвинутые фичи, CI/CD, monitoring, i18n, deploy
- Professional styling, scoring v3, accessories, USP features
- Онбординг UX, pre-generate briefs, color depth, conversion

### v1.3 ✅ ГОТОВО (24-25 марта — 2 сессии)
- Magazine flat-lay коллаж (Playwright)
- Vision bbox refinement (background-aware)
- Vision reclassification (шапка→носки)
- flat_lay_rotation (Vision + 5-zone CV fallback)
- Кнопка "Переснять" с Vision валидацией
- Resize 768px (-40% Vision API cost)
- 4450 тестов, 26 новых
- Тестовая анкета с серверным сохранением

### v1.4 (апрель-май)
- ЮKassa для RU юзеров (после ИП)
- Шоппинг-лист + affiliate (Admitad/Skimlinks)
- Реферальная программа ("Пригласи подругу = +7 дней")
- A/B test paywall timing
- Prometheus dashboards

### v2.0 (июль)
- Ultra план, семейный аккаунт
- Маркетинг: TikTok/Reels, Telegram каналы для мам
- Беременность: триместр в онбординге
