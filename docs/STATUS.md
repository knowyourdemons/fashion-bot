# Fashion Bot — STATUS (22 марта 2026)

## Git: последние коммиты (сессия 22 марта)
```
520d83c fix: pass body_type to AI engine + update CLAUDE.md with session work
b9beccf feat: pre-Vision photo quality assessment + auto-correction
6bdf970 feat: expand normalization to 250+ type synonyms, 150+ color synonyms
f50bc60 feat: type/color normalization for unknown clothing items
52aaa19 feat: 63 stylist simulation tests + fix analogous color range
f4d00e9 feat: professional styling system — 12 improvements across 10 files
f93c45f feat: 470 synthetic wardrobe tests + 2 outfit selector fixes
```

## Тесты
- Всего: **2066**
- Passed: **2066**
- Skipped: 6
- Failed: **0**

## Что сделано (22 марта 2026 — сессия 2)

### Оценка образа по фото — профессиональная стилистика (`services/outfit_evaluator.py`)
- **6 измерений оценки** (веса суммируются до 100%):
  - Цветовая гармония (25%) — правило 60-30-10, monochrome/analogous/complementary
  - Пропорции и силуэт (25%) — правило третей, баланс объёмов
  - Стилевое единство (20%) — согласованность стиля, текстуры
  - Уместность (15%) — повод, сезон, формальность
  - Детали и завершённость (10%) — аксессуары, focal point
  - Индивидуальность (5%) — неожиданный элемент, личность
- **Детская оценка** — альтернативные измерения: безопасность (20%), комфорт (20%), цвета (20%), погода (20%), возраст (15%), индивидуальность (5%)
- **5 tier-ов** (без цифр юзеру): Wow (9+) / Отличный (7.5+) / Хороший (6+) / Есть потенциал (4.5+) / Давай усилим! (<4.5)
- **Cross-validation цветов** — локальная HSL-матрица перепроверяет Vision (предотвращает hallucinated "отличная гармония" на клэше)
- **Структурированный JSON-промпт** — Vision возвращает JSON с dimensions + strengths + improvements + swaps
- **Контекстный промпт**: colortype, body_type, segment, child_age, wardrobe для замен
- **Правило пропорций** в промпте: 1/3-2/3, баланс объёмов, зеркальное селфи
- **CTA после оценки**: "Что надеть" при низком скоре, "Сохрани в избранное" при wow
- **Truncated fallback**: raw text обрезается до 500 символов при parse failure

### Обновлённый handler (`bot/handlers/wardrobe.py`)
- `_rate_photos()` передаёт colortype, body_type, segment, child_age
- Автоопределение возраста ребёнка из БД
- Контекст пользователя из db_user → более точная оценка

### Обновлённый Vision API (`services/vision.py`)
- `_call_rate_vision()` использует новый структурированный промпт
- Sonnet 4.6 (не Haiku) для оценки образа (лучше качество)
- max_tokens: 512 → 1024 (JSON ответ длиннее текстового)
- Fallback: truncated raw text при JSON parse failure

### Тесты: 89 новых (`tests/test_outfit_evaluator.py`)
| Группа | Тестов | Покрытие |
|--------|--------|----------|
| Tier system | 11 | Границы, эмодзи, labels |
| Prompt building | 15 | Adult/child, colortype, body_type, segment, wardrobe, proportions |
| JSON parsing | 12 | Valid/invalid/fenced/clamped/defaults |
| Text formatting | 15 | All tiers, swaps, CTA, no numeric score |
| Cross-validation | 7 | Neutrals, clashes, monochrome |
| Outfit heuristic | 7 | Single/multiple categories, base layer |
| Маша (мама) | 4 | Dark hallway, child outfit, swap suggestion |
| Лена (no_kids) | 4 | Work outfit, date night, bold combo, mirror selfie |
| Edge cases | 7 | No person, flat lay, empty wardrobe, corrupt |
| Dimension weights | 4 | Sum=100, labels, top weight |
| E2E pipeline | 4 | Adult, child, not-outfit, clash correction |

### Совет экспертов (2 итерации)
- **Итерация 1**: Стилист, UX лид, Маша, Лена, Психолог → 5 фиксов:
  - "Попробуй по-другому" → "Давай усилим!" (growth mindset)
  - Правило пропорций в промпте
  - Hint про зеркальное селфи
  - CTA после оценки
  - Truncated fallback
- **Итерация 2**: Финальная валидация — одобрено всеми 5 экспертами

## Новые модули (22 марта 2026)

### `services/color_harmony.py` — HSL матрица цветовой совместимости
- 100+ русских цветов → HSL (hue, saturation, lightness)
- `color_compatibility(a, b)` → score -2..+2:
  - +2: neutral + anything, monochrome
  - +1: analogous (hues ≤60°), complementary (~180°)
  - 0: triadic, unknown
  - -1: mild clash (70-100° + saturated)
- `score_outfit_colors(items)` → 0..10
- `is_neutral()` — белый/чёрный/серый/бежевый/navy = combine with anything

