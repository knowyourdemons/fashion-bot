# Fashion Bot — CLAUDE.md

## Контекст проекта
AI-стилист в Telegram. Анализирует одежду по фото, ведёт гардероб,
отправляет Morning Brief с образом дня. ЦА: мамы с детьми, беременные,
женщины без детей. Замена стилисту за $200-300.

## Стек и версии
```
python-telegram-bot==21.3
fastapi==0.115.5
sqlalchemy==2.0.36 (async + asyncpg)
pydantic==2.9.2
alembic==1.13.3
redis==5.2.0
apscheduler==3.10.4
anthropic==0.40.0
structlog==24.4.0
sentry-sdk[fastapi]==2.18.0
httpx==0.27.2
pillow==10.4.0
imagehash==4.3.1
pytest==8.3.3
pytest-asyncio==0.23.8
ruff==0.7.0
mypy==1.11.0
```

## Архитектура

```
Telegram Bot  ──┐
                ├──► services/ ──► PostgreSQL
REST API      ──┘               ──► Redis
                                ──► Anthropic API
Worker ─────────────────────────►  (async queue)
```

**Главный принцип:** bot/ и api/ — только routing.
Вся бизнес-логика в services/ и worker/tasks/.
Никогда не дублировать логику между bot и api.

## Структура проекта

```
fashion-bot/
  main.py                    # точка входа
  config.py                  # pydantic-settings из .env
  exceptions.py              # кастомные исключения
  Makefile                   # dev/migrate/seed/test/deploy

  api/
    __init__.py
    app.py                   # FastAPI app
    routes/
      auth.py                # POST /api/v1/auth/telegram
      wardrobe.py            # CRUD /api/v1/wardrobe
      brief.py               # GET/POST /api/v1/brief
      onboarding.py          # /api/v1/onboarding
      billing.py             # /api/v1/billing
      webhooks.py            # /api/v1/webhooks/stripe|telegram
    middleware/
      auth.py                # JWT проверка
      rate_limit.py          # Redis rate limiting
      request_id.py          # X-Request-ID header
    schemas/
      user.py
      wardrobe.py
      brief.py

  bot/
    app.py                   # Telegram application
    handlers/
      start.py               # /start онбординг
      wardrobe.py            # фото + команды гардероба
      feedback.py            # 👍/👎
      billing.py             # /subscribe /plan /cancel
      help.py                # /help
      text.py                # произвольный текст → стилист
    middleware/
      auth.py                # проверка user в БД
      typing.py              # send_chat_action TYPING

  worker/
    consumer.py              # Redis queue consumer
    fast_worker.py           # high priority (brief, анализ фото)
    slow_worker.py           # normal/low (аналитика, отчёты)
    tasks/
      morning_brief.py
      wardrobe_analysis.py
      gap_analysis.py        # Batch API
      growth_alert.py
      declutter.py           # Batch API
      capsule_season.py      # Batch API
      birthday_alert.py
      subscription_expiry.py
      reminders.py           # 3/7/30 дней молчания
      analytics_report.py
      unknown_items_report.py
      taxonomy_review.py

  core/
    anthropic_client.py      # пул ключей + failover + circuit breaker
    rate_limiter.py          # token bucket в Redis
    queue.py                 # Redis queue wrapper
    scheduler.py             # APScheduler + Redis
    permissions.py           # планы и лимиты
    circuit_breaker.py       # circuit breaker паттерн

  db/
    base.py                  # engine + session factory
    models/
      user.py
      child.py
      wardrobe.py
      brief_log.py
      outfit_log.py
      events.py
      scoring_matrix.py
      taxonomy.py
      referrals.py
      admin_actions.py
    crud/
      users.py
      wardrobe.py
      scoring.py
      taxonomy.py
    migrations/              # alembic versions
    seeds/
      taxonomy_seed.py       # полный справочник категорий
      scoring_matrix_seed.py # матрицы по возрасту
      dev_seed.py            # тестовые данные

  services/
    weather.py               # wttr.in + Redis кэш
    scoring.py               # скоринг вещи и образа
    image_processor.py       # resize + EXIF очистка + phash
    image_builder.py         # коллаж (заглушка → Фаза 2)
    share.py                 # "спросить подругу" ссылки
    notifications.py         # все уведомления через queue
    storage/
      base.py
      telegram_storage.py
      r2_storage.py          # заглушка
    i18n/
      __init__.py
      ru.py
      en.py                  # заглушка

  billing/
    base.py                  # абстрактный PaymentProvider
    stars.py                 # Telegram Stars
    stripe_provider.py       # Stripe
    paddle_provider.py       # заглушка
    subscription.py          # create/cancel/pause/resume

  docker/
    Dockerfile
    docker-compose.yml
    docker-compose.prod.yml
    nginx.conf
    postgres.conf            # VACUUM, timeouts, slow query log

  tests/
    conftest.py              # fixtures: db, user, child, redis
    test_scoring.py
    test_wardrobe.py
    test_taxonomy.py
    test_weather.py
    test_permissions.py
    test_billing.py

  requirements.txt
  .env.example
  .dockerignore
  .pre-commit-config.yaml
  alembic.ini
  mypy.ini
  README.md
```

