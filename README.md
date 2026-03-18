# Fashion Bot — AI-стилист в Telegram

AI-стилист в Telegram: анализирует одежду по фото, ведёт персональный гардероб,
отправляет утренний образ дня (Morning Brief) и отвечает на вопросы по стилю.

## Быстрый старт

```bash
cp .env.example .env
# Заполни .env (TELEGRAM_BOT_TOKEN, ANTHROPIC_API_KEYS и т.д.)
make dev        # docker-compose up --build
make migrate    # alembic upgrade head
make seed       # taxonomy + scoring_matrix + dev данные
```

Бот доступен через Cloudflare Tunnel — URL стабильный (`bot.fashioncastle.app`).

---

## Архитектура

```
Telegram (webhook)
       │
  ┌────▼─────┐     ┌──────────────────────────────────┐
  │  bot/    │────►│         services/                 │
  │ handlers │     │  scoring · weather · image_proc   │
  └────┬─────┘     │  image_builder · notifications    │
       │           └──────────────┬───────────────────-┘
  ┌────▼─────┐                    │
  │  api/    │     ┌──────────────▼──────────────┐
  │  routes  │────►│          core/              │
  └────┬─────┘     │  AnthropicPool · Scheduler  │
       │           │  RedisQueue · Permissions   │
  ┌────▼─────┐     │  RateLimiter · CircuitBreak │
  │ worker/  │     └──────────────┬──────────────┘
  │ consumer │                    │
  └──────────┘     ┌──────────────▼──────────────┐
                   │     PostgreSQL  +  Redis     │
                   └─────────────────────────────┘
```

**Главный принцип:** `bot/` и `api/` — только routing и UI.
Вся бизнес-логика в `services/` и `worker/tasks/`.

---

## Структура проекта

```
fashion-bot/
├── main.py                    # Точка входа: FastAPI + Telegram webhook + Scheduler
├── config.py                  # pydantic-settings из .env
├── exceptions.py              # FashionBotError и наследники
├── Makefile                   # Команды разработки
├── requirements.txt
├── alembic.ini
│
├── bot/
│   ├── app.py                 # Регистрация всех handlers
│   ├── handlers/
│   │   ├── onboarding.py      # /start, ConversationHandler (сегмент, город, тип тела)
│   │   ├── wardrobe.py        # Фото → Vision AI, просмотр, оценка образа
│   │   ├── billing.py         # /subscribe, Stars/Stripe оплата
│   │   ├── test_billing.py    # /test_subscribe — admin-only панель тестирования
│   │   ├── brief.py           # Фидбек на Morning Brief
│   │   ├── text.py            # Текст → стилист (Claude)
│   │   ├── profile.py         # Настройки пользователя
│   │   ├── help.py
│   │   ├── menu.py            # Главное меню (Reply Keyboard)
│   │   ├── feedback.py
│   │   └── debug.py
│   └── middleware/
│       ├── auth.py            # Авторизация (создание/загрузка User из БД)
│       └── typing.py          # Индикатор "печатает..."
│
├── api/
│   ├── app.py                 # FastAPI factory
│   └── routes/
│       ├── webhooks.py        # POST /telegram + POST /stripe (Stripe webhook)
│       ├── auth.py
│       ├── wardrobe.py
│       ├── brief.py
│       ├── billing.py
│       └── onboarding.py
│
├── worker/
│   ├── consumer.py            # FastWorker (HIGH) + SlowWorker (LOW) через Redis
│   ├── fast_worker.py
│   ├── slow_worker.py
│   └── tasks/
│       ├── morning_brief.py   # Генерация образа дня + push уведомление
│       ├── evening_push.py    # Вечернее напоминание (если завтра бриф)
│       ├── subscription_expiry.py  # Уведомление об окончании trial
│       ├── daily_reset.py     # Сброс дневных лимитов
│       ├── style_config.py    # Определение стиля пользователя
│       ├── capsule_season.py  # Сезонный анализ гардероба
│       ├── gap_analysis.py    # Поиск недостающих вещей
│       ├── wardrobe_analysis.py
│       ├── analytics_report.py
│       ├── cleanup_r2.py
│       └── ...
│
├── core/
│   ├── anthropic_client.py   # AnthropicPool: ротация ключей, circuit breaker
│   ├── permissions.py        # Планы, лимиты, PRICES, LIMITS, get_effective_plan
│   ├── scheduler.py          # APScheduler (cron задачи)
│   ├── queue.py              # RedisQueue HIGH/LOW
│   ├── rate_limiter.py       # RPM лимитер по ключу
│   └── circuit_breaker.py    # Fault tolerance для внешних API
│
├── db/
│   ├── base.py               # AsyncWriteSession / AsyncReadSession
│   ├── models/               # User, Child, WardrobeItem, BriefLog, ScoringMatrix, …
│   ├── crud/                 # users, children, wardrobe, scoring, taxonomy, brief_log
│   ├── seeds/                # taxonomy_seed, scoring_matrix_seed, dev_seed
│   └── migrations/           # Alembic versions
│
├── services/
│   ├── scoring.py            # Скоринг вещей и образов (по матрицам из БД)
│   ├── weather.py            # wttr.in: советы по одежде (7 диапазонов температур)
│   ├── image_processor.py    # Resize, EXIF strip, phash дедупликация
│   ├── image_builder.py      # Генерация коллажей
│   ├── usage.py              # Подсчёт дневных лимитов
│   ├── notifications.py      # Push через Telegram Bot
│   ├── share.py              # Социальный шаринг образов
│   ├── i18n/ru.py            # ~400+ строк интерфейса
│   └── storage/              # Telegram storage (текущий), R2 (v1.4)
│
├── billing/
│   ├── base.py               # Абстрактный PaymentProvider
│   ├── stripe_provider.py    # Stripe Checkout Sessions
│   ├── yukassa_provider.py   # Заглушка (NotImplementedError)
│   └── paddle_provider.py    # Заглушка (NotImplementedError)
│
├── tests/                    # pytest + pytest-asyncio (240+ тестов)
│   ├── test_smoke.py
│   ├── test_unit.py
│   └── ...
│
└── docker/
    ├── Dockerfile
    ├── docker-compose.yml     # Dev: app + worker + postgres + redis + cloudflared
    ├── nginx.conf
    └── postgres.conf
```

