# Fashion Bot — CLAUDE.md

Архитектурные заметки и правила для разработки.

## Архитектура

- **FastAPI** (порт 8000) + python-telegram-bot в режиме webhook
- **Worker**: отдельный процесс (`python -m worker.consumer`), очередь через Redis (HIGH/LOW)
- **БД**: PostgreSQL 16 (asyncpg + SQLAlchemy 2.0 async)
- **Кэш/Очередь**: Redis 7
- **AI**: Anthropic API через `AnthropicPool` (`core/anthropic_client.py`)
- **Туннель**: Cloudflare Named Tunnel → `bot.fashioncastle.app` (постоянный URL)

## Структура проекта

```
bot/handlers/       — Telegram handlers (routing only, бизнес-логика в services/)
bot/middleware/     — auth.py (загрузка user из БД), typing.py (индикатор)
worker/tasks/       — cron задачи: morning_brief, evening_push, subscription_expiry, ...
worker/consumer.py  — FastWorker (HIGH) + SlowWorker (LOW)
db/models/          — SQLAlchemy модели (User, Child, WardrobeItem, BriefLog, ...)
db/crud/            — CRUD операции
db/seeds/           — taxonomy_seed, scoring_matrix_seed, dev_seed
services/           — scoring.py, weather.py, image_processor.py, usage.py, i18n/
core/               — anthropic_client.py, permissions.py, scheduler.py, queue.py
billing/            — stripe_provider.py, yukassa_provider.py (stub), paddle_provider.py (stub)
api/routes/webhooks.py — POST /telegram + POST /stripe
```

## Ключевые соглашения

- **DB сессии**: `AsyncWriteSession` для записи, `AsyncReadSession` для чтения
- **Логирование**: `structlog` (`logger = structlog.get_logger()`)
- **Конфигурация**: через `config.py` (pydantic `BaseSettings`, case-insensitive)
- **Строки UI**: `services/i18n/ru.py` через `t("key")`
- **Redis в боте**: `context.bot_data["redis"]`
- **Владелец вещей**: `child.id` если `segment=mom_girl/mom_boy`, иначе `user.id`
- **Ошибки Sentry**: `sentry_sdk.capture_exception(e)` в обработчиках

## Модели БД

```python
User:
  telegram_id (unique), name, city, timezone
  plan: "free" | "basic" | "family" | "premium" | "ultra"
  segment: "mom_girl" | "mom_boy" | "pregnant" | "no_kids"
  body_type, colortype
  plan_expires_at        # дата истечения ПЛАТНОЙ подписки
  trial_started_at, trial_ends_at  # trial (14 дней, начинается с первого фото)
  payment_provider: "stars" | "stripe" | "test"
  stripe_customer_id, subscription_id
  daily_requests_used, daily_requests_reset_at
  onboarding_completed

Child: user_id, name, birthdate, gender, colortype, current_size, shoe_size

WardrobeItem:
  owner_id (UUID), owner_type: "user" | "child"
  category_group (12 групп), category_code, type, color, style, brand
  season[], occasion[]
  photo_id, photo_url (пустой — R2 в v1.4), photo_hash (phash)
  score_item, score_breakdown (JSONB), score_version="v2.0"
  version (optimistic locking), deleted_at (soft delete)

ScoringMatrix: name, criteria (JSONB), max_score, version, is_active
BriefLog: user_id, date, outfit_items[], feedback, is_wow
```

## Система планов и лимитов (`core/permissions.py`)

### `get_effective_plan(user) -> str`
Приоритет: **admin > paid subscription > trial > legacy mapping**

```python
admin        # telegram_id in ADMIN_TELEGRAM_IDS
premium/ultra # plan_expires_at > now (иначе → "free")
premium       # trial_ends_at > now (trial активен)
legacy        # basic/family → "premium" через _PLAN_ALIAS
```

### LIMITS (текущие лимиты по плану)
```python
free:    photos=3, wardrobe=15, rate=3,  chat=3,  brief=[вт,чт], children=1
premium: photos=30, wardrobe=500, rate=20, chat=20, brief=ежедн., children=3
ultra:   photos=100, wardrobe=2000, rate=50, chat=50, brief=ежедн., children=10
admin:   все=9999
```