## Модели БД (ключевые поля)

### User
```python
id: UUID PK
telegram_id: BigInteger unique indexed
name: String
city: String
timezone: String default="Europe/Vilnius"
plan: Enum("free","basic","family","premium")
segment: Enum("mom_girl","mom_boy","pregnant","no_kids")
body_type: Enum(...) nullable
is_active: Boolean default=True
# Stripe
stripe_customer_id: String nullable
subscription_id: String nullable
plan_expires_at: DateTime nullable
trial_ends_at: DateTime nullable
plan_paused_until: DateTime nullable
payment_provider: Enum("stars","stripe","paddle") nullable
# Referrals
referral_code: String unique
referred_by: UUID nullable FK→User
# Limits
daily_requests_used: Integer default=0
daily_requests_reset_at: DateTime nullable
# Onboarding
onboarding_step: String nullable
onboarding_completed: Boolean default=False
# Soft delete
deleted_at: DateTime nullable
created_at: DateTime
updated_at: DateTime
```

### Child
```python
id: UUID PK
user_id: UUID FK→User
name: String
birthdate: Date
gender: Enum("boy","girl")
colortype: String nullable
shoe_size: Integer nullable
current_size: String nullable
deleted_at: DateTime nullable
created_at: DateTime
```

### WardrobeItem
```python
id: UUID PK
owner_id: UUID
owner_type: Enum("user","child")
# Категория
category_group: Enum("outerwear","top","bottom","one_piece",
  "footwear","accessory","base_layer","sportswear",
  "special","home_beach","pregnant_specific")
category_code: String          # "footwear.shoes.loafers"
is_unknown_category: Boolean default=False
user_label: String nullable    # как назвал пользователь
# Описание
type: String
color: String
style: String
brand: String nullable
season: ARRAY(String)
occasion: ARRAY(String)
# Медиа
photo_id: String               # Telegram file_id
photo_url: String nullable     # R2 URL (Фаза 2)
photo_hash: String nullable    # perceptual hash для дублей
# Размеры
size_fit: Enum("маловата","впору","великовата") nullable
size_actual: String nullable
size_recommended: String nullable
# Состояние
condition: Enum("новая","хорошая","ношеная","на_выброс")
price: Numeric nullable
wear_count: Integer default=0
last_worn: Date nullable
# Скоринг
score_item: Numeric nullable
score_breakdown: JSONB nullable  # GIN индекс
score_version: String default="v1.0"
score_notes: String nullable
# Флаги
is_base_layer: Boolean default=False
show_in_collage: Boolean default=True
quantity: Integer default=1
keep: Boolean default=True
wishlist: Boolean default=False
# Оптимистичная блокировка
version: Integer default=0
# Soft delete
deleted_at: DateTime nullable
added_at: DateTime
```

