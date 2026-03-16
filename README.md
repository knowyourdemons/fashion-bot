# Fashion Bot

AI-стилист в Telegram. Анализирует одежду по фото, ведёт гардероб,
отправляет Morning Brief с образом дня.

## Быстрый старт

```bash
cp .env.example .env
# Заполни .env (BOT_TOKEN, ANTHROPIC_API_KEYS и т.д.)
make dev
make migrate
make seed
```

## Архитектура

```
Telegram Bot  ──┐
                ├──► services/ ──► PostgreSQL
REST API      ──┘               ──► Redis
                                ──► Anthropic API
Worker ─────────────────────────►  (async queue)
```

**Главный принцип:** `bot/` и `api/` — только routing.
Вся бизнес-логика в `services/` и `worker/tasks/`.

## Структура

| Модуль | Назначение |
|--------|-----------|
| `main.py` | Точка входа: FastAPI + Telegram webhook + APScheduler |
| `config.py` | pydantic-settings из .env |
| `exceptions.py` | Кастомные исключения (FashionBotError и наследники) |
| `api/` | FastAPI routes + middleware + schemas |
| `bot/` | Telegram handlers + middleware |
| `worker/` | Redis queue consumer + fast/slow workers + cron tasks |
| `core/` | AnthropicPool, RateLimiter, RedisQueue, Scheduler, Permissions, CircuitBreaker |
| `db/` | SQLAlchemy models, CRUD, Alembic migrations, seeds |
| `services/` | Weather, Scoring, ImageProcessor, Share, Notifications, Storage, i18n |
| `billing/` | Stars, Stripe, Paddle (stub), Subscription |
| `docker/` | Dockerfile, docker-compose, nginx, postgres.conf |
| `tests/` | pytest + pytest-asyncio |

## Планы

| План | Цена | Запросов/день | Вещей | Детей |
|------|------|--------------|-------|-------|
| Free | $0 | 3 | 20 | 0 |
| Basic | $5/мес | 50 | 50 | 1 |
| Family | $12/мес | 100 | 200 | 2 |
| Premium | $19/мес | ∞ | ∞ | ∞ |

## Команды

```bash
make dev       # запуск в docker
make migrate   # alembic upgrade head
make seed      # загрузка taxonomy + scoring_matrix + dev данных
make test      # pytest
make lint      # ruff + mypy
make deploy    # prod деплой
```

## Переменные окружения

Смотри `.env.example`. Обязательные:
- `DATABASE_WRITE_URL`
- `REDIS_URL`
- `TELEGRAM_BOT_TOKEN`
- `ANTHROPIC_API_KEYS` (через запятую для пула)

## Порядок разработки

Следуй нумерации в `CLAUDE.md` → секция "Порядок разработки".