---

## Планы и лимиты

### Текущая система планов

| | Free | Premium | Ultra | Admin |
|---|---|---|---|---|
| **Фото/день** | 3 | 30 | 100 | ∞ |
| **Размер гардероба** | 15 | 500 | 2 000 | ∞ |
| **Оценок образа/день** | 3 | 20 | 50 | ∞ |
| **Вопросов стилисту/день** | 3 | 20 | 50 | ∞ |
| **Образ дня/день** | 1 | 5 | 10 | ∞ |
| **Бриф** | Вт + Чт | Каждый день | Каждый день | Каждый день |
| **Дети** | 1 | 3 | 10 | ∞ |
| **Trial** | 14 дней Premium | — | — | — |

### Цены Premium

| Период | USD | Telegram Stars |
|--------|-----|----------------|
| Месяц | $9 | 700 ⭐ |
| 3 месяца | $22 (экономия $5) | 1 700 ⭐ |
| Год | $72 (экономия $36) | 5 500 ⭐ |

### Логика определения плана (`get_effective_plan`)

```
Приоритет: admin → paid subscription (plan_expires_at) → trial → legacy
```

- **Admin** — по `ADMIN_TELEGRAM_IDS`
- **Premium/Ultra** — если `plan_expires_at` в будущем
- **Trial** — 14 дней после первой загрузки фото (активируется атомарно)
- **Legacy** — `basic/family` → маппится на `premium`

---

## Оплата

### Telegram Stars
- Встроенная оплата Telegram, `currency="XTR"`, без `provider_token`
- Флоу: `/subscribe` → кнопка `pay_stars:` → подтверждение → `confirm_stars:` → invoice
- `handle_pre_checkout` — обязательный ответ в течение 10 сек
- `handle_successful_payment` — активация Premium в БД

### Stripe
- Stripe Checkout Sessions (redirect to hosted page)
- Webhook: `POST /api/v1/webhooks/stripe` с HMAC верификацией
- `checkout.session.completed` → `_activate_premium_after_payment`

### Тестирование оплаты (admin)
```
/test_subscribe → "💳 Stars invoice (тест)"
```
- Payload `test:{plan_key}:{telegram_id}` — Premium **не активируется**
- Ответ: "✅ Тест Stars оплаты прошёл успешно! Premium не активирован"

---

## Vision API (добавление вещей)

- **Модель:** `claude-sonnet-4-6` (НЕ haiku — плохое качество распознавания)
- **max_tokens:** 4096 (иначе обрезает JSON)
- **Ориентация:** вертикальное фото лучше горизонтального
- **Дедупликация:** отключена в v1.1 (мешает больше чем помогает)
- **Prompt caching:** system промпт кэшируется через `cache_control: {type: "ephemeral"}`

---

## Morning Brief

Ежедневный образ дня, генерируется через Claude Sonnet:
1. Получает погоду (wttr.in, кэш Redis 1 час)
2. Выбирает вещи из гардероба по сезону/температуре/поводу
3. Формирует текст образа + коллаж фото
4. Отправляет в Telegram в 7:00 по timezone пользователя

**Расписание:**
- Free: вторник + четверг
- Premium/Ultra: каждый день

---

## AnthropicPool

Пул API ключей с отказоустойчивостью (`core/anthropic_client.py`):
- Ротация ключей round-robin
- Circuit breaker per key (fail fast при перегрузке)
- RPM лимитер через Redis (sliding window)
- Auto-failover при rate limit ошибках
- Логирует токены: input/output/cache_hit/cache_write

---

## База данных

### Ключевые модели

