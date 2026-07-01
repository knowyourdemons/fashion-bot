---
name: cookbook-check
description: Быстрая техническая санитарка кукбука после правок — node --check JS, pytest подмножества, grep-контракты (SYNC_KEYS, sw VERSION ↔ index.html ?v=). Use после изменений в landing/ или api/routes/cookbook.py, перед деплоем/коммитом.
---

# Cookbook Quick Check

Дешёвый пред-деплойный гейт для кукбука. Прогоняй после каждой правки `landing/` или `api/routes/cookbook.py`. Всё read-only, быстро.

## Шаги
1. **Синтаксис JS** (плоский браузерный JS, без сборки):
   ```
   node --check landing/js/app.js
   node --check landing/js/assistant.js
   node --check landing/js/sync.js
   node --check landing/sw.js
   ```
2. **Синтаксис бэкенда**:
   ```
   python3 -c "import ast; ast.parse(open('api/routes/cookbook.py').read()); print('PY OK')"
   ```
3. **Контракт SYNC_KEYS** — множество ключей должно совпадать в трёх местах. Сравни:
   - `landing/js/app.js` (`Store` + `save`-ключи), `landing/js/sync.js` (`SYNC_KEYS`), `api/routes/cookbook.py` (`SYNC_KEYS`).
   ```
   grep -n "SYNC_KEYS" landing/js/sync.js api/routes/cookbook.py
   ```
   Если правил Store — убедись, что тест `tests/test_cookbook_sync.py` (он ассертит это равенство) пройдёт.
4. **Контракт кэш-версии** — `sw.js VERSION` == `?v=` в `index.html`:
   ```
   grep -n "VERSION" landing/sw.js
   grep -n "?v=" landing/index.html | head
   ```
   Если менял фронт — версия должна быть бампнута и одинакова везде.
5. **Юнит-тесты кукбука** (если доступен docker):
   ```
   docker exec docker-app-1 python3 -m pytest /app/tests/test_cookbook_sync.py -q
   ```

## Вывод
Короткий чек-лист: каждый шаг ✅/❌ + первая строка ошибки при падении. Если что-то красное — назови файл/строку и что поправить. Не чини сам, если не попросили — только отчёт.