### ScoringMatrix
```python
id: UUID PK
name: String                   # "0-3_girl", "adult_woman"
age_from: Integer
age_to: Integer
gender: Enum("boy","girl","all")
is_pregnant: Boolean default=False
criteria: JSONB                # {"safety": 2, ...}
max_score: Integer
version: String default="v1.0"
is_active: Boolean default=True
created_at: DateTime
updated_at: DateTime
```

### Остальные модели
OutfitLog, BriefLog, Event, ItemCategory,
TaxonomyVersion, UnknownItem, Referral,
AdminAction — стандартная структура с UUID PK,
soft delete где нужно, created_at везде.

## Индексы

```sql
-- Partial индексы (только активные записи)
CREATE INDEX ON users(telegram_id) WHERE deleted_at IS NULL;
CREATE INDEX ON wardrobe_items(owner_id, owner_type)
  WHERE deleted_at IS NULL;
CREATE INDEX ON wardrobe_items(last_worn)
  WHERE deleted_at IS NULL;
CREATE INDEX ON brief_log(user_id, date);
CREATE INDEX ON events(user_id, created_at);

-- GIN для JSONB
CREATE INDEX ON wardrobe_items USING GIN(score_breakdown);
CREATE INDEX ON outfit_log USING GIN(items);
```

## Правила кода

```python
# 1. Все исключения через exceptions.py
class FashionBotError(Exception): pass
class RateLimitError(FashionBotError): pass
class PaymentError(FashionBotError): pass
class PermissionDeniedError(FashionBotError): pass

# В handlers:
try:
    result = await service.do_something()
except FashionBotError as e:
    await message.reply(str(e))    # показать юзеру
    logger.warning("handled", error=str(e), user_id=user_id)
except Exception as e:
    await message.reply(i18n.t("error.generic"))
    logger.error("unhandled", error=str(e))
    sentry_sdk.capture_exception(e)

# 2. Structlog обязательные поля
logger.info("wardrobe.item.added",
    user_id=str(user.id),
    action="wardrobe.item.added",
    category=item.category_code,
    duration_ms=duration)

# Dev: ConsoleRenderer
# Prod: JSONRenderer
# НИКОГДА не логировать: имена детей, фото, платёжные данные

# 3. DB сессии через DI
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

# 4. Всегда selectinload против N+1
result = await session.execute(
    select(User)
    .options(selectinload(User.children)
             .selectinload(Child.wardrobe_items))
    .where(User.id == user_id)
)

# 5. Optimistic locking для wear_count
await session.execute(
    update(WardrobeItem)
    .where(WardrobeItem.id == item_id,
           WardrobeItem.version == current_version)
    .values(wear_count=new_count,
            version=current_version + 1)
)
```

## Redis — key naming convention

```
weather:cache:{city}              TTL 3600
rate:user:{id}:daily              TTL 86400
rate:api:{key}:minute             TTL 60
lock:cron:{task}:{user_id}        TTL 300
lock:brief:{user_id}:{date}       TTL 86400
queue:high                        no TTL
queue:normal                      no TTL
queue:low                         no TTL
queue:dead                        no TTL
worker:heartbeat:{worker_id}      TTL 120
session:user:{telegram_id}        TTL 3600
task:result:{task_id}             TTL 3600
matrix:cache:{name}               TTL 3600
circuit:{service}:state           TTL 60
share:outfit:{token}              TTL 86400
```

## Anthropic API

