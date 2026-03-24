# Fashion Bot — STATUS (24 марта 2026)

## TODO — Что ещё нужно сделать

### P0 — Критично (до бета-теста)
- [ ] **i18n**: 15+ ключей отсутствуют в EN (brief/menus/boost/fitting/challenge/weekly) — RU юзеры видят raw keys
- [ ] **Landing page**: опубликовать на bot.fashioncastle.app, A/B тест conversion
- [ ] **Stripe webhook**: signature verification + idempotency (аналогично Stars fix)
- [ ] **Photo orientation**: EXIF rotation не работает для некоторых Android — юзер видит вещи боком/вверх ногами
- [ ] **RMBG quality**: деревянный пол плохо удаляется → артефакты на коллаже. Нужен fallback на контрастный фон или ручной кроп

### P1 — Важно (первая неделя бета)
- [ ] **LLM-as-judge tests**: Sonnet оценивает Haiku outfit output (Q6 Comment Relevance) — требует API calls
- [ ] **Golden photo dataset**: tests/golden_photos/ с known attributes для Vision accuracy (Q1)
- [ ] **Kibbe/colortype benchmark**: 10 selфи с known ground truth для Q5
- [ ] **Wardrobe pagination at DB level**: 500 items → LIMIT/OFFSET вместо полной загрузки в память
- [ ] **Pre-process thumbnails в worker**: при загрузке фото (не при генерации брифа) → убрать RMBG из hot path
- [ ] **Graceful deploy**: drain active requests перед restart (brief generation теряется при deploy)
- [ ] **Реферальная программа**: "Пригласи подругу = +7 дней" — UI + backend
- [ ] **ЮKassa**: для RU юзеров (после ИП)

### P2 — Улучшения (первый месяц)
- [ ] **A/B test paywall timing**: день 7 vs день 10 vs по engagement score
- [ ] **Prometheus + Grafana**: метрики вместо logs (P95 latency, outfit quality score)
- [ ] **Photo instruction UX**: inline пример "как фоткать вещь" при первом фото
- [ ] **Manual crop/rotate**: кнопка "повернуть" / "обрезать" для плохих фото
- [ ] **Шоппинг-лист + affiliate**: Admitad/Skimlinks интеграция
- [ ] **Brief card redesign**: больше пространства для фото, меньше текста
- [ ] **Capsule colortype filter**: build_seasonal_capsule() учитывает палитру юзера
- [ ] **Travel formality check**: деловая поездка ≠ шлёпки
- [ ] **Antibot grace period**: bulk photo upload при онбординге не должен банить
- [ ] **Dead letter queue cleanup**: cron задача для очистки (метод уже есть)

### P3 — Техдолг
- [ ] **Preference cache invalidation**: вызывать после каждого feedback (метод есть, не подключён везде)
- [ ] **Session management**: validate timezone in onboarding (TimezoneFinder может вернуть None)
- [ ] **SQLAlchemy SAWarning**: Child.wardrobe_items overlaps → добавить overlaps= param
- [ ] **PTBUserWarning per_message**: CallbackQueryHandler в ConversationHandler

---

## Что сделано (24 марта 2026) — 15 коммитов

### Инфра: OOM fix + Watchdog upgrade + Memory auto-scale
- **Worker OOM crash loop**: 591 рестарт, бриф опоздал на 2ч. Причина: memory 1024MB < RMBG peak 1100MB
- **Worker memory**: 1024MB → 1536MB, App memory: 1536MB → 2048MB
- **Watchdog blind spots**: Redis IP протух (3 дня без алертов), TELEGRAM_BOT_TOKEN не передавался
- **Watchdog: OOM/RestartCount detection**: docker inspect → Telegram алерт
- **Watchdog: memory auto-scale**: >80% usage → docker update +512MB (cap 3GB, 1GB host reserve)
- **Watchdog: re-alerts**: stale worker каждые 30 мин (не одноразовый)
- **Queue recovery lock**: Redis lock на 30s при recovery (предотвращает дубли при двойном рестарте)
- **Brief dedup**: `dedup:generate_brief:{user_id}:{date}` внутри generate_brief()