### `services/normalize.py` — нормализация типов вещей и цветов
- **250+ типов** → канонические формы для `_select_outfit()`:
  - Headwear: капор, балаклава, тюбетейка, берет, шляпа, федора → "шапка"
  - Footwear: кеды, лоферы, оксфорды, мюли, эспадрильи, берцы → canonical
  - Tops: баска→блузка, болеро→кардиган, бралетт→топ, свитшот→худи
  - Bottoms: скинни→джинсы, палаццо→брюки, плиссе→юбка
  - Baby: ползунки→комбинезон, распашонка→футболка, конверт→комбинезон
- **150+ цветов** → канонические:
  - маренго→тёмно-серый, марсала→бордовый, фуксия→розовый
  - цвет морской волны→бирюзовый, сиреневый→лавандовый
  - English: navy→тёмно-синий, burgundy→бордовый, teal→бирюзовый
- **Интеграция**: `wardrobe.py` вызывает нормализацию ДО записи в БД
- **Также исправляет category_group**: берет как "top" → "accessory"

### `services/photo_quality.py` — оценка качества фото до Vision API
- **Проверки** (< 50ms):
  - Разрешение: < 200×200 → reject ("слишком маленькое")
  - Яркость: < 40 → auto-fix + warn ("слишком тёмное")
  - Яркость: > 245 → warn ("пересвечено")
  - Blur: Laplacian variance < 30 → warn ("размытое")
  - Aspect ratio: > 4:1 → warn ("скриншот/панорама")
  - Contrast: stddev < 15 → warn ("однотонное")
- **Auto-correction**: тёмные фото осветляются перед Vision (экономия $0.003/call)
- **User tips**: конкретные подсказки на русском ("включи свет", "держи ровно")

## Улучшения outfit selection (22 марта 2026)

### AI промпты (outfit_engine.py)
| Улучшение | Описание |
|-----------|----------|
| Цветовая гармония | 60-30-10 rule, 3 цвета max, monochrome/analogous/complementary |
| Body type | 5 типов фигуры → стилистические правила в промпте |
| Occasion filtering | Исключение evening/party в будни, formal в выходные |
| 4 возрастных промпта | 0-3 (безопасность), 3-7 (самостоятельность), 7-12 (баланс), 12-16 (тренды) |
| Wind chill | `calc_wind_chill()` — ощущаемая температура |
| UV index | UV≥6 → "панамка обязательна" |
| Colortype palette | Конкретные цвета из палитры в промпте |
| Style preferences | avoid/prefer/style из user.style_preferences |

### Rule-based selector (outfit_selector.py)
| Улучшение | Описание |
|-----------|----------|
| Season fallback | Если нет top+bottom после фильтра → используй ВСЕ вещи |
| Score preference | `_first()` сортирует по score_item desc |
| Freshness bonus | +1.0 для вещей не ношенных >7 дней |
| Warmth consistency | Нет пуховик (warmth=5) + шорты (warmth=1) |

### 12-season colortype (style_config.py)
- 12 подтипов вместо 4: Bright/True/Light Spring, Light/True/Soft Summer, Soft/True/Deep Autumn, Deep/True/Bright Winter
- 6-8 цветов на слот (было 3)
- Backward-compatible: "Лето" → True Summer, "Зима" → True Winter

### Capsule wardrobe (scoring.py)
- `calc_item_versatility()` — сколько вещей сочетается с данной
- `get_wardrobe_gaps()` — минимумы (3 tops, 2 bottoms, 2 shoes), orphan detection
- Combo potential: tops × bottoms × (outerwear+1) + dresses

### Scoring refactor (scoring.py)
- Adult: color_harmony 2→3, occasion_fit 1→2, +body_type_fit(1) = 26 max
- Child: +safety(1) = 11 max
- WOW threshold: transformation≥3 AND unexpected_combination≥2

## Интеграционные фиксы
- `body_type` теперь передаётся в `select_outfit_ai()` из:
  - `wardrobe.py` (кнопка "Что надеть")
  - `morning_brief.py` (утренний бриф)
- `day_type` корректно определяется: weekday<5 → "садик"/"работа", else → "прогулка"/"выходной"

## Новые тестовые файлы

| Файл | Тестов | Покрытие |
|------|--------|----------|
| `test_wardrobe_optimizer.py` | 470 | 12 сегментов × 4 размера гардероба × 8 погод + edge cases |
| `test_stylist_simulation.py` | 63 | 3 персоны: стилист (цвета), мама (детская безопасность), женщина (стиль) |
| `test_normalize.py` | 175 | 250+ типов, 150+ цветов, интеграция с selector |
| `test_photo_quality.py` | 52 | Яркость, blur, resolution, форматы, телефоны, corrupt |

## Контейнеры

| Контейнер | Статус | Memory |
|-----------|--------|--------|
| docker-app-1 | Up (healthy) | 113 MiB / 1.5 GiB |
| docker-worker-1 | Up (restarted) | 85 MiB / 768 MiB |
| docker-renderer-1 | Up (healthy) | 104 MiB / 768 MiB |
| docker-postgres-1 | Up (healthy) | 27 MiB / 512 MiB |
| docker-redis-1 | Up (healthy) | 4.5 MiB / 256 MiB |

