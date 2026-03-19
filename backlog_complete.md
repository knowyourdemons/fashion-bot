# Fashion Bot — Полный бэклог v1.0 remaining + v1.1

## v1.0 REMAINING (до запуска жене)

### В Claude Code сейчас:
- [ ] Онбординг UX (Касси, fuzzy дата, float обувь, прогресс, "Для обоих")
- [ ] Объединение outfit_builder (wardrobe.py + morning_brief.py → единый модуль)
- [ ] Хотфиксы (эмодзи в PIL, шорты при холоде, скор текстом 10+ мест)

### Нужно отдать в Claude Code:
- [ ] Меню: "Что надеть" full-width + "Спросить Касси" + handlers (промт готов)
- [ ] Текст брифа 15→5 строк, color_circle, температура round (промт готов)
- [ ] Visual polish: центрирование подписей, увеличить иконки/фото, контекст "садик" (промт готов)

### Руками (быстрые фиксы):
- [x] brief.py "Другое" → inline кнопка "🔄 Другой образ" (СДЕЛАНО)
- [x] Центрирование куртки placeholder зоны 1 (СДЕЛАНО)
- [x] Увеличить иконки placeholder 0.75→0.85 (СДЕЛАНО)

---

## v1.1 (после запуска, апрель)

### Коллаж
- [ ] Цветной фон карточек по доминантному цвету вещи (getcolors + lighten)
- [ ] Сезонные иконки placeholder (outerwear_light.png для ветровки при +10°C)
- [ ] AI-плейсхолдеры: 25 AI-картинок вместо outline-силуэтов, подбор по цветотипу/полу
- [ ] Тени усилить (SHADOW_BLUR=9 может быть мало на большом canvas)

### Профиль и настройки
- [ ] /profile — просмотр и редактирование города, цветотипа, сегмента
- [ ] /add_child — добавить ребёнка после онбординга, меняет сегмент
- [ ] Онбординг resumable — не сбрасывать при смене сегмента
- [ ] Переключение "чьи вещи добавляю" при отправке фото (свои / ребёнка)
- [ ] Возраст для взрослых (no_kids) в онбординге
- [ ] Триместр для беременных в онбординге

### Оценка образа по фото
- [ ] Фото в чат → определить: вещь flat lay vs outfit (человек в полный рост)
- [ ] Если outfit → оценить, дать советы по стилю (Haiku + Vision)
- [ ] Если вещь → добавить в гардероб (текущее поведение)

### Образ и бриф
- [ ] Контекстный чат — wardrobe summary в system prompt Haiku
- [ ] Re-roll "переодень" — кнопка + exclude текущих + Redis counter 3/день premium
- [ ] Вечерний образ 20:00 — scheduler по timezone, "на завтра"
- [ ] Trial постепенное отключение дни 12-14 (re-roll → вечерний → чат)
- [ ] Тизеры в не-бриф дни ("У меня есть образ с твоим тренчем")
- [ ] Engagement push дни 3/7/10/11
- [ ] Trial report день 11
- [ ] "Переслать бабушке" кнопка
- [ ] Погодный alert (резкое изменение погоды)
- [ ] Календарь образов (история за неделю/месяц)
- [ ] Контекст "садик/школа/площадка" по возрасту ребёнка
- [ ] Шорты: type_not_contains="юбк" тоже при холоде для совсем маленьких

### Гардероб
- [ ] Цветные кружки color_circle() в списке вещей ("👀 Посмотреть вещи")
- [ ] Gap analysis → список что купить (цвет по цветотипу, тип по сезону)
- [ ] Growth alert WHO (ребёнок вырос из размера)
- [ ] Сумки в taxonomy (category_group "bags")
- [ ] Vision: улучшить распознавание (носок≠шапка, ковёр не одежда)

### Инфраструктура
- [x] rembg local ONNX silueta (43MB, 1.3 сек, fallback remove.bg API) — ГОТОВО 2026-03-19
- [x] Redis singleton (core/redis.py, 17 утечек закрыты) — ГОТОВО 2026-03-19
- [x] DB индексы (6 критических, partial на soft-delete) — ГОТОВО 2026-03-19
- [x] Health check реальный (Redis+DB, 503 при сбое) — ГОТОВО 2026-03-19
- [x] Queue at-least-once (RPOPLPUSH+ack+recovery) — ГОТОВО 2026-03-19
- [x] Exponential backoff (1s→4s→16s) — ГОТОВО 2026-03-19
- [x] Background task tracking + graceful shutdown — ГОТОВО 2026-03-19
- [x] Paginated schedule_all (batch 500) — ГОТОВО 2026-03-19
- [x] Atomic rate limiter (Lua script) — ГОТОВО 2026-03-19
- [x] CASCADE → SET NULL на логах — ГОТОВО 2026-03-19
- [x] Worker concurrency (semaphore fast=4, slow=2) — ГОТОВО 2026-03-19
- [x] Correlation ID (ContextVar + structlog) — ГОТОВО 2026-03-19
- [x] Pool tuning (pre_ping, recycle 10min) — ГОТОВО 2026-03-19
- [x] Atomic Anthropic pool rotation (asyncio.Lock) — ГОТОВО 2026-03-19
- [ ] Sentry для error tracking
- [ ] CI/CD (GitHub Actions → Docker build → deploy)
- [x] Cloudflare named tunnel (URL не меняется при рестарте) — УЖЕ БЫЛО
- [ ] photo_url через R2 CDN (сейчас только telegram file_id)

---

## v1.2 (май)

### Монетизация
- [ ] Шоппинг-лист: gap analysis → что купить + ценовой диапазон
- [ ] Affiliate: EU = H&M (7%) + Reima через Skimlinks/AWIN
- [ ] Affiliate: RU/CIS = Lamoda (10-12%) + WB через Admitad
- [ ] ЮKassa (после открытия ИП в РБ/ЛТ)
- [ ] Paddle (альтернатива Stripe для EU)
- [ ] Stripe price_id заполнить в permissions.PRICES

### Фичи
- [ ] Антибот: cooldown 24ч при 3 мусорных фото, honeypot метрики
- [ ] "Для обоих" в онбординге (also_for_self flag)
- [ ] Реферальная программа

---

## v2.0 (июль)

- [ ] Ultra план ($19/мес) — AI-стилист, неограниченный чат, семейный аккаунт
- [ ] Семейный аккаунт (несколько детей + взрослые)
- [ ] EN локализация
- [ ] Публичный маркетинг (Product Hunt, Reddit, мама-форумы)