### 5 UI багов
- **"Что надеть" погода**: temp_now (текущая) вместо temp_morning (прогноз)
- **"Спросить Касси"**: подсказка про фото (вещь → гардероб, образ → оценка)
- **Цветотип**: 12 подтипов вместо 4 базовых + кнопка "определить по селфи"
- **Capsule + Travel**: owner_id для мам = child.id (было user.id → 0 вещей)
- **Travel**: восстановление reply-клавиатуры после flow

### Коллаж: bbox + RMBG
- **bbox crop**: пороги 0.92 вместо 0.55 (вещи обрезались до 44% кадра)
- **Landscape → portrait**: ротация ДО bg removal (на оригинальном фото)
- **RMBG quality**: stricter check (>15% semi-transparent → reject, 10-80% opaque)
- **RMBG memory**: asyncio.Semaphore(1) — max 1 inference одновременно (5 юзеров × 600MB = OOM)
- **Typing indicator**: background task каждые 4s (closure fix: mutable list)

### Outfit Engine: системные валидации
- **SLOT_EXCLUSIONS матрица**: one_piece → excludes [top, bottom] (расширяемая)
- **9 post-validation rules**: color harmony, colortype compliance, statement pieces, bag-shoes formality, metal tone, tights, occasion-formality, wind outerwear
- **AI prompt**: "Если one_piece, НЕ добавляй bottom"

### Shared validation module (`services/validation.py`)
- **validate_vision_item()**: category_group, season, occasion, warmth, formality, color, type, score_breakdown
- **VALID_CATEGORY_GROUPS, VALID_SEASONS, VALID_OCCASIONS**: whitelists
- **has_minimum_wardrobe()**: проверяет top+bottom или one_piece (не только count)

### Destructive аудит: 41 баг найден и исправлен
**P0 Crashes (7):**
- Worker semaphore deadlock (try/finally)
- gap_analysis redis.aclose() убивал singleton
- Vision bbox NaN/None crash
- Scoring ZeroDivisionError (empty matrix)
- OUTFIT_MAX_ADULT 26→28 + score clamp ≤10.0
- morning_brief uuid NameError

**P0 Security (2):**
- Cross-user delete: soft_delete() + get_by_id() теперь проверяют owner
- Share vote: empty voter_id → random anon ID

**P1 Data integrity (14):**
- Vision: 60s timeout, 8-item cap, expanded post-validation
- Brief: weather validation, card timeout, no-children fallback
- Admin exemption в antibot
- Queue corrupted JSON handling
- Photo counter atomic INCR
- 5 EN i18n onboarding keys
- Scoring comment per-user cache
- Billing: trial clear on payment, extend not overwrite
- Outfit evaluator missing dimensions default

**P2 Silent bugs (18):**
- Warmth filter returns filtered (not unfiltered)
- AI duplicate item dedup
- Rotation skip for small wardrobe
- Per-task 300s timeout
- Dead letter queue cleanup
- Streak freezes clamp
- Vision daily call limit (30/day)
- Russian plural fix
- Scheduler safe job imports
- Redis init asyncio.Lock

### Engagement fix
- **brief_count**: COUNT(DISTINCT date) вместо COUNT(*) — 181 дубль от crash loop удалён

### Product Quality Test Suite (48 тестов)
- 4 синтетических персоны: мама Анна, Лена no_kids, edge Катя, poison Вика
- OutfitQualityChecker: 8 deterministic checks
- 7 quality dimensions: Weather, Formality, Color, Base Layer, Duplicates, Occasion, Slots
- Parametrized: -15° to +30°, 2 персоны × 7 температур
- **Baseline: 48/48 (100%)**

### Тесты: 4371 → 4420 (+49)
- 48 product quality tests
- 1 new validation test
- Scoring tests обновлены для Vision 1-3 scale

---

## Git: 185+ коммитов

### 23 марта — 1 сессия, 25+ коммитов, 70+ файлов
```
57f0a4c..b6e838f  Полная v1.2: professional styling, USP, accessories, onboarding UX, beta prep
```

**Ключевые блоки сессии:**
- Professional styling: contrast + Kibbe + essence + fabric harmony
- USP: preference learning, streak, memory, mood, style passport Stories
- Accessories Phase 1+2: bags (21), jewelry (20), belt, formality 1-5
- Scoring v3: 8 измерений, segment overrides
- Onboarding UX: selfie-first, photo reactions + progress bar, 5-photo threshold
- Pre-generate briefs overnight, color depth 16 seasons
- Conversion: smart paywall, nudge, language picker
- Infra: deploy script, CI/CD SSH, systemd, antibot, watchdog upgrade
- Beta prep: referral tracking, day 3/7 feedback, /stats
- 12 critical bugs fixed, 0 remaining