```python
# Prompt caching для системных промптов
messages = [{
    "role": "user",
    "content": [{
        "type": "text",
        "text": system_prompt,
        "cache_control": {"type": "ephemeral"}  # кэш 5 мин
    }, {
        "type": "text",
        "text": user_message
    }]
}]

# Image preprocessing перед Vision API
def preprocess_for_vision(image_bytes: bytes) -> bytes:
    img = Image.open(io.BytesIO(image_bytes))
    img.thumbnail((1024, 1024))        # resize
    img = remove_exif(img)             # GDPR
    return img.tobytes()

# Предфильтр одежды (~100 токенов)
async def has_clothing(photo_bytes) -> bool:
    response = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=10,
        messages=[{"role": "user", "content": [
            {"type": "image", ...},
            {"type": "text", "text": "Есть одежда на фото? да/нет"}
        ]}]
    )
    return "да" in response.content[0].text.lower()

# Circuit breaker
# После 5 ошибок → открыть на 60 сек
# Degraded mode: вернуть cached ответ или текстовый Brief

# Batch API для несрочных задач
# gap_analysis, declutter, capsule_season
# → 5x дешевле, результат через 24 часа

# Model fallback
PRIMARY_MODEL = "claude-haiku-4-5-20251001"
FALLBACK_MODEL = "claude-sonnet-4-6"
```

## Планы и лимиты

```python
# core/permissions.py

PLANS = {
    "free": {
        "daily_requests": 3,
        "max_wardrobe_items": 20,
        "max_children": 0,
        "morning_brief": False,
        "gap_analysis": False,
        "wow_builder": False,
    },
    "basic": {           # $5/мес или $48/год
        "daily_requests": 50,
        "max_wardrobe_items": 50,
        "max_children": 1,
        "morning_brief": True,
        "gap_analysis": False,
        "wow_builder": False,
    },
    "family": {          # $12/мес или $115/год
        "daily_requests": 100,
        "max_wardrobe_items": 200,
        "max_children": 2,
        "morning_brief": True,
        "gap_analysis": True,
        "wow_builder": False,
    },
    "premium": {         # $19/мес или $182/год
        "daily_requests": -1,   # unlimited
        "max_wardrobe_items": -1,
        "max_children": -1,
        "morning_brief": True,
        "gap_analysis": True,
        "wow_builder": True,
    }
}

# Конверсионные триггеры
UPGRADE_TRIGGERS = {
    "items_limit_90pct": "У тебя {used}/{max} вещей. "
        "Перейди на {next_plan} и добавь ещё",
    "brief_blocked": "Сегодня {weather}. "
        "Хочешь образ для Алисы? Morning Brief в Basic $5",
    "daily_limit": "Использовано {used}/{max} запросов. "
        "Basic $5 — 50 запросов в день",
}
```

## Матрицы скоринга вещи

Хранятся в БД (ScoringMatrix), кэш Redis 1 час.
Seed в db/seeds/scoring_matrix_seed.py.

```
0-3 года (max=15): safety:2, practicality:2, durability:2,
  age_authenticity:2, ease_of_care:1, colortype:1,
  comfort:1, versatility:1, condition:1,
  size_fit_score:1, seasonality:1

3-7 лет (max=14): practicality:2, colortype:2, versatility:2,
  age_authenticity:2, ease_of_care:1, comfort:1,
  condition:1, size_fit_score:1, seasonality:1,
  child_preference:1

7-12 лет (max=13): style:2, child_preference:2, colortype:2,
  versatility:2, trend:1, condition:1, ease_of_care:1,
  seasonality:1, size_fit_score:1

12-16 лет (max=13): trend:2, child_preference:2, style:2,
  colortype:2, individuality:2, condition:1,
  seasonality:1, versatility:1

16+ взрослый (max=12): colortype:2, trend:2, dress_code:2,
  versatility:2, condition:1, seasonality:1,
  style_unity:1, brand_quality:1

Беременная (max=12): comfort:3, practicality:2,
  post_pregnancy_use:2, safety:1, colortype:1,
  versatility:1, condition:1, seasonality:1
```

## Матрица скоринга образа