## DB миграции (22 марта)
- `ALTER TABLE users ADD COLUMN style_preferences JSONB` — применена вручную

## Архитектура outfit selection (текущая)

```
User фото → photo_quality.py (brightness/blur check)
         → normalize.py (капор→шапка, маренго→серый)
         → vision.py (Claude Sonnet 4.6, multi-item detection)
         → post_validate (шорты→штаны при <10°C)
         → wardrobe DB (with score, warmth, bbox)

"Что надеть" / Morning brief:
  → load items + weather + user profile
  → outfit_engine.py (Claude Haiku):
      - Age-specific prompt (0-3/3-7/7-12/12-16)
      - Color harmony rules (60-30-10)
      - Body type hints
      - Occasion filtering
      - Colortype palette
      - Wind chill + UV
  → fallback: outfit_selector.py (rule-based):
      - Season + warmth + score preference
      - Freshness bonus
      - Warmth consistency check
  → outfit_builder.py (slots assembly, base layer filter)
  → brief_card.py → Playwright → PNG collage
```

## Роадмап статус

### v1.0 ✅ DONE
- Онбординг, утренний бриф, Sentry, CI/CD, RMBG-1.4

### v1.1 (апрель) — в процессе
| Фича | Статус |
|------|--------|
| Контекстный чат | ✅ DONE |
| Re-roll (детский + взрослый) | ✅ DONE |
| Вечерний образ 20:00 | ✅ DONE |
| Trial degradation дни 12-14 | ✅ DONE |
| RMBG-1.4 quantized | ✅ DONE |
| Sentry + CI/CD | ✅ DONE |
| Профессиональная стилистика | ✅ DONE (22 марта) |
| Нормализация вещей/цветов | ✅ DONE (22 марта) |
| Pre-Vision photo quality | ✅ DONE (22 марта) |
| /profile + /add_child | 🔲 TODO |
| Оценка образа по фото | ✅ DONE (22 марта) |
| Gap analysis + growth alert | 🔲 TODO (capsule scoring готов) |
| Reminders (3/7/30 дней) | ✅ DONE (22 марта) |
| Birthday alert | ✅ DONE (22 марта) |
| Gap insights в brief | ✅ DONE (22 марта) |
| Тизеры, engagement push | ✅ DONE (ранее) |

### v1.2 (май) — планируется
- Шоппинг-лист + affiliate
- ЮKassa/Paddle
- Антибот, реферальная
- Prometheus + Grafana
- User style_preferences через онбординг
- 12-season цветотип через расширенный анализ селфи

### v2.0 (июль)
- Ultra план, семейный аккаунт, EN, маркетинг

## Файлы проекта (ключевые)

```
services/
  color_harmony.py     — NEW: HSL матрица 100+ цветов, compatibility scoring
  normalize.py         — NEW: 250+ типов + 150+ цветов нормализация
  photo_quality.py     — NEW: pre-Vision яркость/blur/contrast + auto-fix
  outfit_engine.py     — AI outfit selection (Haiku), 4 возрастных промпта
  outfit_selector.py   — Rule-based fallback, score preference, warmth check
  outfit_builder.py    — Slot assembly, base layer filter, collage params
  scoring.py           — Item/outfit scoring, capsule analysis, gap detection
  weather.py           — wttr.in + wind_chill(), UV index
  vision.py            — Claude Sonnet Vision, multi-item, bbox, post-validation, structured eval
  outfit_evaluator.py  — NEW: профессиональная оценка образа, 6 измерений, cross-validation
  image_processor.py   — EXIF, RMBG-1.4, thumbnail pipeline
  collage_styles.py    — 6 стилей, hex colors (расширено для 12-season)

worker/tasks/
  style_config.py      — 12-season colortype palettes (72 палитры)
  morning_brief.py     — Brief generation, body_type integration

tests/
  test_wardrobe_optimizer.py  — 470 тестов: full matrix
  test_stylist_simulation.py  — 63 теста: 3 персоны
  test_normalize.py           — 175 тестов: типы + цвета
  test_photo_quality.py       — 52 теста: фото quality
  test_outfit_evaluator.py    — NEW: 89 тестов: оценка образа, TA сценарии
  test_outfit_engine.py       — 80+ тестов: AI engine
  test_outfit.py              — 45 тестов: rule-based
  test_outfit_fixes.py        — 57 тестов: fixes
```

## Известные баги / TODO

### Средние
1. backup.sh не в crontab
2. Thumbnail cache cold start (~4с на фото)
3. photo_url пустой (только Telegram file_id)

### Косметические
4. SAWarning Child.wardrobe_items overlaps
5. PTBUserWarning per_message
6. Размер обуви только int (нужен float 26.5)

### Не реализовано
7. /profile + /add_child UI
8. ~~Оценка образа по фото~~ — ✅ DONE
9. style_preferences сбор через онбординг (поле в БД готово, UI нет)
10. 12-season определение через селфи (палитры готовы, Vision prompt нет)