## Тесты
- **4420 passed**, 0 failed, 5 skipped (24 марта 2026)
- 48 product quality tests (OutfitQualityChecker + 4 персоны × 7 temps)
- 122 e2e тестов (test_e2e_flows.py)
- 73 test files, 95 source files
- CI: GitHub Actions → Tests pass → Deploy via SSH
- Pre-push hook: блокирует push при failures

## Архитектура
```
FastAPI (port 8000) + PTB 22.x webhook
Worker: FastWorker (4 concurrent) + SlowWorker (2)
PostgreSQL 16 (asyncpg + SQLAlchemy 2.0 async)
Redis 7 (singleton, max 32 connections)
Satori renderer (HTML → PNG)
Anthropic: Sonnet 4.6 (Vision), Haiku 4.5 (chat/outfit)
RMBG-1.4 quantized (bg removal, 44MB)
Cloudflare tunnel → bot.fashioncastle.app
```

## Сервисы (полный список)
```
services/
  selfie_analysis.py     — Vision selfie: colortype + contrast + Kibbe + essence + tonal + chroma
  preference_learner.py  — implicit learning из BriefLog feedback (24h cache)
  streak.py              — daily streak + freeze + milestones 3-100 дней
  kassi_memory.py        — personal facts auto + explicit (3-day cooldown)
  mood.py                — weather + weekday → outfit mood (rain/sun/fog/weekend)
  body_type.py           — 5 body types + Kibbe rules + contrast + essence + fabric scoring
  normalize.py           — 250+ типов, 150+ цветов, 99 formality levels, metal tone detection
  outfit_engine.py       — AI outfit selection (Haiku) + formality coherence + styling context
  outfit_evaluator.py    — 8-dim scoring + segment overrides
  outfit_builder.py      — slot assembly, base layer filter, 5-photo minimum
  color_harmony.py       — HSL матрица 100+ цветов
  vision.py              — Sonnet Vision, multi-item, bbox, formality, bag detection
  brief_renderer.py      — Jinja2 → Satori → PNG (коллаж + style passport 1080×1920)
  brief_formatter.py     — текст брифа + UV hint
  brief_weather.py       — Open-Meteo + geocoding + UV index
  brief_card.py          — 3 card states (weather/hybrid/full)
  gap_analysis.py        — AI shopping list + bag gaps
  scoring.py             — item/outfit scoring, capsule analysis
  wardrobe_math.py       — combo counting, capsule builder, travel packing, monthly report
  i18n/                  — 144 RU keys + 160 EN keys
  image_processor.py     — RMBG-1.4 + silueta fallback
  weather_card.py        — PIL weather card

bot/handlers/
  wardrobe.py            — photo upload, outfit generation, milestone system
  onboarding.py          — ConversationHandler: selfie-first (no_kids) + standard (moms)
  billing.py             — Stars + Stripe, smart paywall (value proof + loss aversion)
  brief.py               — feedback, reroll (atomic INCR), share
  text.py                — Haiku chat + explicit memory detection
  profile.py             — all settings + Касси % + redo selfie
  capsule.py, travel.py  — UI for capsule/travel
  settings.py            — language selection
  menu.py                — dynamic wardrobe icon
  boost.py, fitting.py   — photo evaluation, fit check
  challenge.py           — 10-day capsule challenge
  ask_friend.py          — outfit voting
  style_quiz.py          — 10-pair style type quiz
  debug.py               — admin commands + /stats

bot/middleware/
  antibot.py             — per-user rate limiting + temp ban
  auth.py                — user load/create + language auto-detect
  typing.py              — typing indicator

worker/tasks/
  morning_brief.py       — schedule_all (timeout 120s) + generate + send
  pre_generate_brief.py  — overnight weather cache (02:00 local)
  analytics_report.py    — monthly style report PNG push
  capsule_season.py      — seasonal capsule push (Mar/Jun/Sep/Dec)
  wardrobe_analysis.py   — weekly versatility + orphans + imbalances
  declutter.py           — monthly declutter suggestions
  taxonomy_review.py     — daily unknown item re-classification
  unknown_items_report.py — monthly admin report
  subscription_expiry.py — trial degradation + smart paywall messages
  + 6 others (evening_push, reminders, growth_alert, etc.)
```

