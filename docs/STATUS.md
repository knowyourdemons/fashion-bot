# Fashion Bot — STATUS (23 марта 2026)

## Git: 153 коммита (20-23 марта 2026)

### 23 марта (2 коммита)
```
ffb88b4 fix: update 10 legacy tests for v2.1 changes
facf5c3 feat: v2.1 — professional styling, USP features, accessories, 101 e2e tests
```

**Сессия 23 марта — 62 файла, +4963 строк:**
- Professional styling: contrast + Kibbe + essence из селфи
- USP: preference learning, streak, memory, mood
- Accessories Phase 1+2: bags (21 тип), jewelry (20 типов), formality 1-5
- Scoring v3: 8 измерений + segment overrides
- UI: Capsule, Travel, Monthly Report, EN localization
- Conversion: smart paywall, wardrobe nudge, language picker
- Infra: deploy script, antibot, Loki, 4 worker tasks
- 9 критических багов исправлено
- 101 новый e2e тест, 4349 всего

## Тесты
- **4349 passed**, 0 failed, 5 skipped (23 марта 2026)
- 101 e2e тестов в test_e2e_flows.py
- CI: GitHub Actions на каждый push/PR
- Pre-push hook блокирует push при failures

## Архитектура (актуальная)
```
FastAPI (port 8000) + PTB webhook
Worker (consumer.py): FastWorker (4 concurrent) + SlowWorker (2)
PostgreSQL 16, Redis 7, Satori renderer
Anthropic: Sonnet 4.6 (Vision), Haiku 4.5 (chat/outfit)
RMBG-1.4 quantized (bg removal, 44MB)
```

## Новые сервисы (23 марта)
```
services/
  preference_learner.py  — implicit learning из BriefLog feedback
  streak.py              — daily streak + freeze + milestones
  kassi_memory.py        — personal facts + explicit memory из чата
  mood.py                — weather + weekday → outfit mood
  body_type.py           — 5 types + Kibbe + contrast + essence + fabric scoring

bot/handlers/
  capsule.py   — /capsule, seasonal capsule builder UI
  travel.py    — /travel, 3-step inline packing flow
  settings.py  — language selection

bot/middleware/
  antibot.py   — per-user rate limiting + temp ban

worker/tasks/
  wardrobe_analysis.py      — weekly versatility + orphans + imbalances
  declutter.py              — monthly declutter suggestions
  taxonomy_review.py        — daily unknown item re-classification
  unknown_items_report.py   — monthly admin report
  analytics_report.py       — monthly style report PNG push
  capsule_season.py         — seasonal capsule push
```

## Скоринг v3 (8 измерений)
| Измерение | Вес | Новое? |
|-----------|-----|--------|
| color_harmony | 20% | обновлено |
| proportions | 20% | обновлено |
| style_coherence | 20% | обновлено |
| occasion_fit | 15% | обновлено |
| accessory_completeness | 10% | NEW |
| shoe_bag_harmony | 5% | NEW |
| details_polish | 5% | — |
| creativity | 5% | — |

## Professional Styling (из 1 селфи)
- 12-season colortype ✅
- Contrast level (HIGH/MEDIUM/LOW) ✅
- Kibbe family (5 types) ✅
- Style essence (5 types) ✅
- Fabric-Kibbe compatibility scoring ✅

## Formality System
- 60+ типов вещей с формальностью 1-5
- Coherence check в outfit_engine (±1, creative ±2)
- Occasion × formality матрица

## i18n
- 80+ ключей RU + EN
- Auto-detect language из Telegram
- Language picker для unknown locale
- Все хендлеры используют `t(key, lang)`

## Unit Economics (на 1000 юзеров)
- Breakeven: 11 paying users ($99/mo costs ÷ $9/user)
- Conversion: ~7% trial → paid
- LTV/CAC: 7.5-19x
- Gross margin: 51.7%
- Подробнее: docs/simulation_1000_users.md

## Роадмап
### v1.0-v1.1 ✅ ГОТОВО
Все базовые + продвинутые фичи реализованы.

### v1.2 (апрель-май)
- ЮKassa для RU юзеров (после ИП)
- Шоппинг-лист + affiliate
- Реферальная программа
- A/B test paywall timing

### v2.0 (июль)
- Ultra план, семейный аккаунт
- Маркетинг: TikTok/Reels, Telegram каналы
- Беременность: триместр в онбординге