### PRICES (цены Premium)
```python
premium_monthly:   usd=9,  stars=700,  label_usd="Месяц — $9"
premium_quarterly: usd=22, stars=1700, label_usd="3 месяца — $22 (экономия $5)"
premium_yearly:    usd=72, stars=5500, label_usd="Год — $72 (экономия $36)"
```

### Вспомогательные функции
- `days_until_expiry(user)` → int | None
- `get_trial_days_left(user)` → int | None
- `is_trial_active(user)` → bool
- `is_brief_day(plan, timezone)` → bool
- `is_brief_day_tomorrow(plan, timezone)` → bool
- `get_limit(key, plan)` → int

## Платёжный флоу

### Telegram Stars
```
/subscribe
→ _subscribe_keyboard() (Stars всегда, Stripe если settings.stripe_secret_key)
→ pay_stars:{plan_key}
→ handle_pay_stars: edit_message_text с подтверждением
→ confirm_stars:{plan_key}
→ handle_confirm_stars: delete, send_invoice(currency="XTR", provider_token="")
→ PreCheckoutQuery → handle_pre_checkout (ответить в течение 10 сек!)
→ SUCCESSFUL_PAYMENT → handle_successful_payment → update_user_plan в БД
```

**Payload format**: `"premium:{plan_key}:{telegram_id}"`
**Test payload**: `"test:{plan_key}:{telegram_id}"` → Premium НЕ активируется

### Stripe
```
pay_stripe:{plan_key}
→ StripeProvider.create_invoice(user_id, plan, period)
→ Checkout Session URL → reply_text с ссылкой
→ Stripe webhook → POST /api/v1/webhooks/stripe
→ HMAC верификация → checkout.session.completed
→ _activate_premium_after_payment(telegram_id, plan, period, ...)
```

### Защиты
- **Double payment guard**: если `expire_days > 3` → показать статус, не показывать форму
- **Admin bypass**: admin видит `/test_subscribe` вместо формы оплаты

## Vision API (добавление вещей в гардероб)

- **Модель**: `claude-sonnet-4-6` (НЕ haiku — плохое качество!)
- **max_tokens**: 4096 (иначе обрезает JSON на больших ответах)
- **Ориентация**: вертикальное фото работает лучше
- **Дедупликация**: ОТКЛЮЧЕНА в v1.1 (`photo_hash` хранится, но не проверяется)
- **Prompt caching**: system промпт кэшируется через `cache_control: {type: "ephemeral"}`
- **Trial активация**: при первом фото атомарно `UPDATE WHERE trial_started_at IS NULL`

## Скоринг

- Матрицы в БД: таблица `scoring_matrices`, загружаются при старте
- Шкала: каждый критерий 0–2 × вес, нормируется в 10 баллов
- `score_version = "v2.0"` — текущая версия
- Возрастные варианты: `0-3`, `3-7`, `7-12`, `12-16`, `16-25`, `25-35`, `35-45`, `45+`
- Для беременных: `pregnant-1`, `pregnant-2`, `pregnant-3`

## AnthropicPool (`core/anthropic_client.py`)

- Ротация ключей round-robin по `ANTHROPIC_API_KEYS` (через запятую)
- Circuit breaker per key: CLOSED → OPEN → HALF_OPEN
- RPM лимитер: sliding window в Redis
- Auto-failover при `RateLimitError` / `APIStatusError`
- Модели: PRIMARY=claude-haiku-4-5, FALLBACK=claude-sonnet-4-6
- Логирует: input_tokens, output_tokens, cache_hit_tokens, cache_write_tokens

## Morning Brief (`worker/tasks/morning_brief.py`)

1. Загружает погоду (wttr.in, Redis кэш 1 час)
2. Выбирает вещи (`_select_outfit`) по сезону/температуре/поводу
3. Генерирует текст образа через Claude
4. Строит коллаж (`image_builder.build_collage`)
5. Отправляет в Telegram в 7:00 по timezone пользователя

Вечернее напоминание (`evening_push.py`) — отправляется если `is_brief_day_tomorrow`.

## Subscription Expiry (`worker/tasks/subscription_expiry.py`)

