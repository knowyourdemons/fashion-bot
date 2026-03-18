# Fashion Bot — CLAUDE.md

## Инфраструктура
- VPS: agent-farm-01, user=stas, ~/fashion-bot
- Containers: docker-app-1 (FastAPI+PTB), docker-worker-1, 
  docker-postgres-1, docker-redis-1
- GitHub: knowyourdemons/fashion-bot
- Tunnel: bot.fashioncastle.app (именованный Cloudflare tunnel ✅)
- Webhook: https://bot.fashioncastle.app/api/v1/webhooks/telegram

## Архитектура
- FastAPI app (порт 8000) + python-telegram-bot webhook
- Worker: отдельный процесс, очередь через Redis
- БД: PostgreSQL (asyncpg + SQLAlchemy async)
- Кэш: Redis
- AI: Anthropic API через AnthropicPool (core/anthropic_client.py)
- Два API ключа в пуле с watchdog (автопереключение при 429)

## Стек
- Python 3.12, PTB 22.x, SQLAlchemy 2.0, asyncpg
- Vision: claude-sonnet-4-6
- Чат/бриф/текст: claude-haiku-4-5-20251001
- remove.bg size=small ($0.002/фото)
- Prompt caching: ephemeral везде

## Структура проекта
- bot/handlers/ — Telegram handlers
  - wardrobe.py — Vision, коллаж, owner switching, оценка образа
  - onboarding.py — ConversationHandler онбординга
  - subscription.py — /subscribe, /test_subscribe, Stars/Stripe
  - text.py — Haiku чат стилиста
  - start.py — /start handler
- bot/middleware/ — auth, typing
- worker/tasks/ — cron задачи
  - morning_brief.py — бриф для детей и взрослых
  - style_config.py — COLORTYPE_PALETTES, WOW_PHRASES, _needs_tights
  - subscription_expiry.py — уведомления об окончании trial
  - evening_push.py — вечерний push в 20:00
- db/models/ — SQLAlchemy модели
- db/crud/ — CRUD операции
- services/
  - image_builder.py — коллаж, силуэты (детские + взрослые)
  - scoring.py, usage.py, i18n/
- permissions.py — лимиты, планы, trial логика (ЦЕНТРАЛЬНЫЙ ФАЙЛ)

## Ключевые соглашения
- Все DB операции: AsyncWriteSession (запись) / AsyncReadSession (чтение)
- Логирование: structlog (logger = structlog.get_logger())
- Переменные окружения: через config.py (pydantic BaseSettings)
- Строки интерфейса: services/i18n/ru.py через t("key")
- Redis из bot: context.bot_data["redis"]
- owner_id: child.id если segment=mom_girl/mom_boy, иначе user.id
- Активный owner: _get_owner(user, context) → (owner_id, owner_type)

## Модели БД
- User: telegram_id, plan (free/premium/ultra/admin), segment, 
  city, timezone, onboarding_completed, onboarding_step,
  trial_started_at, trial_ends_at, plan_expires_at, payment_provider
- Child: user_id, name, birthdate, gender, colortype, 
  current_size, shoe_size
- WardrobeItem: owner_id, owner_type (user/child), 
  category_group, type, color, season, score_item, show_in_collage
- ScoringMatrix: name, age_from, age_to, criteria (JSONB), max_score
- BriefLog: user_id, date, outfit_items, feedback, is_wow

## Планы и лимиты (permissions.py)
- free: 3 фото/день, 15 вещей, 3 оценки, 3 чата, 1 образ, бриф вт/чт
- premium ($9/мес): 30 фото, 500 вещей, 20 оценок, 20 чатов, 
  5 образов, бриф каждый день
- ultra: заглушка (шоппинг-лист, капсула, семья — в разработке)
- admin: безлимит (telegram_id=195169)
- Trial: 14 дней с первого фото → premium доступ
- get_effective_plan(user) — учитывает trial и plan_expires_at

## Платежи
- Stripe: для Европы (картой + Apple/Google Pay)
- Telegram Stars: универсально без юрлица
- ЮKassa: заглушка (нужно ИП в РФ/РБ)
- Paddle: заглушка (альтернатива без юрлица)
- Цены: $9/мес, $22/3мес, $72/год | 700/1700/5500 Stars
- После оплаты: _activate_premium_after_payment() в webhooks.py

## Vision (добавление вещей)
- Модель: claude-sonnet-4-6 (НЕ haiku — плохое качество)
- Фото вертикально: качество распознавания лучше
- Дедупликация: ОТКЛЮЧЕНА
- Bbox валидация: w>0.8 или h>0.8 → центральный crop
- remove.bg: size=small, затем → rembg u2net локально (v1.2)

## Коллаж
- image_builder.py: build_collage(outfit_slots)
- Реальные вещи + плейсхолдеры с силуэтами
- Детские силуэты: по возрасту и полу ребёнка
- Взрослые силуэты: женские пропорции (грубые, TODO редизайн)
- adult=True в outfit_slots → взрослые силуэты
- show_in_collage=True если alpha ratio ≥15%

## Бриф
- Детский (mom_girl/mom_boy): Vision коллаж + Haiku текст
- Взрослый (no_kids/pregnant): погода + Haiku совет по цветотипу
- Free: бриф вт/чт | Premium: каждый день включая выходные
- is_brief_day(plan, timezone) в permissions.py
- Цветотипы: Весна/Лето/Осень/Зима → палитры в style_config.py

## Тестирование
- /test_subscribe — только для admin, тест платёжного флоу
- Тесты: tests/test_smoke.py, test_unit.py, test_integration.py
- Запуск: docker exec docker-app-1 python3 -m pytest /app/tests/ -v
- 60+ тестов

## Деплой
- Рестарт app: docker restart docker-app-1
- Рестарт worker: docker restart docker-worker-1
- Worker sync (обязательно для morning_brief, style_config):
  docker cp docker-app-1:/app/FILE /tmp/F && 
  docker cp /tmp/F docker-worker-1:/app/FILE
- Sync на хост: docker cp docker-app-1:/app/FILE ~/fashion-bot/FILE
- Alembic: docker exec docker-app-1 alembic upgrade head
- Backup: pg_dump cron ежедневно 3:00, хранить 7 дней

## Тест-пользователи
- Стас: telegram_id=195169, plan=admin
- Алиса: owner_id=acf0100d-ca11-4fce-815e-c516af11e710, 3г, девочка, Лето
- Город: Вильнюс, timezone: Europe/Vilnius

## Известные баги / TODO
- Силуэты (детские+взрослые) нарисованы грубо → редизайн SVG/иконки
- /profile + /add_child — не реализовано
- Онбординг сегменты обидные → переделать UX (в работе)
- Размер обуви принимает только int → нужен float (26.5)
- Лимиты применяются во время онбординга → фикс нужен
- ЮKassa требует ИП/ООО → после открытия в РБ
- Stripe price_id не заполнены в permissions.PRICES

## Роадмап
- Срочно: онбординг UX фикс, лимиты в онбординге, размер обуви
- v1.1: силуэты редизайн, /profile, /add_child, онбординг resumable
- v1.2: шоппинг-лист, growth_alert, capsule_season, wardrobe_analysis
- v2.0: семейный аккаунт, Ultra план, ЮKassa после ИП