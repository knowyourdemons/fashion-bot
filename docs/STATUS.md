# Fashion Bot — STATUS (23 марта 2026, вечер)

## Git: 170+ коммитов

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
- **4371 passed**, 0 failed, 5 skipped
- 122 e2e тестов (test_e2e_flows.py)
- 72 test files, 92 source files
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
- ✅ Kate onboarding reset
- ✅ All containers healthy, 4371 tests pass