```
Взрослые (max=23 → нормируем в 10):
  Технический (max=8):
    color_harmony:2, style_unity:2,
    colortype_outfit:2, seasonality:1, occasion_fit:1
  Эстетический (max=11):
    unexpected_combination:2, focal_point:2,
    proportions:2, modernity:2, transformation:3
  Персональный (max=4):
    variety:1, sleeping_items:2, capsule_efficiency:1
  Accessory bonus: -1..+2

WOW: transformation>=3 AND unexpected_combination>=2
  → "✨ Такой образ обычно предлагают стилисты за $200+"

Дети (max=10):
  color_harmony:2, practicality_outfit:2,
  age_appropriateness:2, weather_fit:2,
  style_unity:1, variety:1
```

## Онбординг флоу (конфиг)

```python
ONBOARDING_FLOWS = {
    "mom_girl": [
        {"step": "child_name", "q": "Как зовут дочку?"},
        {"step": "child_birthdate", "q": "Дата рождения?"},
        {"step": "child_size", "q": "Размер одежды?"},
        {"step": "child_shoe_size", "q": "Размер обуви?"},
        {"step": "city", "q": "Ваш город?"},
        {"step": "tutorial", "q": None},  # показать tutorial
    ],
    "mom_boy": [...],      # аналогично
    "pregnant": [
        {"step": "trimester", "q": "Какой триместр?"},
        {"step": "city", "q": "Ваш город?"},
        {"step": "body_type", "q": "Тип фигуры?", "optional": True},
    ],
    "no_kids": [
        {"step": "colortype_photo", "q": "Пришли селфи", "optional": True},
        {"step": "body_type", "q": "Тип фигуры?", "optional": True},
        {"step": "city", "q": "Ваш город?"},
    ]
}
# Сохранять onboarding_step при каждом ответе
# Возобновлять с того же шага при /start
```

## Погодные алерты (services/weather.py)

```python
# Redis кэш TTL=3600 по городу
# wttr.in/Vilnius?format=j1
# Парсить: temp_C, feels_likeC, weatherDesc,
#          windspeedKmph, uvIndex, evening_temp

TEMP_RULES = {
    (20, 99):   "лёгкая одежда без куртки",
    (15, 20):   "тепло — лёгкая кофта",
    (10, 15):   "прохладно — лёгкая куртка",
    (5, 10):    "холодно — тёплая куртка",
    (0, 5):     "около нуля — утеплиться",
    (-5, 0):    "мороз — тёплая одежда",
    (-99, -5):  "сильный мороз — максимальное утепление",
}

DELTA_RULES = {
    8: "⚠️ Резкое похолодание вечером на {n}°C",
    5: "⚠️ Вечером холоднее на {n}°C",
}

PRECIP_RULES = {
    "rain_morning":  "🌧 Дождь — непромокаемая куртка",
    "rain_evening":  "🌧 Вечером дождь — возьми дождевик",
    "snow":          "❄️ Снег — зимняя одежда",
    "sleet":         "🌨 Мокрый снег — водоотталкивающая куртка",
}

WIND_RULES = {
    15: "💨 Сильный ветер — закрытая одежда",
    10: "💨 Ветрено — куртка с капюшоном",
}

SPECIAL_RULES = {
    "fog":      "🌫 Туман — яркая одежда (заметность)",
    "thunder":  "⛈ Гроза — лучше остаться дома",
    "hot":      "☀️ Жара — панамка + солнцезащитный крем",
    "uv_high":  "🌞 Высокий УФ — панамка обязательна",
    "transitional": "Переменная погода — одеть слоями",  # март/апрель/окт
}
```

## Cron задачи

