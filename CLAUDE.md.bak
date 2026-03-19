# Fashion Bot — CLAUDE.md

## Инфраструктура
- VPS: agent-farm-01, user=stas, ~/fashion-bot
- Containers: docker-app-1 (FastAPI+PTB), docker-worker-1, docker-postgres-1, docker-redis-1
- GitHub: knowyourdemons/fashion-bot
- Tunnel: bot.fashioncastle.app (именованный Cloudflare tunnel ✅)
- Webhook: https://bot.fashioncastle.app/api/v1/webhooks/telegram
- Тест-пользователи: Стас telegram_id=195169 (plan=admin), Алиса owner_id=acf0100d-ca11-4fce-815e-c516af11e710 (3г, девочка, Лето)

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
- remove.bg size=small ($0.002/фото)
- Prompt caching: ephemeral везде

## Структура проекта
```
bot/handlers/
  wardrobe.py      — Vision, коллаж, owner switching, оценка образа
  onboarding.py    — ConversationHandler онбординга
  subscription.py  — /subscribe, /test_subscribe, Stars/Stripe
  text.py          — Haiku чат стилиста (_get_text_system по сегменту)
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
  image_builder.py — коллаж, силуэты детские+взрослые
  scoring.py, weather.py, image_processor.py, usage.py, i18n/
permissions.py     — лимиты, планы, trial логика (ЦЕНТРАЛЬНЫЙ ФАЙЛ)
billing/           — stripe_provider.py, yukassa_provider.py (stub), paddle_provider.py (stub)
```

## Ключевые соглашения
- **DB сессии**: `AsyncWriteSession` для записи, `AsyncReadSession` для чтения
- **Логирование**: `structlog` (`logger = structlog.get_logger()`)
- **Конфигурация**: через `config.py` (pydantic `BaseSettings`, case-insensitive)
- **Строки UI**: `services/i18n/ru.py` через `t("key")`
- **Redis в боте**: `context.bot_data["redis"]`
- **Владелец вещей**: `child.id` если `segment=mom_girl/mom_boy`, иначе `user.id`
- **Активный owner**: `_get_owner(user, context)` → `(owner_id, owner_type)`
- **Ошибки Sentry**: `sentry_sdk.capture_exception(e)` в обработчиках

## Модели БД
```python
User:
  telegram_id (unique), name, city, timezone
  plan: "free" | "premium" | "ultra" | "admin"
  segment: "mom_girl" | "mom_boy" | "pregnant" | "no_kids"
  colortype, body_type
  plan_expires_at        # дата истечения ПЛАТНОЙ подписки
  trial_started_at, trial_ends_at  # trial (14 дней, с первого фото)
  payment_provider: "stars" | "stripe" | "test"
  onboarding_completed, onboarding_step

Child: user_id, name, birthdate, gender, colortype, current_size, shoe_size

WardrobeItem:
  owner_id (UUID), owner_type: "user" | "child"
  category_group, type, color, season
  photo_id, photo_url (пустой — R2 в v1.4), photo_hash
  score_item, score_breakdown (JSONB), score_version="v2.0"
  show_in_collage (alpha ratio ≥15%)

ScoringMatrix: name, criteria (JSONB), max_score, is_active
BriefLog: user_id, date, outfit_items[], feedback, is_wow
```

## Система планов и лимитов (`permissions.py`)

### `get_effective_plan(user) -> str`
Приоритет: **admin > paid subscription > trial > free**
```python
admin         # telegram_id=195169
premium/ultra # plan_expires_at > now (иначе → "free")
premium       # trial_ends_at > now (trial активен)
```

### LIMITS
```
free:    photos=3, wardrobe=15, rate=3,  chat=3,  outfit=1,  brief=[вт,чт], children=1
premium: photos=30, wardrobe=500, rate=20, chat=20, outfit=5,  brief=ежедн., children=3
ultra:   photos=100, wardrobe=2000, rate=50, chat=50, outfit=10, brief=ежедн., children=10
admin:   все=9999
```

### PRICES
```
premium_monthly:   usd=9,  stars=700
premium_quarterly: usd=22, stars=1700
premium_yearly:    usd=72, stars=5500
```

### Функции
- `get_effective_plan(user)` → str
- `get_limit(key, plan)` → int
- `is_brief_day(plan, timezone)` → bool
- `is_brief_day_tomorrow(plan, timezone)` → bool
- `get_trial_days_left(user)` → int | None
- `is_trial_active(user)` → bool
- `days_until_expiry(user)` → int | None

## Платёжный флоу

### Telegram Stars
```
/subscribe → pay_stars:{plan_key}
→ handle_pay_stars: подтверждение
→ confirm_stars:{plan_key}
→ send_invoice(currency="XTR", provider_token="")
→ PreCheckoutQuery → ответить за 10 сек!
→ SUCCESSFUL_PAYMENT → _activate_premium_after_payment()
```
Payload: `"premium:{plan_key}:{telegram_id}"` (реальный) | `"test:..."` (тест, не активирует)

### Stripe
```
pay_stripe:{plan_key} → create_checkout_session → URL
→ Stripe webhook POST /api/v1/webhooks/stripe
→ HMAC верификация → checkout.session.completed
→ _activate_premium_after_payment()
```