Ежедневно в 09:00 UTC. Ищет пользователей у которых:
```sql
WHERE trial_ends_at BETWEEN yesterday AND now
  AND plan = 'free'
  AND onboarding_completed = TRUE
  AND deleted_at IS NULL
  AND is_active = TRUE
```

Тест для конкретного пользователя: `notify_single_user_trial_expiry(telegram_id)`.

## Admin: `/test_subscribe`

Панель тестирования платёжного флоу (только `ADMIN_TELEGRAM_IDS`):

| Кнопка | Действие |
|--------|----------|
| 🎁 Trial 14д | Устанавливает trial на 14 дней |
| 💎 Premium 30д | Активирует premium на 30 дней |
| 🔄 Сбросить в free | Очищает все планы/trial |
| 📊 Лимиты | Показывает FREE/PREMIUM/ULTRA сравнение |
| 🔔 Запустить expiry | Имитирует окончание trial + уведомление |
| 🌅 Evening push | Тестовый вечерний push |
| 💳 Stars invoice (тест) | Отправляет invoice с payload `test:` |
| 🔄 Обновить | Перечитать пользователя из БД |

Статус-эмодзи: 🔴 free · 🟡 trial-premium · 🟢 paid-premium · 👑 admin

## Деплой

```bash
# VPS: 100.97.47.50 (Tailscale), Ubuntu 24.04 ARM64

# Полный rebuild (после изменений requirements или Dockerfile)
docker compose -f ~/fashion-bot/docker/docker-compose.yml up --build -d

# Обновить только код (без rebuild образа)
docker compose -f ~/fashion-bot/docker/docker-compose.yml restart app worker

# Логи
docker compose -f ~/fashion-bot/docker/docker-compose.yml logs -f app

# Миграции
docker compose exec app alembic upgrade head
```

**ВАЖНО**: После `docker compose up --build` все изменения через `docker cp` теряются.
Всегда синхронизируй с хоста: `docker compose cp src/ app:/app/`.

### Cloudflare Tunnel

URL: `bot.fashioncastle.app` (постоянный, не меняется при рестарте).

```yaml
# ~/.cloudflared/config.yml
tunnel: fashion-bot
credentials-file: /etc/cloudflared/{TUNNEL_ID}.json
ingress:
  - hostname: bot.fashioncastle.app
    service: http://app:8000
  - service: http_status:404
```

Права: `chmod 755 ~/.cloudflared && chmod 644 ~/.cloudflared/*.json ~/.cloudflared/config.yml`

## Переменные окружения

```bash
TELEGRAM_BOT_TOKEN          # токен @fashion_castle_bot
TELEGRAM_WEBHOOK_URL        # https://bot.fashioncastle.app
TELEGRAM_WEBHOOK_SECRET     # HMAC для верификации
ANTHROPIC_API_KEYS          # key1,key2,... (пул, ротация)
DATABASE_WRITE_URL          # postgresql+asyncpg://...?ssl=disable
DATABASE_READ_URL           # postgresql+asyncpg://...?ssl=disable
REDIS_URL                   # redis://redis:6379/0
ADMIN_TELEGRAM_IDS          # 195169 (через запятую)
PAYMENT_PROVIDER            # stars | stripe
STRIPE_SECRET_KEY           # sk_live_... или sk_test_...
STRIPE_WEBHOOK_SECRET       # whsec_...
ENVIRONMENT                 # dev | prod
SENTRY_DSN                  # опционально
```

## Важные ограничения (v1.1)

| Ограничение | Workaround | Roadmap |
|-------------|-----------|---------|
| `photo_url` пустой — фото только в Telegram | Используем `photo_id` | R2 в v1.4 |
| Нет возраста взрослых в онбординге | Предполагается 30 лет | v1.2 |
| Нет выбора триместра | Всегда `pregnant-2` | v1.2 |
| Дедупликация отключена | — | v1.2 |
| `test_stylist.py` — flaky | `--ignore` при запуске | — |

## Roadmap

- **v1.1** (текущая) — Vision, Morning Brief, Stars + Stripe, /test_subscribe, named Cloudflare tunnel
- **v1.2** — редактирование вещей, возраст в онбординге, матрицы скоринга v3
- **v1.4** — Cloudflare R2 storage, Sentry production, Paddle, referral program
- **v2.0** — публичный запуск, analytics dashboard, Ultra план