| Задача | Время | Тип |
|--------|-------|-----|
| morning_brief | 07:00 timezone юзера | fast, ежедневно |
| growth_alert | вс 11:00 UTC | normal, еженедельно |
| declutter | 1-е 10:00 UTC | **Batch API**, ежемесячно |
| gap_analysis | 15-е 10:00 UTC | **Batch API**, ежемесячно |
| capsule_season | 1 мар/июн/сен/дек | **Batch API** |
| birthday_alert | день рождения 08:00 UTC | normal |
| subscription_expiry | ежедневно 09:00 UTC | normal |
| reminders | ежедневно 10:00 UTC | low |
| db_backup | ежедневно 03:00 UTC | system |
| analytics_report | ежедневно 08:00 UTC | low |
| unknown_items_report | 1-е 09:00 UTC | low |
| taxonomy_review | 1 мар/июн/сен/дек 09:00 | low |

Missed jobs при рестарте: проверять за последние 2 часа.

## Docker

```yaml
# Каждый сервис обязан иметь:
healthcheck:
  test: [...]
  interval: 30s
  timeout: 10s
  retries: 3

# Resource limits:
deploy:
  resources:
    limits:
      memory: 512m  # app
      memory: 256m  # worker
      memory: 256m  # redis

# Log rotation:
logging:
  driver: json-file
  options:
    max-size: "100m"
    max-file: "3"

# Timezone:
environment:
  - TZ=UTC
```

## nginx.conf ключевые настройки

```nginx
# IP rate limiting
limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
limit_req zone=api burst=20 nodelay;

# Gzip
gzip on;
gzip_types application/json;

# CSP для Mini App
add_header Content-Security-Policy
  "default-src 'self' *.telegram.org";

# Webhook endpoint без rate limit
location /api/v1/webhooks/ {
    limit_req off;
}
```

## postgres.conf

```
statement_timeout = 30000           # 30 сек
idle_in_transaction_session_timeout = 30000
log_min_duration_statement = 1000   # slow query > 1 сек
autovacuum = on
```

## Деплой — zero-downtime миграции

```
Правило: никогда не удалять колонку в том же деплое где добавляешь новую.

Деплой 1: добавить new_column nullable
Деплой 2: заполнить данные
Деплой 3: сделать not nullable / удалить old_column

Каждая миграция ОБЯЗАНА иметь downgrade().
```

## Безопасность

```python
# EXIF очистка (GDPR)
def remove_exif(img: Image) -> Image:
    data = list(img.getdata())
    clean = Image.new(img.mode, img.size)
    clean.putdata(data)
    return clean

# Perceptual hash для дублей
import imagehash
hash1 = imagehash.phash(Image.open(photo1))
hash2 = imagehash.phash(Image.open(photo2))
if hash1 - hash2 < 10:  # порог схожести
    raise DuplicateItemError

# Presigned URLs для R2 (Фаза 2)
# TTL = 3600 сек, не постоянные публичные ссылки

# PII никогда в логах:
# ❌ logger.info("child", name=child.name)
# ✅ logger.info("child", child_id=str(child.id))

# Audit log для admin действий
# Отдельная таблица admin_actions
```

## Медиа обработка

```python
# До отправки в Vision API:
# 1. Проверить размер (max 20MB)
# 2. resize до 1024×1024 (Pillow)
# 3. Очистить EXIF
# 4. Perceptual hash для дублей

# Коллаж (Фаза 1 — заглушка, Фаза 2 — реализация):
# - скачать фото по photo_id из Telegram
# - grid 2×2 или 2×3
# - base_layer исключить
# - accessory включить
# - подписи под каждой вещью
```

## "Спросить подругу"

```python
# Генерировать share token (UUID)
# Хранить в Redis TTL=86400: share:outfit:{token}
# URL: https://fashionbot.app/ask/{token}
# Страница: фото + кнопки 👍/👎
# Результат → уведомление владельцу
# Подруга не регистрируется
```

## Напоминания (worker/tasks/reminders.py)

```python
REMINDER_RULES = [
    (3,  "Привет! Не забывай про Morning Brief 👗"),
    (7,  "Твой гардероб скучает — загляни?"),
    (30, "Давно не виделись! Есть новые вещи?"),
]
# Проверять ежедневно last_active пользователя
# Не слать если уже слали за последние 3 дня
```