### Защиты
- Double payment guard: если `expire_days > 3` → не показывать форму
- Admin bypass: admin видит `/test_subscribe` вместо формы оплаты
- Test payload: `test:` → Premium НЕ активируется

## Vision API
- **Модель**: `claude-sonnet-4-6` (НЕ haiku!)
- **max_tokens**: 4096
- Фото вертикально — лучше качество
- Дедупликация: ОТКЛЮЧЕНА
- Bbox: w>0.8 или h>0.8 → центральный crop
- Trial активация: атомарно `UPDATE WHERE trial_started_at IS NULL`
- Prompt caching: `cache_control: {type: "ephemeral"}`

## Коллаж (`services/image_builder.py`)
- `build_collage(outfit_slots)` — реальные вещи + плейсхолдеры
- Детские силуэты: по возрасту и полу ребёнка
- Взрослые силуэты: `adult=True` в outfit_slots (грубые, TODO редизайн SVG)
- show_in_collage=True если alpha ratio ≥15%

## Бриф (`worker/tasks/morning_brief.py`)
- Детский (mom_girl/mom_boy): коллаж + Haiku текст стилиста
- Взрослый (no_kids/pregnant): погода + Haiku совет по цветотипу
- Free: бриф вт/чт | Premium: каждый день включая выходные
- Цветотипы: Весна/Лето/Осень/Зима → палитры в `style_config.py`
- Вечерний push: `evening_push.py` в 20:00 если `is_brief_day_tomorrow`

## AnthropicPool (`core/anthropic_client.py`)
- Ротация ключей round-robin по `ANTHROPIC_API_KEYS`
- Circuit breaker per key: CLOSED → OPEN → HALF_OPEN
- RPM лимитер: sliding window в Redis
- Логирует: input_tokens, output_tokens, cache_hit_tokens

## Admin: `/test_subscribe`
Только для `ADMIN_TELEGRAM_IDS`. Панель тестирования:

| Кнопка | Действие |
|--------|----------|
| 🎁 Trial 14д | trial на 14 дней |
| 💎 Premium 30д | premium на 30 дней |
| 🔄 Сбросить в free | очистить всё |
| 📊 Лимиты | сравнение FREE/PREMIUM/ULTRA |
| 🔔 Запустить expiry | тест уведомления об окончании |
| 🌅 Evening push | тестовый push |
| 💳 Stars invoice (тест) | invoice с `test:` payload |
| 🔄 Обновить | перечитать из БД |

Статус: 🔴 free · 🟡 trial · 🟢 premium · 👑 admin

## Деплой
```bash
# Рестарт только app
docker restart docker-app-1

# Рестарт только worker
docker restart docker-worker-1

# Worker sync (ОБЯЗАТЕЛЬНО для morning_brief, style_config, permissions):
docker cp docker-app-1:/app/FILE /tmp/F
docker cp /tmp/F docker-worker-1:/app/FILE
docker restart docker-worker-1

# Sync на хост
docker cp docker-app-1:/app/FILE ~/fashion-bot/FILE

# Миграции
docker exec docker-app-1 alembic upgrade head

# Полный rebuild
docker compose -f ~/fashion-bot/docker/docker-compose.yml up --build -d

# ВАЖНО: после --build все docker cp теряются!
```

## Тестирование
```bash
docker exec docker-app-1 python3 -m pytest /app/tests/ -v --tb=short
# 60+ тестов: test_smoke.py, test_unit.py, test_integration.py
```

## Переменные окружения
```bash
TELEGRAM_BOT_TOKEN
TELEGRAM_WEBHOOK_URL        # https://bot.fashioncastle.app
ANTHROPIC_API_KEYS          # key1,key2 (пул)
DATABASE_WRITE_URL          # postgresql+asyncpg://...?ssl=disable
DATABASE_READ_URL
REDIS_URL                   # redis://redis:6379/0
ADMIN_TELEGRAM_IDS          # 195169
STRIPE_SECRET_KEY           # sk_live_... или sk_test_...
STRIPE_WEBHOOK_SECRET       # whsec_...
ENVIRONMENT                 # dev | prod
```

## Известные баги / TODO
- Силуэты (детские+взрослые) нарисованы грубо → редизайн SVG/иконки
- /profile + /add_child — не реализовано
- Онбординг: сегменты обидные → переделать UX (в работе)
- Онбординг: размер обуви принимает только int → нужен float (26.5)
- Онбординг: лимиты применяются во время онбординга → фикс нужен
- Онбординг: нет вопроса "а для себя тоже?" после выбора дочки/сына
- ЮKassa требует ИП/ООО → после открытия в РБ
- Stripe price_id не заполнены в permissions.PRICES
- photo_url пустой — фото только в Telegram (R2 в v1.4)

## Роадмап
- **Срочно**: онбординг UX (сегменты, размер обуви, лимиты, /start admin)
- **v1.1**: силуэты редизайн SVG, /profile, /add_child, онбординг resumable
- **v1.2**: шоппинг-лист, growth_alert, capsule_season, wardrobe_analysis
- **v1.4**: Cloudflare R2, Sentry, Paddle, referral program
- **v2.0**: публичный запуск, Ultra план, ЮKassa после ИП, семейный аккаунт