## Скоринг v3 (8 измерений)
| Измерение | Вес | Что оценивает |
|-----------|-----|---------------|
| color_harmony | 20% | Палитра + metal consistency + contrast match |
| proportions | 20% | Силуэт + Kibbe + обувь/сумка пропорции |
| style_coherence | 20% | Formality ±1 + стиль + текстура |
| occasion_fit | 15% | Dress code + shoe/bag occasion |
| accessory_completeness | 10% | Обувь + сумка + one statement rule |
| shoe_bag_harmony | 5% | Тональность + формальность обувь↔сумка |
| details_polish | 5% | Tucking, layering, neckline+jewelry |
| creativity | 5% | Unexpected combos, personal signature |

## Professional Styling (из 1 селфи)
- 12-season colortype + flow seasons (16 equiv)
- Contrast level: HIGH/MEDIUM/LOW
- Kibbe family: DRAMATIC/NATURAL/CLASSIC/GAMINE/ROMANTIC
- Style essence: 5 types → outfit mood
- Tonal depth: LIGHT → DEEP
- Chroma: BRIGHT/MODERATE/MUTED
- Fabric-Kibbe compatibility scoring

## Formality System
- 99 типов вещей с формальностью 1-5 (все категории)
- Coherence check в outfit_engine: ±1 (creative styles ±2)
- Occasion × formality матрица

## Юнит-экономика
| Метрика | Значение |
|---------|----------|
| API cost/user/month | $0.15 (prompt caching ON) |
| Margin | 98.4% |
| Breakeven | 1 paying user ($7.60/мес infra) |
| 10 users API cost | $1.50/мес |
| 100 users API cost | $14.50/мес |

## Scheduler (17 cron jobs)
| Job | Schedule | What |
|-----|----------|------|
| morning_brief | Every hour :00 | Brief at 07:00 local |
| evening_brief | Every hour :30 | Evening at 20:00 local |
| pre_generate_brief | Every hour :45 | Pre-gen at 02:00 local |
| daily_reset | Every hour :00 | Reset counters at 00:00 local |
| evening_push | Every hour :45 | Evening push at 20:00 local |
| weekly_plan | Every hour :15 | Sunday 19:00 local |
| analytics_report | Day 1, 08:00 | Monthly report push |
| capsule_season | Day 1, 09:30 | Seasonal capsule push |
| wardrobe_analysis | Monday 06:00 | Weekly wardrobe health |
| declutter | Day 15, 10:00 | Monthly declutter suggestions |
| taxonomy_review | Daily 04:00 | Re-classify unknown items |
| unknown_items_report | Day 1, 07:00 | Admin report |
| gap_analysis | Day 1, 09:00 | Monthly gap analysis |
| subscription_expiry | Daily 09:00 | Trial notifications |
| reminders | Daily 10:00 | Cold user reminders |
| growth_alert | Day 1, 08:30 | Child growth alerts |
| cleanup_r2 | Daily 03:00 | R2 storage cleanup |

## Monitoring
- **Sentry**: app + worker + PTB error handler
- **Watchdog**: health check + worker heartbeat + restart loop detection + Telegram alerts
- **systemd**: fashionbot.service (auto-start on reboot)
- **CI/CD**: Tests → Deploy → Telegram notification

## Beta Readiness
- ✅ Referral tracking: `t.me/fashioncastle_bot?start=ref_SOURCE`
- ✅ Day 3/7 feedback prompts
- ✅ /stats admin dashboard
- ✅ All containers healthy, 4420 tests pass (4371 tech + 48 product quality + 1 validation)
- ✅ 41 баг из destructive аудита исправлен
- ✅ Payment idempotency (Stars)
- ✅ Cross-user access blocked
- ✅ 23 outfit post-validation rules
- ✅ Vision input validation (7 полей)
- ✅ Worker OOM/deadlock protected
- ✅ Memory auto-scale + typing indicator
- ✅ Product quality test suite (baseline 48/48)
- ⚠️ i18n: 15+ EN ключей отсутствуют (brief/menus/boost)
- ⚠️ RMBG quality: артефакты на некоторых фонах
- ⚠️ Stripe webhook: нет signature verification