## Переменные окружения (.env.example)

```env
# БД
DATABASE_WRITE_URL=postgresql+asyncpg://user:pass@postgres:5432/fashion
DATABASE_READ_URL=postgresql+asyncpg://user:pass@postgres:5432/fashion
DATABASE_POOL_SIZE=20
DATABASE_MAX_OVERFLOW=10

# Redis
REDIS_URL=redis://redis:6379/0

# Telegram
TELEGRAM_BOT_TOKEN=
TELEGRAM_WEBHOOK_URL=https://yourdomain.com/webhook
TELEGRAM_WEBHOOK_SECRET=
TELEGRAM_PAYMENT_TOKEN=

# Anthropic (через запятую для пула)
ANTHROPIC_API_KEYS=key1,key2

# Billing
PAYMENT_PROVIDER=stars
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=

# App
ENVIRONMENT=dev
SENTRY_DSN=
ADMIN_TELEGRAM_IDS=195169
FREE_TRIAL_DAYS=7
DAILY_LIMITS_FREE=3
DAILY_LIMITS_BASIC=50
DAILY_LIMITS_FAMILY=100

# Storage (Фаза 2)
CLOUDFLARE_R2_BUCKET=
CLOUDFLARE_R2_ACCESS_KEY=
CLOUDFLARE_R2_SECRET_KEY=

# Annual pricing
BASIC_MONTHLY_PRICE=5
BASIC_ANNUAL_PRICE=48
FAMILY_MONTHLY_PRICE=12
FAMILY_ANNUAL_PRICE=115
PREMIUM_MONTHLY_PRICE=19
PREMIUM_ANNUAL_PRICE=182
```

## Makefile

```makefile
dev:
	docker-compose up --build

migrate:
	docker-compose exec app alembic upgrade head

seed:
	docker-compose exec app python -m db.seeds.taxonomy_seed
	docker-compose exec app python -m db.seeds.scoring_matrix_seed
	docker-compose exec app python -m db.seeds.dev_seed  # только dev

test:
	pytest tests/ -v --asyncio-mode=auto

lint:
	ruff check .
	mypy .

deploy:
	docker-compose -f docker/docker-compose.prod.yml up -d --build
	docker-compose exec app alembic upgrade head
```

## Порядок разработки

```
1. docker/ (Dockerfile, compose, nginx, postgres.conf)
2. config.py + exceptions.py
3. db/base.py + все модели
4. alembic.ini + первая миграция (все таблицы)
5. db/seeds/ (taxonomy, scoring_matrix, dev)
6. core/anthropic_client.py (пул + failover + circuit breaker)
7. core/rate_limiter.py (token bucket в Redis)
8. core/queue.py (Redis queue)
9. core/permissions.py
10. services/weather.py
11. services/scoring.py
12. services/image_processor.py
13. services/image_builder.py (заглушка)
14. services/share.py
15. services/notifications.py
16. billing/ (stars + stripe + subscription)
17. worker/tasks/morning_brief.py
18. worker/consumer.py + fast/slow workers
19. bot/handlers/start.py (онбординг)
20. bot/handlers/wardrobe.py
21. bot/handlers/feedback.py
22. bot/handlers/text.py (стилист-консультант)
23. bot/handlers/billing.py
24. bot/handlers/help.py
25. api/routes/ (все endpoints)
26. main.py
27. tests/
28. .pre-commit-config.yaml
29. README.md
```

## Dev seed (db/seeds/dev_seed.py)

```python
# Создаёт при ENVIRONMENT=dev:
# User: telegram_id=195169, name="Стас", city="Вильнюс",
#       plan=premium, onboarding_completed=True
# Child: name="Алиса Мария", birthdate=2022-12-19, gender=girl,
#        colortype="Лето", shoe_size=27, current_size="92"
# WardrobeItems: 8 вещей из текущего wardrobe.json
```