**User** — основная модель
```python
telegram_id, name, city, timezone
plan: "free" | "basic" | "family" | "premium" | "ultra"
segment: "mom_girl" | "mom_boy" | "pregnant" | "no_kids"
body_type, colortype
plan_expires_at       # дата истечения платной подписки
trial_started_at, trial_ends_at  # trial период
payment_provider: "stars" | "stripe" | "test"
stripe_customer_id, subscription_id
daily_requests_used, daily_requests_reset_at
onboarding_completed
```

**WardrobeItem** — вещь в гардеробе
```python
owner_id, owner_type: "user" | "child"  # владелец
category_group, category_code           # таксономия (12 групп)
type, color, style, brand
season[], occasion[]                    # массивы
photo_id, photo_hash                    # phash для дедупликации
score_item, score_breakdown (JSONB)     # скоринг v2.0
```

**ScoringMatrix** — матрицы скоринга по возрасту
```
Варианты: 0-3, 3-7, 7-12, 12-16, 16-25, 25-35, 35-45, 45+,
          pregnant-1, pregnant-2, pregnant-3
```

### Read/Write сессии
```python
from db.base import AsyncWriteSession, AsyncReadSession

async with AsyncWriteSession() as session:
    await session.execute(...)
    await session.commit()

async with AsyncReadSession() as session:
    result = await session.execute(select(User)...)
```

---

## Деплой

### Docker Compose

```
docker/docker-compose.yml:
  app        — FastAPI + Telegram bot (порт 8000)
  worker     — Background task consumer
  postgres   — PostgreSQL 16-alpine
  redis      — Redis 7-alpine
  cloudflared — Cloudflare Tunnel (постоянный URL)
```

### Команды

```bash
make dev       # docker-compose up --build -d
make migrate   # alembic upgrade head
make seed      # taxonomy + scoring + dev данные
make test      # pytest (smoke + unit)
make lint      # ruff + mypy
make deploy    # build → test → up → migrate
```

### Cloudflare Tunnel

Именованный tunnel с постоянным URL `bot.fashioncastle.app`:
```yaml
# ~/.cloudflared/config.yml
tunnel: fashion-bot
credentials-file: /etc/cloudflared/{TUNNEL_ID}.json
ingress:
  - hostname: bot.fashioncastle.app
    service: http://app:8000
  - service: http_status:404
```

**URL не меняется при рестарте** (в отличие от `trycloudflare.com`).

### Production VPS

- IP: `100.97.47.50` (Tailscale), Ubuntu 24.04 ARM64
- Webhook: `https://bot.fashioncastle.app/api/v1/webhooks/telegram`
- Логи: `docker compose logs -f app`

---

## Переменные окружения

```bash
# Обязательные
TELEGRAM_BOT_TOKEN=          # токен бота
TELEGRAM_WEBHOOK_URL=        # https://bot.fashioncastle.app
ANTHROPIC_API_KEYS=key1,key2 # через запятую (пул ключей)
DATABASE_WRITE_URL=postgresql+asyncpg://...
DATABASE_READ_URL=postgresql+asyncpg://...
REDIS_URL=redis://redis:6379/0

# Billing
PAYMENT_PROVIDER=stars       # stars | stripe
STRIPE_SECRET_KEY=           # если используется Stripe
STRIPE_WEBHOOK_SECRET=       # для верификации webhook

# App
ADMIN_TELEGRAM_IDS=195169    # ID администраторов (через запятую)
ENVIRONMENT=dev              # dev | prod
SENTRY_DSN=                  # опционально

# Storage (v1.4)
CLOUDFLARE_R2_BUCKET=
CLOUDFLARE_R2_ACCESS_KEY=
CLOUDFLARE_R2_SECRET_KEY=
```

Полный список — `.env.example`.

---

## Тесты

```bash
pytest tests/test_smoke.py             # быстрые smoke тесты (~30 шт)
pytest tests/test_unit.py              # unit тесты (~200 шт)
pytest tests/ --ignore=tests/test_stylist.py  # все кроме flaky
```

**Покрытие:**
- `test_smoke.py` — импорты, наличие функций, константы
- `test_unit.py` — логика планов, Stars оплата, trial активация, лимиты
- `test_billing.py` — Stripe webhook, Stars flow

---

## Roadmap

| Версия | Статус | Что |
|--------|--------|-----|
| **v1.1** | ✅ Текущая | Vision, Morning Brief, Stars + Stripe, /test_subscribe |
| **v1.2** | Планируется | Онбординг жены, редактирование вещей, матрицы скоринга |
| **v1.4** | Планируется | Cloudflare R2, Sentry, Paddle, полный referral |
| **v2.0** | Будущее | Публичный запуск, analytics dashboard, Ultra план |

---

## Известные ограничения (v1.1)

| Проблема | Обходной путь | Планируется |
|----------|--------------|-------------|
| `photo_url` пустой — фото только в Telegram | Используем `photo_id` | R2 в v1.4 |
| Нет возраста пользователя в онбординге | Предполагается 30 лет | v1.2 |
| Нет выбора триместра для беременных | Всегда `pregnant-2` | v1.2 |
| Дедупликация отключена | — | v1.2 |
| `test_stylist.py` — flaky тест | `--ignore` при запуске | — |
