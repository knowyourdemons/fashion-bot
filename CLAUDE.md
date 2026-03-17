# Fashion Bot — CLAUDE.md

## Архитектура
- FastAPI app (порт 8000) + python-telegram-bot webhook
- Worker: отдельный процесс, очередь через Redis
- БД: PostgreSQL (asyncpg + SQLAlchemy async)
- Кэш: Redis
- AI: Anthropic API через AnthropicPool (core/anthropic_client.py)

## Структура проекта
- bot/handlers/ — Telegram handlers
- bot/middleware/ — auth, typing
- worker/tasks/ — cron задачи (morning_brief, analytics и др.)
- worker/consumer.py — worker runner
- db/models/ — SQLAlchemy модели
- db/crud/ — CRUD операции
- db/seeds/ — seed данные (scoring_matrices, translate_items)
- services/ — бизнес логика (scoring.py, usage.py, i18n/)
- core/ — инфраструктура (anthropic_client.py, scheduler.py)

## Ключевые соглашения
- Все DB операции: AsyncWriteSession (запись) / AsyncReadSession (чтение)
- Логирование: structlog (logger = structlog.get_logger())
- Переменные окружения: через config.py (pydantic BaseSettings)
- Строки интерфейса: services/i18n/ru.py через t("key")
- Redis из bot: context.bot_data["redis"]
- owner_id для вещей: child.id если segment=mom_girl/mom_boy, иначе user.id

## Модели
- User: telegram_id, plan (free/basic/family/premium), segment, city, timezone
- Child: user_id, name, birthdate, gender, colortype, current_size, shoe_size
- WardrobeItem: owner_id, owner_type (user/child), category_group, type, color, score_item
- ScoringMatrix: name (0-3/3-7/7-12/12-16/16-25/25-35/35-45/45+/pregnant-1/2/3)
- BriefLog: user_id, date, outfit_items, feedback, is_wow

## Vision (добавление вещей)
- Модель: claude-sonnet-4-6 (НЕ haiku — плохое качество)
- Промпт: короткий — длинный ухудшает распознавание
- Ориентация: вертикальное фото работает лучше горизонтального
- Дедупликация: ОТКЛЮЧЕНА (мешает больше чем помогает)
- max_tokens: 4096 (иначе обрезает JSON)

## Скоринг
- Матрицы в БД: таблица scoring_matrices, seeded при старте
- Шкала: 0-2 × вес, нормируется в 10
- score_version="v2.0" — текущая версия
- Prompt caching: system промпт кэшируется через cache_control

## Деплой
- VPS: 100.97.47.50 (Tailscale), Ubuntu 24.04 ARM64
- Docker compose: ~/fashion-bot/docker/docker-compose.yml
- Rebuild: docker compose -f ~/fashion-bot/docker/docker-compose.yml up --build -d
- Cloudflare Tunnel: systemd сервис cloudflared (URL меняется при рестарте!)
- Webhook: обновлять после рестарта tunnel

## Важные ограничения
- Cloudflare Tunnel URL нестабильный — нужен именованный tunnel (v1.4)
- photo_url пустой — фото только в Telegram (R2 в v1.4)
- Дедупликация отключена — редактирование вещей в v1.2
- Онбординг: нет возраста для взрослых и триместра для беременных (v1.2)

## Переменные окружения (.env)
- TELEGRAM_BOT_TOKEN — @fashion_castle_bot
- ANTHROPIC_API_KEYS — через запятую для пула
- DATABASE_WRITE_URL / DATABASE_READ_URL — postgres с ?ssl=disable
- ADMIN_TELEGRAM_IDS — 195169

## Roadmap
- v1.1 (текущая) — Vision улучшения, Morning Brief, скоринг
- v1.2 — онбординг жены, редактирование вещей, матрицы скоринга
- v1.4 — Cloudflare R2, Sentry, именованный tunnel
- v2.0 — публичный запуск, billing
