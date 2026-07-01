/* ============================================================
   Поваренная книга — основная логика (SPA, hash-роутер).
   Без сборки, без fetch для данных. Работает под file:// и на хосте.
   ============================================================ */
(function () {
  'use strict';

  /* ---------- Константы оформления ---------- */
  const CUISINE_COLOR = {
    "Итальянская": "--cover-tomato", "Русская": "--cover-honey",
    "Грузинская": "--cover-tomato", "Японская": "--cover-berry",
    "Тайская": "--cover-grass", "Китайская": "--cover-spice",
    "Мексиканская": "--cover-tomato", "Индийская": "--cover-spice",
    "Французская": "--cover-plum", "Корейская": "--cover-spice",
    "Марокканская": "--cover-spice", "Ближневосточная": "--cover-sand",
    "Турецкая": "--cover-sand", "Греческая": "--cover-berry",
    "Испанская": "--cover-tomato", "Вьетнамская": "--cover-grass",
    "Узбекская": "--cover-sand", "Американская": "--cover-honey"
  };
  const CAT_COLOR = {
    "Завтрак": "--cover-honey", "Суп": "--cover-grass", "Основное": "--cover-tomato",
    "Гарнир": "--cover-sand", "Салат": "--cover-sage", "Десерт": "--cover-plum",
    "Выпечка": "--cover-plum", "Закуска": "--cover-sand", "Напиток": "--cover-berry"
  };
  const CUISINE_ICON = {
    "Итальянская": "🍝", "Русская": "🥟", "Грузинская": "🫓", "Японская": "🍣",
    "Тайская": "🌶", "Китайская": "🥢", "Мексиканская": "🌮", "Индийская": "🍛",
    "Французская": "🥐", "Корейская": "🍚", "Марокканская": "🍲", "Ближневосточная": "🧆",
    "Турецкая": "🥙", "Греческая": "🫒", "Испанская": "🥘", "Вьетнамская": "🍜",
    "Узбекская": "🍲", "Американская": "🍔"
  };
  const SHOP_ORDER = ["Овощи", "Мясо", "Молочное", "Бакалея", "Специи", "Заморозка", "Прочее"];

  /* ---------- localStorage ---------- */
  const LS = {
    get(k, def) { try { const v = localStorage.getItem(k); return v == null ? def : JSON.parse(v); } catch (e) { return def; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }
  };
  const Store = {
    shopping: LS.get("cb_shopping", { recipes: {}, manual: [], checked: {} }),
    pantry:   LS.get("cb_pantry", { items: {} }),
    memory:   LS.get("cb_memory", {}),
    userRecipes: LS.get("cb_userRecipes", LS.get("cb_user_recipes", [])), // читаем правильный ключ; миграция со старого cb_user_recipes
    plan:     LS.get("cb_plan", {}),
    ingChecks: LS.get("cb_ingChecks", {}),
    profile:  LS.get("cb_profile", { excludeAllergens: [], diet: "" }),
    planServings: LS.get("cb_planServings", {}),
    goals:    LS.get("cb_goals", { kcal: 0, protein: 0, fat: 0, carbs: 0 }),
    eaten:    LS.get("cb_eaten", {}),
    collections: LS.get("cb_collections", {}),
    child:    LS.get("cb_child", { name: "", age: "", dislikes: [], allergies: [] }),
    save(key) { LS.set("cb_" + key, Store[key]); if (window.CookSync) window.CookSync.push(key); },
    // перезапись значения без побочек (для будущего синка: не триггерит push повторно)
    set(key, val) { Store[key] = val; LS.set("cb_" + key, val); }
  };

  /* ---------- Доступ к данным ---------- */
  function allRecipes() { return (window.RECIPES || []).concat(Store.userRecipes || []); }
  // Гейт логина перед AI-действиями вне экрана ассистента: вместо глухого тоста — окно входа + повтор действия
  function guardAuth(action) {
    if (window.CookAssistant && !window.CookAssistant.isAuthed()) { window.CookAssistant.promptLogin(() => action()); return; }
    action();
  }
  function getRecipe(id) { return allRecipes().find(r => r.id === id); }

  /* ---------- Утилиты ---------- */
  function $(sel, root) { return (root || document).querySelector(sel); }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
  function cssVar(v) { return getComputedStyle(document.documentElement).getPropertyValue(v).trim() || "#E2D4BE"; }

  const FRACTIONS = [[0.125, "⅛"], [0.25, "¼"], [0.333, "⅓"], [0.5, "½"], [0.666, "⅔"], [0.75, "¾"]];
  function fmtNum(n) {
    if (n == null) return "";
    const whole = Math.floor(n), frac = n - whole;
    let best = null, bestD = 0.06;
    for (const [v, s] of FRACTIONS) { const d = Math.abs(frac - v); if (d < bestD) { bestD = d; best = s; } }
    if (best) return (whole ? whole + " " : "") + best;
    if (Math.abs(frac) < 0.06) return String(whole);
    return String(Math.round(n * 10) / 10).replace(".", ",");
  }
  function scaleQty(qty, servings, base) {
    if (qty == null) return null;
    return qty * (servings || base) / (base || 1);
  }
  function fmtQtyUnit(qty, unit, servings, base) {
    if (qty == null) return unit || "";
    const v = scaleQty(qty, servings, base);
    return fmtNum(v) + (unit ? " " + unit : "");
  }

  let toastTimer = null;
  function toast(msg) {
    let t = $("#toast"); if (t) t.remove();
    t = document.createElement("div"); t.id = "toast"; t.className = "toast"; t.textContent = msg;
    document.body.appendChild(t);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.remove(), 2200);
  }

  function shopCount() {
    const s = Store.shopping;
    return Object.keys(s.recipes || {}).length + (s.manual || []).length;
  }
  function updateBadge() {
    const b = $("#shopBadge"), n = shopCount();
    if (!b) return;
    if (n > 0) { b.textContent = n; b.classList.remove("hidden"); } else b.classList.add("hidden");
  }

  /* ---------- Обложки ---------- */
  function coverVar(r) {
    return CUISINE_COLOR[r.cuisine] || CAT_COLOR[r.category] || "--cover-sand";
  }
  function coverStyle(r) {
    return r.photo ? "" : `background:var(${coverVar(r)});`;
  }
  function cardHtml(r, extra) {
    const mem = Store.memory[r.id];
    const made = mem && mem.madeLog && mem.madeLog.length;
    const cover = r.photo
      ? `<div class="cover photo"><img src="${esc(r.photo)}" alt="" loading="lazy">
           <div class="cover-cap">
             <div class="c-cat">${esc(r.category)}</div>
             <div class="c-title">${esc(r.title)}</div>
           </div>
         </div>`
      : `<div class="cover" style="${coverStyle(r)}">
           <div class="c-cat">${esc(r.category)}</div>
           <div class="c-title">${esc(r.title)}</div>
         </div>`;
    return `<a class="card" href="#/recipe/${esc(r.id)}">
      ${cover}
      <div class="card-meta">
        <span>${r.time} мин</span>
        ${r.kcal ? `<span>🔥 ${r.kcal}</span>` : ""}
        ${r.forKid ? '<span class="kid">★ дочке</span>' : ""}
        ${made ? '<span title="готовил">✓</span>' : ""}
      </div>
      ${extra || ""}
    </a>`;
  }

  // «Подать с…» — дополняющие блюда из нашей базы (клиентский подбор, $0, офлайн)
  const SERVE_PAIRS = {
    "Основное": ["Гарнир", "Салат", "Суп"],
    "Гарнир": ["Основное", "Салат"],
    "Суп": ["Выпечка", "Салат"],
    "Салат": ["Основное", "Суп"],
    "Закуска": ["Основное", "Суп"],
    "Выпечка": ["Напиток"],
    "Десерт": ["Напиток"],
    "Напиток": ["Выпечка", "Десерт"],
    "Завтрак": ["Напиток", "Выпечка"],
  };
  function serveWithSuggestions(r, limit) {
    limit = limit || 3;
    const wantCats = SERVE_PAIRS[r.category] || ["Напиток"];
    const pool = allRecipes().filter(x => x.id !== r.id && wantCats.includes(x.category) && (x.difficulty || 1) <= 2 && profileAllows(x)); // гардрейл: не предлагать исключённое диетой/аллергенами
    const rank = (x) => {
      const mem = Store.memory[x.id] || {};
      let s = x.cuisine === r.cuisine ? 3 : 0;      // та же кухня — выше
      if (mem.vote === 1) s += 2;
      if (mem.madeLog && mem.madeLog.length) s += 1;
      s += Math.max(0, 2 - ((x.difficulty || 1) - 1)); // проще — выше
      return s;
    };
    const sorted = pool.slice().sort((a, b) => rank(b) - rank(a) || a.time - b.time);
    const out = [], usedCat = new Set();
    for (const x of sorted) { if (out.length >= limit) break; if (usedCat.has(x.category)) continue; usedCat.add(x.category); out.push(x); }
    for (const x of sorted) { if (out.length >= limit) break; if (!out.includes(x)) out.push(x); }
    return out;
  }
  function serveSuggestCardHtml(x) {
    const bg = x.photo ? `background-image:url('${esc(x.photo)}')` : coverStyle(x);
    return `<a class="serve-card" href="#/recipe/${esc(x.id)}">
      <div class="sc-cover" style="${bg}"></div>
      <div class="sc-cat">${esc(x.category)} · ${x.time} мин</div>
      <div class="sc-title">${esc(x.title)}</div>
    </a>`;
  }
  function serveSuggestBlockHtml(r) {
    const sug = serveWithSuggestions(r);
    if (!sug.length) return "";
    return `<div class="label" style="margin-top:14px">Хорошо дополнит</div>
      <div class="serve-row">${sug.map(serveSuggestCardHtml).join("")}</div>`;
  }

  /* ---------- Личная память ---------- */
  function getMem(id) {
    return Store.memory[id] || (Store.memory[id] = { vote: 0, madeLog: [], notes: "", kidRating: 0, substitutions: [] });
  }
  function saveMem() { Store.save("memory"); }

  /* ---------- Рекомендации (content-based) ---------- */
  function recommend(limit) {
    const recipes = allRecipes();
    const now = Date.now();
    // профиль вкуса из голосов с тайм-decay
    const weights = {}; // признак -> вес
    const tried = new Set();
    const recentMade = new Set();
    function bump(key, w) { weights[key] = (weights[key] || 0) + w; }
    for (const r of recipes) {
      const m = Store.memory[r.id]; if (!m) continue;
      if (m.vote) tried.add(r.id);
      if (m.madeLog && m.madeLog.length) {
        const last = new Date(m.madeLog[m.madeLog.length - 1]).getTime();
        if (now - last < 12 * 864e5) recentMade.add(r.id); // готовил < 12 дней
      }
      if (m.vote) {
        // свежие голоса весомее (по позиции в madeLog нет даты голоса — простой decay по голосу)
        const sign = m.vote;
        bump("cuisine:" + r.cuisine, sign);
        bump("category:" + r.category, sign);
        if (r.forKid) bump("forKid", sign);
        (r.tags || []).forEach(t => bump("tag:" + t, sign * 0.6));
        keyIngredients(r).forEach(i => bump("ing:" + i, sign * 0.4));
      }
    }
    const hasProfile = Object.keys(weights).length > 0;
    // Холодный старт без оценок → курированная, стабильная и разнообразная подборка
    if (!hasProfile) return curatedStarters(limit || 6, recentMade);
    const scored = recipes.filter(r => !tried.has(r.id) && !recentMade.has(r.id)).map(r => {
      let s = 0;
      s += weights["cuisine:" + r.cuisine] || 0;
      s += weights["category:" + r.category] || 0;
      if (r.forKid) s += weights["forKid"] || 0;
      (r.tags || []).forEach(t => s += weights["tag:" + t] || 0);
      keyIngredients(r).forEach(i => s += weights["ing:" + i] || 0);
      return { r, s };
    }).filter(x => x.s > 0).sort((a, b) => b.s - a.s);
    return scored.slice(0, limit || 6).map(x => x.r);
  }
  function hasTasteProfile() {
    return Object.values(Store.memory || {}).some(m => m && m.vote);
  }
  // Курированный холодный старт: детское → быстрое → простое, по одному на кухню (разнообразие), стабильно (без random)
  function curatedStarters(limit, recentMade) {
    recentMade = recentMade || new Set();
    const ranked = allRecipes()
      .filter(r => !recentMade.has(r.id))
      .map(r => ({
        r,
        s: (r.forKid ? 3 : 0) + (r.time <= 20 ? 2 : r.time <= 35 ? 1 : 0) + (3 - (r.difficulty || 2)) * 0.5
      }))
      .sort((a, b) => b.s - a.s || a.r.time - b.r.time || a.r.title.localeCompare(b.r.title));
    const out = [], seen = new Set();
    for (const { r } of ranked) { if (out.length >= limit) break; if (seen.has(r.cuisine)) continue; seen.add(r.cuisine); out.push(r); }
    for (const { r } of ranked) { if (out.length >= limit) break; if (!out.includes(r)) out.push(r); }
    return out;
  }
  function keyIngredients(r) {
    return (r.ingredients || []).filter(i => !i.staple).slice(0, 4).map(i => normName(i.name));
  }
  function normName(n) { return String(n).toLowerCase().trim().replace(/ё/g, "е"); }

  /* ---------- Аллергены / диеты / кладовка ---------- */
  // Свёртка мусорных вариантов в канон (регистр/ё уже чистит normName)
  const ALLERGEN_CANON = {
    "молочное": "молоко", "молочные продукты": "молоко", "лактоза": "молоко",
    "яйцо": "яйца", "арахис": "орехи",
    "ракообразные": "морепродукты", "моллюски": "морепродукты"
  };
  function canonAllergen(a) { const n = normName(a); return ALLERGEN_CANON[n] || n; }
  function recipeAllergens(r) { return new Set((r.allergens || []).map(canonAllergen)); }
  // Гардрейл: AI-вариант не должен вносить исключённый профилем аллерген. Проверяем и заявленные allergens, и названия ингредиентов
  const ALLERGEN_INGR = {
    "глютен": ["пшен", "мук", "хлеб", "макарон", "манк", "булгур", "сухар", "панир", "овсян", "ячмен", "рож", "отруб"],
    "молоко": ["молок", "сливк", "сливочн", "сметан", "творог", "сыр", "йогурт", "кефир", "ряженк"],
    "яйца": ["яйц", "яиц", "меланж"],
    "орехи": ["орех", "миндал", "фундук", "кешью", "фисташк", "арахис", "пекан", "грецк", "макадам"],
    "рыба": ["рыб", "лосос", "треск", "тунец", "форел", "сельд", "минтай", "икра"],
    "соя": ["соя", "соев", "тофу", "эдамам", "мисо"],
    "морепродукты": ["креветк", "краб", "кальмар", "мидии", "устриц", "морепрод", "гребешок"],
  };
  function draftAllergenConflict(draft) {
    const excl = (Store.profile.excludeAllergens || []).map(canonAllergen);
    if (!excl.length) return [];
    const declared = new Set((draft.allergens || []).map(canonAllergen));
    const names = (draft.ingredients || []).map(i => normName(typeof i === "string" ? i : (i.name || ""))).join(" | ");
    const hit = new Set();
    for (const a of excl) {
      if (declared.has(a)) { hit.add(a); continue; }
      if ((ALLERGEN_INGR[a] || []).some(k => names.includes(k))) hit.add(a);
    }
    return [...hit];
  }
  function tagsHave(r, sub) { return (r.tags || []).some(t => normName(t).includes(sub)); }
  function recipeMatchesDiet(r, diet) {
    if (diet === "веганское") return tagsHave(r, "веган") || tagsHave(r, "постн");
    if (diet === "вегетарианское") return tagsHave(r, "вегетар") || tagsHave(r, "веган") || tagsHave(r, "постн");
    if (diet === "постное") return tagsHave(r, "постн") || tagsHave(r, "веган");
    if (diet === "безглютена") return tagsHave(r, "без глютена") || !recipeAllergens(r).has("глютен");
    return true;
  }
  // Постоянный профиль питания фильтрует и список, и рекомендации
  function profileAllows(r) {
    const p = Store.profile;
    if (p.excludeAllergens && p.excludeAllergens.length) {
      const ra = recipeAllergens(r);
      if (p.excludeAllergens.some(a => ra.has(a))) return false;
    }
    return !p.diet || recipeMatchesDiet(r, p.diet);
  }
  // Ребёнок не ест / аллергия — блокирует рецепт в детском фильтре
  function childBlocks(r) {
    const c = Store.child || {};
    const ingNames = (r.ingredients || []).map(i => normName(i.name)).join(" ");
    if ((c.dislikes || []).some(d => d && ingNames.includes(normName(d)))) return true;
    const ra = recipeAllergens(r);
    if ((c.allergies || []).some(a => ra.has(canonAllergen(a)) || ingNames.includes(normName(a)))) return true;
    return false;
  }
  // Совпадение с кладовкой по НЕ-staple ингредиентам (staple считаем «всегда есть»)
  function pantryMatch(r) {
    const key = (r.ingredients || []).filter(i => !i.staple);
    const missing = key.filter(i => !Store.pantry.items[normName(i.name)]).map(i => i.name);
    return { total: key.length, have: key.length - missing.length, missing };
  }
  function pantryBadge(m) {
    if (!m.total) return "";
    const miss = m.missing.length ? `<div class="pc-missing">не хватает: ${m.missing.map(esc).join(", ")}</div>` : "";
    return `<div class="pc-badge">есть ${m.have} из ${m.total} ключевых${m.missing.length === 0 ? " ✓" : ""}</div>${miss}`;
  }

  /* ============================================================
     ВЬЮХА: Список (#/)
     ============================================================ */
  let listState = { q: "", cuisine: "", category: "", kidOnly: false, time: "", difficulty: "", simple: false, fewIngr: false, pantryCook: false, noOven: false };
  function nonStapleCount(r) { return (r.ingredients || []).filter(i => !i.staple).length; }
  function recipeNeedsOven(r) { return (r.equipment || []).some(e => normName(e).includes("духов")); }
  const DIFF_LABEL = ["", "просто", "средне", "сложно"];

  /* ============================================================
     ВЬЮХА: Что сегодня? (#/today) — экран-решение «5pm»
     ============================================================ */
  let todayShown = new Set();
  // Профиль ребёнка задан, если есть имя или списки не-любит/аллергий
  function childProfileSet() { const c = Store.child || {}; return !!(c.name || (c.dislikes || []).length || (c.allergies || []).length); }
  function pickTonight() {
    let ranked = recommend(80).filter(r => profileAllows(r) && !todayShown.has(r.id));
    if (!ranked.length) { todayShown = new Set(); ranked = recommend(80).filter(profileAllows); }
    if (!ranked.length) return null;
    const dinner = MEAL_CATS["Ужин"];
    const kidOn = childProfileSet();
    const scored = ranked.map(r => {
      const m = pantryMatch(r);
      const kidOk = !kidOn || !childBlocks(r);
      // «что поедят ВСЕ»: сильный приоритет ужинам, что подойдут и ребёнку
      const s = (dinner.includes(r.category) ? 3 : 0) + Math.max(0, 4 - m.missing.length) + (r.time <= 40 ? 1 : 0) + (kidOn && kidOk ? 3 : 0);
      return { r, m, s, kidOk };
    }).sort((a, b) => b.s - a.s);
    const pick = scored[0];
    if (pick) todayShown.add(pick.r.id);
    return pick;
  }
  function todayWhy(pick) {
    const m = pick.m;
    const kidLine = (childProfileSet() && pick.kidOk) ? ` · подойдёт и ${esc((Store.child && Store.child.name) || "ребёнку")}` : "";
    if (!m.total) return "Просто и без лишних покупок" + kidLine;
    if (!m.missing.length) return "🏠 Всё есть — готовь прямо сейчас" + kidLine;
    if (m.missing.length <= 2) return "Почти всё есть, купить: " + m.missing.map(esc).join(", ") + kidLine;
    return (hasTasteProfile() ? "Под ваши вкусы" : "Хороший вариант на вечер") + kidLine;
  }
  function renderToday() {
    const view = $("#view");
    const pick = pickTonight();
    if (!pick) { view.innerHTML = `<div class="empty">Пока нечего предложить.<br><a href="#/" style="color:var(--accent)">К каталогу</a></div>`; return; }
    const r = pick.r, sv = r.baseServings;
    view.innerHTML = `
      <div class="section-head" style="margin-top:4px"><h1>🍽 Сегодня</h1></div>
      <a class="card today-card-big" href="#/recipe/${esc(r.id)}">
        ${r.photo ? `<div class="cover photo"><img src="${esc(r.photo)}" alt="" loading="lazy"><div class="cover-cap"><div class="c-cat">${esc(r.cuisine)} · ${esc(r.category)}</div><div class="c-title">${esc(r.title)}</div></div></div>`
          : `<div class="cover" style="${coverStyle(r)}"><div class="c-cat">${esc(r.cuisine)} · ${esc(r.category)}</div><div class="c-title">${esc(r.title)}</div></div>`}
        <div class="card-meta"><span>⏱ ${r.time} мин</span>${r.kcal ? `<span>🔥 ${r.kcal}</span>` : ""}${r.forKid ? '<span class="kid">★ дочке</span>' : ""}</div>
      </a>
      <div class="today-why">${todayWhy(pick)}</div>
      <div class="btn-row" style="margin:14px 0">
        <a class="btn primary" href="#/cook/${esc(r.id)}">🍳 Готовить</a>
        <button class="btn" id="todayShop">🛒 В список</button>
      </div>
      <div class="btn-row">
        <button class="btn ghost" id="todayLike">👍 Нравится</button>
        <button class="btn ghost" id="todayNope">👎 Другое</button>
        <button class="btn" id="todayMore">🔄 Ещё вариант</button>
      </div>
    `;
    $("#todayShop").onclick = () => { addRecipeToShopping(r.id, sv); updateBadge(); toast("В списке покупок"); };
    $("#todayMore").onclick = () => renderToday();
    $("#todayLike").onclick = () => { const m = getMem(r.id); m.vote = 1; saveMem(); toast("Запомнил — буду предлагать похожее"); renderToday(); };
    $("#todayNope").onclick = () => renderToday(); // «не сегодня» ≠ дизлайк: просто другой вариант (pickTonight исключит показанный). Явный минус — только 👎 в карточке рецепта
  }

  function renderList() {
    const recipes = allRecipes();
    const cuisines = [...new Set(recipes.map(r => r.cuisine))].sort();
    const categories = [...new Set(recipes.map(r => r.category))];

    const catChips = `<button class="chip ${!listState.category ? "active" : ""}" data-cat="">Все</button>` +
      categories.map(c => `<button class="chip ${listState.category === c ? "active" : ""}" data-cat="${esc(c)}">${esc(c)}</button>`).join("");
    const fcount = filterCount();

    const view = $("#view");
    view.innerHTML = `
      <a class="today-hero" href="#/today">🍽 Что приготовить сегодня?<span>один тап — готовый ответ</span></a>
      <div class="search">
        <span>🔎</span>
        <input id="q" type="text" placeholder="Поиск: название, тег, ингредиент…" value="${esc(listState.q)}">
      </div>
      <div class="active-filters" id="activeFilters">${activeFilterChips()}</div>
      <div class="chips wrap">${catChips}</div>
      <div class="toolbar">
        <button class="btn ghost sm" id="openFilters">⚙ Фильтры${fcount ? ` · ${fcount}` : ""}</button>
        <button class="chip accent ${listState.kidOnly ? "active" : ""}" id="kidChip">★ Дочке</button>
        <button class="chip accent ${listState.simple ? "active" : ""}" id="simpleChip">⚡ Просто и быстро${listState.simple ? ` · ${currentMeal().toLowerCase()}` : ""}</button>
        <button class="chip accent ${listState.pantryCook ? "active" : ""}" id="pantryCookChip">🏠 Из кладовки</button>
        <button class="btn ghost sm" id="surprise">🎲 Удиви меня</button>
      </div>
      <div id="listResults"></div>
    `;
    renderResults(recipes);

    $("#q").addEventListener("input", e => { listState.q = e.target.value; debouncedResults(); });
    $("#kidChip").addEventListener("click", () => { listState.kidOnly = !listState.kidOnly; renderList(); });
    $("#simpleChip").addEventListener("click", () => { listState.simple = !listState.simple; renderList(); });
    $("#pantryCookChip").addEventListener("click", () => { listState.pantryCook = !listState.pantryCook; renderList(); });
    $("#surprise").addEventListener("click", () => {
      const pool = applyFilters(recipes); if (!pool.length) return;
      location.hash = "#/recipe/" + pool[Math.floor(Math.random() * pool.length)].id;
    });
    $("#openFilters").addEventListener("click", () => openFilterSheet(recipes, cuisines));
    view.querySelectorAll("[data-cat]").forEach(b => b.addEventListener("click", () => {
      const c = b.dataset.cat;
      listState.category = (c && listState.category === c) ? "" : c; // повторный тап по активной категории снимает фильтр
      renderList();
    }));
    view.querySelectorAll("#activeFilters [data-clear]").forEach(b => b.addEventListener("click", () => {
      const k = b.dataset.clear; listState[k] = (k === "kidOnly" || k === "fewIngr" || k === "simple" || k === "noOven") ? false : ""; renderList();
    }));
  }

  function filterCount() {
    return (listState.cuisine ? 1 : 0) + (listState.time ? 1 : 0) + (listState.difficulty ? 1 : 0) + (listState.fewIngr ? 1 : 0) + (listState.noOven ? 1 : 0);
  }
  // Активные фильтры из листа «Фильтры» → съёмные чипы под поиском
  function activeFilterChips() {
    const chips = [];
    if (listState.cuisine) chips.push(["cuisine", listState.cuisine]);
    if (listState.time) chips.push(["time", "≤ " + listState.time + " мин"]);
    if (listState.difficulty) chips.push(["difficulty", DIFF_LABEL[listState.difficulty] || ""]);
    if (listState.fewIngr) chips.push(["fewIngr", "≤ 5 покупных"]);
    if (listState.noOven) chips.push(["noOven", "без духовки"]);
    return chips.map(([k, label]) => `<button class="afilter" data-clear="${k}">${esc(label)} ✕</button>`).join("");
  }

  // Лист «Фильтры»: все кухни сеткой (+ поиск по кухне), время, сложность
  function openFilterSheet(recipes, cuisines) {
    const html = `
      <div class="filter-group">
        <div class="label">Профиль (исключить аллергены)</div>
        <div class="chips wrap" id="allergenGrid">
          ${["глютен", "молоко", "яйца", "орехи", "рыба", "морепродукты", "соя"].map(a =>
            `<button class="chip ${Store.profile.excludeAllergens.includes(a) ? "active" : ""}" data-al="${a}">${a}</button>`).join("")}
        </div>
        <div class="label" style="margin-top:10px">Диета</div>
        <div class="chips wrap" id="dietGrid">
          ${[["", "Любая"], ["вегетарианское", "Вегетар."], ["веганское", "Веган"], ["постное", "Постное"], ["безглютена", "Без глютена"]]
            .map(([v, l]) => `<button class="chip ${Store.profile.diet === v ? "active" : ""}" data-diet="${v}">${l}</button>`).join("")}
        </div>
        <button class="btn ghost sm" id="childBtn" style="margin-top:10px">👶 Профиль ребёнка${Store.child && Store.child.name ? " · " + esc(Store.child.name) : ""}</button>
      </div>
      <div class="filter-group">
        <div class="label">Кухня</div>
        <input id="cuisineSearch" class="mini-search" placeholder="Найти кухню…">
        <div class="chips wrap" id="cuisineGrid">
          ${cuisines.map(c => `<button class="chip ${listState.cuisine === c ? "active" : ""}" data-fc="${esc(c)}">${esc(c)}</button>`).join("")}
        </div>
      </div>
      <div class="filter-group">
        <div class="label">Время</div>
        <div class="chips" id="timeGrid">${[15, 30, 60].map(t => `<button class="chip ${listState.time == t ? "active" : ""}" data-ft="${t}">≤ ${t} мин</button>`).join("")}</div>
      </div>
      <div class="filter-group">
        <div class="label">Сложность</div>
        <div class="chips" id="diffGrid">${[1, 2, 3].map(d => `<button class="chip ${listState.difficulty == d ? "active" : ""}" data-fd="${d}">${DIFF_LABEL[d]}</button>`).join("")}</div>
      </div>
      <div class="filter-group">
        <div class="label">Ингредиенты</div>
        <div class="chips" id="ingrGrid"><button class="chip ${listState.fewIngr ? "active" : ""}" id="fewIngrChip">≤ 5 покупных</button></div>
      </div>
      <div class="filter-group">
        <div class="label">Оборудование</div>
        <div class="chips" id="equipGrid"><button class="chip ${listState.noOven ? "active" : ""}" id="noOvenChip">🚫🔥 Без духовки</button></div>
      </div>
      <div class="sheet-actions">
        <button class="btn ghost" id="fReset">Сбросить</button>
        <button class="btn primary" id="fApply"></button>
      </div>`;
    const ov = openSheet("Фильтры", html);
    const root = ov.querySelector(".sheet");
    const updateCount = () => { $("#fApply").textContent = "Показать " + applyFilters(recipes).length; };
    const single = (grid, attr, key) => grid.querySelectorAll("[" + attr + "]").forEach(b => b.addEventListener("click", () => {
      const v = b.getAttribute(attr);
      listState[key] = (String(listState[key]) === v) ? "" : v;
      grid.querySelectorAll("[" + attr + "]").forEach(x => x.classList.toggle("active", String(listState[key]) === x.getAttribute(attr)));
      updateCount();
    }));
    single(root.querySelector("#cuisineGrid"), "data-fc", "cuisine");
    single(root.querySelector("#timeGrid"), "data-ft", "time");
    single(root.querySelector("#diffGrid"), "data-fd", "difficulty");
    // Профиль питания сохраняется сразу (не зависит от Apply/Reset)
    root.querySelector("#allergenGrid").querySelectorAll("[data-al]").forEach(b => b.onclick = () => {
      const a = b.dataset.al, arr = Store.profile.excludeAllergens, i = arr.indexOf(a);
      if (i >= 0) arr.splice(i, 1); else arr.push(a);
      Store.save("profile"); b.classList.toggle("active"); updateCount();
    });
    root.querySelector("#dietGrid").querySelectorAll("[data-diet]").forEach(b => b.onclick = () => {
      Store.profile.diet = b.dataset.diet; Store.save("profile");
      root.querySelectorAll("#dietGrid [data-diet]").forEach(x => x.classList.toggle("active", x.dataset.diet === Store.profile.diet));
      updateCount();
    });
    root.querySelector("#childBtn").onclick = () => openChildSheet();
    root.querySelector("#fewIngrChip").addEventListener("click", (e) => {
      listState.fewIngr = !listState.fewIngr;
      e.target.classList.toggle("active", listState.fewIngr);
      updateCount();
    });
    root.querySelector("#noOvenChip").addEventListener("click", (e) => {
      listState.noOven = !listState.noOven;
      e.target.classList.toggle("active", listState.noOven);
      updateCount();
    });
    $("#cuisineSearch").addEventListener("input", e => {
      const q = normName(e.target.value);
      root.querySelectorAll("#cuisineGrid [data-fc]").forEach(b => {
        b.style.display = (!q || normName(b.getAttribute("data-fc")).includes(q)) ? "" : "none";
      });
    });
    $("#fReset").onclick = () => { listState.cuisine = ""; listState.time = ""; listState.difficulty = ""; listState.fewIngr = false; listState.noOven = false; closeSheet(); renderList(); };
    $("#fApply").onclick = () => { closeSheet(); renderList(); };
    updateCount();
  }
  // Перерисовываем ТОЛЬКО результаты — поле поиска и чипы не трогаем (фокус не теряется)
  const LIST_PAGE = 48; // карточек за «страницу» бесконечного скролла
  let listShown = LIST_PAGE;
  let listObserver = null;
  function renderResults(recipes) {
    recipes = recipes || allRecipes();
    const el = $("#listResults");
    if (!el) return;
    const filtered = applyFilters(recipes);
    const anyFilter = listState.q || listState.cuisine || listState.category || listState.kidOnly || listState.time || listState.difficulty || listState.simple || listState.fewIngr || listState.pantryCook || listState.noOven;
    const recs = anyFilter ? [] : recommend(6).filter(profileAllows);
    const recsHead = hasTasteProfile() ? "Вам понравится" : "С чего начать";
    listShown = LIST_PAGE; // сброс при каждой смене фильтров/поиска
    // Режим «Из кладовки»: сортировка по нехватке + бейдж на карточке
    let decorate = (r) => cardHtml(r);  // обёртка: .map передаёт индекс 2-м арг — не пускаем его в extra
    if (listState.pantryCook) {
      filtered.sort((a, b) => { const ma = pantryMatch(a), mb = pantryMatch(b); return ma.missing.length - mb.missing.length || mb.have - ma.have || a.time - b.time; });
      decorate = (r) => cardHtml(r, pantryBadge(pantryMatch(r)));
    } else if (listState.simple) {
      // Мягкая привязка ко времени суток: горячее блюдо под трапезу вверх, салаты ниже
      const pref = MEAL_PREF[currentMeal()];
      filtered.sort((a, b) => simpleRank(a, pref) - simpleRank(b, pref) || a.time - b.time);
    }
    const pantryEmptyHint = (listState.pantryCook && !Object.keys(Store.pantry.items || {}).length)
      ? `<div class="empty" style="margin-bottom:12px">Кладовка пуста — отмечайте 🏠 на позициях в списке покупок.</div>` : "";
    el.innerHTML = `
      ${recs.length ? `
        <div class="section-head"><h2>${recsHead}</h2></div>
        <div class="grid">${recs.map(r => cardHtml(r)).join("")}</div>` : ""}
      ${pantryEmptyHint}
      <div class="section-head"><h2>Рецепты</h2><span class="muted">${filtered.length}</span></div>
      ${filtered.length ? `<div class="grid" id="listGrid">${filtered.slice(0, listShown).map(decorate).join("")}</div><div id="listSentinel" style="height:1px"></div>`
        : `<div class="empty">Ничего не найдено.<br>Сбросьте фильтры или <a href="#/add" style="color:var(--accent)">добавьте рецепт</a>.</div>`}
    `;
    setupInfiniteScroll(filtered, decorate);
  }
  // Догружаем карточки порциями по мере прокрутки — иначе 4600 <img> рендерятся разом
  function setupInfiniteScroll(filtered, decorate) {
    decorate = decorate || cardHtml;
    if (listObserver) { listObserver.disconnect(); listObserver = null; }
    const sentinel = document.getElementById("listSentinel");
    const grid = document.getElementById("listGrid");
    if (!sentinel || !grid || filtered.length <= listShown) return;
    listObserver = new IntersectionObserver((entries) => {
      if (!entries[0].isIntersecting) return;
      const next = filtered.slice(listShown, listShown + LIST_PAGE);
      grid.insertAdjacentHTML("beforeend", next.map(decorate).join(""));
      listShown += next.length;
      if (listShown >= filtered.length) { listObserver.disconnect(); listObserver = null; }
    }, { rootMargin: "800px" });
    listObserver.observe(sentinel);
  }
  let listDebTimer = null;
  function debouncedResults() { clearTimeout(listDebTimer); listDebTimer = setTimeout(() => renderResults(), 180); }

  // «⚡ Просто и быстро» — это «дай приготовлю что-то поесть», а не напиток/десерт/нарезку
  const SIMPLE_EXCLUDE = new Set(["Напиток", "Десерт", "Закуска"]);
  // Приоритет категорий по времени суток (мягкая сортировка — горячее выше салатов в обед/ужин)
  const MEAL_PREF = {
    "Завтрак": ["Завтрак", "Выпечка", "Основное", "Гарнир", "Суп", "Салат"],
    "Обед":    ["Суп", "Основное", "Гарнир", "Салат", "Завтрак", "Выпечка"],
    "Ужин":    ["Основное", "Гарнир", "Суп", "Салат", "Завтрак", "Выпечка"],
  };
  function currentMeal() { const h = new Date().getHours(); return h < 11 ? "Завтрак" : h < 16 ? "Обед" : "Ужин"; }
  function simpleRank(r, pref) { const i = pref.indexOf(r.category); return i < 0 ? pref.length : i; }

  function applyFilters(recipes) {
    const q = normName(listState.q);
    return recipes.filter(r => {
      if (!profileAllows(r)) return false;
      if (listState.kidOnly && (!r.forKid || childBlocks(r))) return false;
      if (listState.cuisine && r.cuisine !== listState.cuisine) return false;
      if (listState.category && r.category !== listState.category) return false;
      if (listState.time && r.time > +listState.time) return false;
      if (listState.difficulty && r.difficulty !== +listState.difficulty) return false;
      if (listState.simple && !(r.difficulty <= 1 && r.time <= 30)) return false;
      if (listState.simple && SIMPLE_EXCLUDE.has(r.category)) return false;
      if (listState.fewIngr && nonStapleCount(r) > 5) return false;
      if (listState.noOven && recipeNeedsOven(r)) return false;
      if (listState.pantryCook && pantryMatch(r).missing.length > 2) return false;
      if (q) {
        const hay = [r.title, ...(r.tags || []), ...(r.ingredients || []).map(i => i.name)].map(normName).join(" ");
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }

  /* ============================================================
     ВЬЮХА: Избранное / Готовил (#/saved)
     ============================================================ */
  function renderSaved() {
    const all = allRecipes();
    const withMem = all.filter(r => Store.memory[r.id]);
    const cooked = withMem
      .filter(r => (Store.memory[r.id].madeLog || []).length)
      .sort((a, b) => new Date(Store.memory[b.id].madeLog.at(-1)) - new Date(Store.memory[a.id].madeLog.at(-1)));
    const liked = withMem.filter(r => Store.memory[r.id].vote === 1);
    const kid = withMem
      .filter(r => (Store.memory[r.id].kidRating || 0) > 0)
      .sort((a, b) => (Store.memory[b.id].kidRating || 0) - (Store.memory[a.id].kidRating || 0));

    const section = (title, sub, list) => list.length
      ? `<div class="section-head"><h2>${title}</h2><span class="muted">${list.length}</span></div>
         ${sub ? `<div class="muted" style="margin:-6px 0 10px">${sub}</div>` : ""}
         <div class="grid">${list.map(r => cardHtml(r)).join("")}</div>`
      : "";

    // Свои коллекции — сверху
    const cols = Object.entries(Store.collections || {}).filter(([, ids]) => (ids || []).length);
    const colSections = cols.map(([n, ids]) => {
      const list = ids.map(getRecipe).filter(Boolean);
      return `<div class="section-head"><h2>📁 ${esc(n)}</h2><span class="muted">${list.length}</span><button class="btn ghost sm" data-delcol="${esc(n)}" style="margin-left:auto">Удалить</button></div>
        <div class="grid">${list.map(r => cardHtml(r)).join("")}</div>`;
    }).join("");

    const favBody = section("Готовил", "Отмеченное «✓ Готовил» — от свежего к старому", cooked)
      + section("Понравилось", "Отмеченное 👍", liked)
      + section("Алисе зашло", "По звёздам, от высоких к низким", kid);
    const body = (colSections || favBody) ? (colSections + favBody)
      : `<div class="empty">Пока пусто.<br>Открой рецепт: отметь «✓ Готовил», 👍, звёзды «Алисе зашло» или собери свою коллекцию (📁).</div>`;

    $("#view").innerHTML = `<div class="section-head" style="margin-top:4px"><h1>Избранное</h1></div>${body}`;
    $("#view").querySelectorAll("[data-delcol]").forEach(b => b.onclick = () => {
      if (confirm("Удалить коллекцию «" + b.dataset.delcol + "»? Рецепты останутся в базе.")) { delete Store.collections[b.dataset.delcol]; Store.save("collections"); renderSaved(); }
    });
  }

  /* ============================================================
     ВЬЮХА: Карточка рецепта (#/recipe/:id)
     ============================================================ */
  const recipeServings = {}; // id -> текущее кол-во порций (сессия)

  function renderRecipe(id) {
    const r = getRecipe(id);
    const view = $("#view");
    if (!r) { view.innerHTML = `<div class="empty">Рецепт не найден. <a href="#/" style="color:var(--accent)">К списку</a></div>`; return; }
    if (!recipeServings[id]) recipeServings[id] = r.baseServings;
    const sv = recipeServings[id];
    const mem = getMem(id);

    const hero = r.photo
      ? `<div class="recipe-hero photo"><img src="${esc(r.photo)}" alt=""></div>`
      : `<div class="recipe-hero" style="background:var(${coverVar(r)});">
           <div class="r-cat">${esc(r.cuisine)} · ${esc(r.category)}</div>
           <h1>${esc(r.title)}</h1>
         </div>`;

    view.innerHTML = `
      <a href="#/" class="btn ghost sm" style="margin-bottom:12px">← Назад</a>
      ${hero}
      ${r.photo ? `<div class="r-cat" style="margin:4px 0 6px">${esc(r.cuisine)} · ${esc(r.category)}</div><h1 style="font-size:28px;margin-bottom:10px">${esc(r.title)}</h1>` : ""}
      <div class="r-meta">
        <span>⏱ <b>${r.time}</b> мин</span>
        ${(r.prepTime != null && r.cookTime != null) ? `<span>🔪 ${r.prepTime} + 🍳 ${r.cookTime} мин</span>` : ""}
        <span>📊 сложность <b>${DIFF_LABEL[r.difficulty] || "просто"}</b></span>
        ${r.kcal ? `<span>🔥 <b>${r.kcal}</b> ккал</span>` : ""}
        ${(r.protein != null && r.fat != null && r.carbs != null) ? `<span>Б <b>${r.protein}</b> · Ж <b>${r.fat}</b> · У <b>${r.carbs}</b> г</span>` : ""}
        ${r.forKid ? '<span class="kid" style="color:var(--accent);font-weight:700">★ для дочки</span>' : ""}
      </div>
      ${r.allergens && r.allergens.length ? `<div class="allergen-badges">${[...recipeAllergens(r)].map(a => `<span class="al-badge">${esc(a)}</span>`).join("")}</div>` : ""}
      ${r.forKid && r.kidNote ? `<div class="kid-note">👶 ${esc(r.kidNote)}</div>` : ""}

      <div class="servings">
        <span class="label">Порции</span>
        <div class="stepper">
          <button id="svMinus">−</button><span id="svVal">${sv}</span><button id="svPlus">+</button>
        </div>
      </div>

      <div class="label">Ингредиенты</div>
      <ul class="ingredients" id="ings">
        ${r.ingredients.map((ing, i) => ingredientRow(r, ing, i, sv)).join("")}
      </ul>

      <div class="btn-row" style="margin:18px 0">
        <a class="btn primary" href="#/cook/${esc(r.id)}">🍳 Готовить</a>
        <button class="btn" id="toShop">🛒 В список покупок</button>
        <button class="btn" id="shareBtn">📤 Поделиться</button>
      </div>
      <button class="btn" id="askAssistant" style="width:100%;margin:-6px 0 4px">✦ Спросить ассистента о рецепте</button>
      <button class="btn" id="personalizeBtn" style="width:100%;margin:4px 0">✨ Персонализировать (детская / веган / полезнее…)</button>
      <button class="btn" id="collectBtn" style="width:100%;margin:0 0 4px">📁 В коллекцию</button>

      <div class="label" style="margin-top:8px">Метод</div>
      <ol class="steps">
        ${r.steps.map(s => `<li>${s.title ? `<div class="step-title">${esc(s.title)}</div>` : ""}<div class="step-text">${esc(s.text)}${s.timer ? `<br><span class="timer-chip">⏱ ${fmtTimer(s.timer)}</span>` : ""}</div></li>`).join("")}
      </ol>

      ${r.serveWith ? `<div class="label" style="margin-top:14px">С чем подавать</div><p class="serve-note">${esc(r.serveWith)}</p>` : ""}
      ${serveSuggestBlockHtml(r)}
      ${r.notes ? `<div class="label" style="margin-top:14px">Совет</div><p class="serve-note">${esc(r.notes)}</p>` : ""}

      ${memoryBlock(r, mem)}
    `;

    $("#svMinus").onclick = () => changeServings(id, -1);
    $("#svPlus").onclick = () => changeServings(id, +1);
    $("#toShop").onclick = () => { addRecipeToShopping(id, recipeServings[id]); toast("Добавлено в список"); updateBadge(); };
    $("#askAssistant").onclick = () => { if (window.CookAssistant) window.CookAssistant.openOverlay({ recipe: r }); };
    $("#shareBtn").onclick = () => shareRecipe(r);
    $("#personalizeBtn").onclick = () => openPersonalizeSheet(r);
    $("#collectBtn").onclick = () => openCollectionSheet(r.id);
    bindIngredientRows(r);
    bindMemory(r);
  }

  function ingredientRow(r, ing, i, sv) {
    const checked = ingChecked(r.id, i);
    return `<li class="${checked ? "checked" : ""}" data-i="${i}">
      <button class="ing-check" data-check="${i}">${checked ? "✓" : ""}</button>
      <span class="ing-name">${esc(ing.name)}</span>
      <span class="ing-qty">${fmtQtyUnit(ing.qty, ing.unit, sv, r.baseServings)}</span>
      <button class="ing-ask" data-ask="${i}" title="Спросить ассистента">✦</button>
    </li>`;
  }
  function ingChecked(id, i) { return !!Store.ingChecks[id + ":" + i]; }
  function bindIngredientRows(r) {
    $("#ings").querySelectorAll("[data-check]").forEach(b => b.onclick = () => {
      const key = r.id + ":" + b.dataset.check;
      if (Store.ingChecks[key]) delete Store.ingChecks[key]; else Store.ingChecks[key] = true;
      Store.save("ingChecks");
      b.closest("li").classList.toggle("checked"); b.textContent = Store.ingChecks[key] ? "✓" : "";
    });
    $("#ings").querySelectorAll("[data-ask]").forEach(b => b.onclick = () => {
      const ing = r.ingredients[b.dataset.ask];
      if (window.CookAssistant) window.CookAssistant.openOverlay({ recipe: r, ingredient: ing });
    });
  }
  function changeServings(id, d) {
    const r = getRecipe(id);
    recipeServings[id] = Math.max(1, Math.min(20, recipeServings[id] + d));
    $("#svVal").textContent = recipeServings[id];
    const ul = $("#ings");
    r.ingredients.forEach((ing, i) => {
      const cell = ul.querySelector(`li[data-i="${i}"] .ing-qty`);
      if (cell) cell.textContent = fmtQtyUnit(ing.qty, ing.unit, recipeServings[id], r.baseServings);
    });
  }

  function memoryBlock(r, mem) {
    const made = mem.madeLog || [];
    const lastMade = made.length ? new Date(made[made.length - 1]).toLocaleDateString("ru-RU") : null;
    return `<div class="memory">
      <div class="label">Личное</div>
      <div class="vote-row">
        <button class="vote up ${mem.vote === 1 ? "on" : ""}" data-vote="1">👍</button>
        <button class="vote down ${mem.vote === -1 ? "on" : ""}" data-vote="-1">👎</button>
        <button class="btn sm" id="madeBtn" style="margin-left:auto">✓ Готовил сегодня</button>
      </div>
      <div class="made-log">${made.length ? `Готовил ${made.length} раз. Последний раз: ${lastMade}.` : "Ещё не отмечал, что готовил."}</div>
      <button class="btn sm ghost" id="eatBtn" style="margin-top:8px">🍽 Съел сегодня (в дневник)</button>
      <div style="margin-top:14px"><span class="label">Алисе зашло</span>
        <div class="stars" id="kidStars">${[1, 2, 3, 4, 5].map(n => `<span class="star" data-star="${n}">${n <= (mem.kidRating || 0) ? "★" : "☆"}</span>`).join("")}</div>
      </div>
      <div style="margin-top:14px"><span class="label">Заметки и правки</span>
        <textarea id="memNotes" placeholder="Личные правки, замены, что поменять…">${esc(mem.notes || "")}</textarea>
      </div>
      ${(mem.substitutions || []).length ? `<div class="made-log" style="margin-top:10px"><b>Замены:</b><br>${mem.substitutions.map(s => `${esc(s.original)} → ${esc(s.replacement)}${s.note ? " (" + esc(s.note) + ")" : ""}`).join("<br>")}</div>` : ""}
    </div>`;
  }
  function bindMemory(r) {
    const mem = getMem(r.id);
    $("#view").querySelectorAll("[data-vote]").forEach(b => b.onclick = () => {
      const v = parseInt(b.dataset.vote, 10);
      mem.vote = mem.vote === v ? 0 : v; saveMem(); renderRecipe(r.id);
    });
    $("#madeBtn").onclick = () => { mem.madeLog = mem.madeLog || []; mem.madeLog.push(new Date().toISOString()); saveMem(); toast("Отмечено: готовил"); renderRecipe(r.id); };
    $("#eatBtn").onclick = () => eatToday(r.id);
    $("#kidStars").querySelectorAll("[data-star]").forEach(s => s.onclick = () => {
      const n = parseInt(s.dataset.star, 10);
      mem.kidRating = (mem.kidRating === n) ? 0 : n; // повторный тап по той же звезде снимает оценку
      saveMem(); renderRecipe(r.id);
    });
    $("#memNotes").addEventListener("change", e => { mem.notes = e.target.value.slice(0, 2000); saveMem(); toast("Заметка сохранена"); });
  }

  /* ============================================================
     Список покупок (#/shopping)
     ============================================================ */
  function addRecipeToShopping(id, servings) {
    Store.shopping.recipes[id] = servings || getRecipe(id).baseServings;
    Store.save("shopping");
  }
  function aggregateShopping() {
    const map = {}; // `${name}|${unit}` -> {name, unit, qty, group, fromStaple}
    for (const [id, sv] of Object.entries(Store.shopping.recipes)) {
      const r = getRecipe(id); if (!r) continue;
      for (const ing of r.ingredients) {
        const key = normName(ing.name) + "|" + (ing.unit || "");
        if (!map[key]) map[key] = { name: ing.name, unit: ing.unit, qty: null, group: ing.group || "Прочее", staple: ing.staple };
        const scaled = scaleQty(ing.qty, sv, r.baseServings);
        if (scaled != null) map[key].qty = (map[key].qty || 0) + scaled;
      }
    }
    // ручные позиции
    (Store.shopping.manual || []).forEach((m, i) => {
      map["manual:" + i] = { name: m.name, unit: m.unit || "", qty: m.qty, group: m.group || "Прочее", staple: false, manualIndex: i };
    });
    // вычесть кладовку
    const pantry = Store.pantry.items || {};
    const items = Object.entries(map).filter(([key, it]) => {
      if (it.staple && pantry["staple"]) return false;
      if (pantry[normName(it.name)]) return false;
      return true;
    }).map(([key, it]) => ({ key, ...it }));
    // группировка
    const groups = {};
    items.forEach(it => { (groups[it.group] = groups[it.group] || []).push(it); });
    return groups;
  }

  function renderShopping() {
    const groups = aggregateShopping();
    const order = SHOP_ORDER.filter(g => groups[g]).concat(Object.keys(groups).filter(g => !SHOP_ORDER.includes(g)));
    const recipeChips = Object.keys(Store.shopping.recipes).map(id => {
      const r = getRecipe(id); if (!r) return "";
      return `<button class="chip active" data-rm="${esc(id)}">${esc(r.title)} ✕</button>`;
    }).join("");

    const view = $("#view");
    view.innerHTML = `
      <div class="section-head"><h2>Список покупок</h2></div>
      ${recipeChips ? `<div class="chips wrap">${recipeChips}</div>` : ""}
      ${order.length ? order.map(g => `
        <div class="shop-group">
          <h3>${esc(g)}</h3>
          ${groups[g].map(it => {
            const done = !!Store.shopping.checked[it.key];
            return `<div class="shop-item ${done ? "done" : ""}" data-key="${esc(it.key)}">
              <button class="ing-check" data-toggle="${esc(it.key)}">${done ? "✓" : ""}</button>
              <span class="si-name">${esc(it.name)}</span>
              <span class="si-qty">${it.qty != null ? fmtNum(it.qty) + (it.unit ? " " + it.unit : "") : (it.unit || "")}</span>
              ${it.manualIndex != null ? `<button class="ing-ask" data-delman="${it.manualIndex}">✕</button>` : `<button class="ing-ask" data-pantry="${esc(it.name)}" title="Есть дома (в кладовку)">🏠</button>`}
            </div>`;
          }).join("")}
        </div>`).join("")
        : `<div class="empty">Список пуст.<br>Добавьте ингредиенты из рецептов кнопкой «🛒 В список».</div>`}

      <div class="btn-row" style="margin-top:18px">
        <button class="btn" id="addManual">＋ Своя позиция</button>
        <button class="btn" id="copyShop">📋 Скопировать</button>
        ${order.length ? `<button class="btn ghost" id="clearShop">Очистить</button>` : ""}
      </div>
      ${pantryBlock()}
    `;

    view.querySelectorAll("[data-rm]").forEach(b => b.onclick = () => { delete Store.shopping.recipes[b.dataset.rm]; Store.save("shopping"); updateBadge(); renderShopping(); });
    view.querySelectorAll("[data-toggle]").forEach(b => b.onclick = () => { const k = b.dataset.toggle; Store.shopping.checked[k] = !Store.shopping.checked[k]; Store.save("shopping"); b.closest(".shop-item").classList.toggle("done"); b.textContent = Store.shopping.checked[k] ? "✓" : ""; });
    view.querySelectorAll("[data-pantry]").forEach(b => b.onclick = () => { addToPantry(b.dataset.pantry); Store.save("pantry"); toast("В кладовку: " + b.dataset.pantry); renderShopping(); });
    view.querySelectorAll("[data-delman]").forEach(b => b.onclick = () => { Store.shopping.manual.splice(parseInt(b.dataset.delman, 10), 1); Store.save("shopping"); renderShopping(); });
    $("#addManual").onclick = addManualPrompt;
    $("#copyShop").onclick = copyShopping;
    const cl = $("#clearShop"); if (cl) cl.onclick = () => { if (confirm("Очистить весь список?")) { Store.shopping = { recipes: {}, manual: [], checked: {} }; Store.save("shopping"); updateBadge(); renderShopping(); } };
    bindPantry();
  }

  function daysLeft(dateStr) { if (!dateStr) return null; const d = new Date(dateStr + "T00:00:00"); const t = new Date(); t.setHours(0, 0, 0, 0); return Math.round((d - t) / 86400000); }
  function expiryBadge(name) {
    const dl = daysLeft((Store.pantry.expiry || {})[name]);
    if (dl == null) return "";
    if (dl < 0) return ` <span class="exp-badge exp-bad">просроч.</span>`;
    if (dl === 0) return ` <span class="exp-badge exp-soon">сегодня</span>`;
    if (dl <= 3) return ` <span class="exp-badge exp-soon">${dl}д</span>`;
    return ` <span class="exp-badge">${dl}д</span>`;
  }
  function pantryBlock() {
    const items = Object.keys(Store.pantry.items || {}).filter(k => Store.pantry.items[k]);
    const expiring = items.filter(n => { const dl = daysLeft((Store.pantry.expiry || {})[n]); return dl != null && dl <= 3; });
    return `<div class="memory" style="margin-top:22px">
      <div class="label">🏠 Кладовка (есть дома — не попадает в список)</div>
      ${expiring.length ? `<div class="expire-soon">⏳ <b>Успей съесть:</b> ${expiring.map(esc).join(", ")}<button class="btn sm" id="pantryUseUp" style="margin-top:8px">✨ Придумай из них</button></div>` : ""}
      ${items.length ? `<div class="chips" style="flex-wrap:wrap;padding-top:10px">${items.map(n => `<span class="chip active pantry-chip" data-exp="${esc(n)}">${esc(n)}${expiryBadge(n)}<b class="p-x" data-unpantry="${esc(n)}">✕</b></span>`).join("")}</div><div class="muted" style="font-size:12px;margin-top:6px">Тап по продукту — поставить срок годности.</div>` : `<div class="made-log">Пусто. Отмечайте 🏠 на позициях, что уже есть дома.</div>`}
      <div class="dyn-row" style="margin-top:10px"><input id="pantryAdd" placeholder="Добавить в кладовку (соль, масло…)"><button class="btn sm" id="pantryAddBtn">＋</button></div>
      <label class="btn block" style="margin-top:8px">📷 Сфоткать продукты (можно несколько кадров)<input id="pantryScan" type="file" accept="image/*" capture="environment" multiple class="hidden"></label>
      ${items.length ? `<button class="btn block" id="pantryGen" style="margin-top:8px">✨ Придумай блюдо из кладовки</button>` : ""}
    </div>`;
  }
  function setExpiry(name) {
    const cur = (Store.pantry.expiry || {})[name];
    const v = prompt("Через сколько дней истекает срок «" + name + "»? (0 — сегодня, пусто — убрать)", cur != null ? String(daysLeft(cur)) : "");
    if (v === null) return;
    Store.pantry.expiry = Store.pantry.expiry || {};
    if (v.trim() === "") { delete Store.pantry.expiry[name]; }
    else { const days = parseInt(v, 10) || 0; const d = new Date(); d.setDate(d.getDate() + days); Store.pantry.expiry[name] = d.toISOString().slice(0, 10); }
    Store.save("pantry"); renderShopping();
  }
  function bindPantry() {
    $("#view").querySelectorAll("[data-unpantry]").forEach(b => b.onclick = (e) => { e.stopPropagation(); const n = b.dataset.unpantry; delete Store.pantry.items[n]; if (Store.pantry.expiry) delete Store.pantry.expiry[n]; Store.save("pantry"); renderShopping(); });
    $("#view").querySelectorAll("[data-exp]").forEach(b => b.onclick = () => setExpiry(b.dataset.exp));
    const useUp = $("#pantryUseUp");
    if (useUp) useUp.onclick = () => guardAuth(async () => {
      if (!window.CookAssistant) { toast("Ассистент недоступен"); return; }
      const items = Object.keys(Store.pantry.items || {}).filter(k => Store.pantry.items[k] && (() => { const dl = daysLeft((Store.pantry.expiry || {})[k]); return dl != null && dl <= 3; })());
      if (!items.length) return;
      toast("Придумываю из портящегося… (10–20 сек)");
      try { startDraft(await window.CookAssistant.generateRecipe({ ingredients: items, diet: Store.profile.diet || "", allergens: Store.profile.excludeAllergens || [] })); }
      catch (e) { toast(e.message || "Не получилось"); }
    });
    const add = () => { const v = $("#pantryAdd").value.trim(); if (v) { addToPantry(v); Store.save("pantry"); renderShopping(); } };
    $("#pantryAddBtn").onclick = add;
    $("#pantryAdd").addEventListener("keydown", e => { if (e.key === "Enter") add(); });
    const gen = $("#pantryGen");
    if (gen) gen.onclick = () => guardAuth(async () => {
      if (!window.CookAssistant) { toast("Ассистент недоступен"); return; }
      const ingredients = Object.keys(Store.pantry.items || {}).filter(k => Store.pantry.items[k]);
      if (!ingredients.length) return;
      toast("Придумываю рецепт… (10–20 сек)");
      try { startDraft(await window.CookAssistant.generateRecipe({ ingredients, diet: Store.profile.diet || "", allergens: Store.profile.excludeAllergens || [] })); }
      catch (e) { toast(e.message || "Не получилось"); }
    });
    const scan = $("#pantryScan");
    if (scan) scan.onchange = () => guardAuth(async () => {
      let files = Array.from(scan.files || []); if (!files.length || !window.CookAssistant) return;
      const SCAN_MAX = 5;
      if (files.length > SCAN_MAX) { toast(`За раз обрабатываю ${SCAN_MAX} кадров`); files = files.slice(0, SCAN_MAX); }
      const seen = new Set(), merged = [];
      try {
        for (let i = 0; i < files.length; i++) {
          toast(files.length > 1 ? `Распознаю фото ${i + 1} из ${files.length}…` : "Распознаю продукты… (5–15 сек)");
          const names = await window.CookAssistant.scanFridge(files[i]);
          for (const n of (names || [])) { const k = normName(n); if (!seen.has(k)) { seen.add(k); merged.push(n); } }
        }
      } catch (e) { toast(e.message || "Не получилось"); }
      scan.value = "";
      if (merged.length) openScanResultSheet(merged); else toast("Ничего не распознал — попробуйте ближе/светлее");
    });
  }
  // Авто-срок годности по типу продукта (клиентский, $0)
  const SHELF_LIFE = { молочка: 4, мясо: 2, рыба: 2, овощи: 7, фрукты: 7, зелень: 4, хлеб: 3, яйца: 21, бакалея: 180, заморозка: 90, прочее: 7 };
  // keyword'ы уже нормализованы (без ё) — classifyFood нормализует и имя (normName: ё→е, lower)
  const FOOD_KEYWORDS = [
    ["молочка", ["молок", "кефир", "сметан", "творог", "сыр", "йогурт", "сливк", "сливочн", "ряженк", "масло сливоч"]],
    ["мясо", ["мясо", "курин", "куриц", "фарш", "говядин", "свинин", "индейк", "колбас", "сосиск", "бекон", "ветчин"]],
    ["рыба", ["рыб", "лосос", "форел", "селедк", "креветк", "кальмар", "тунец", "икра", "морепрод"]],
    ["зелень", ["укроп", "петрушк", "кинз", "базилик", "руккол", "шпинат", "зелень", "лук зелен", "зелен лук"]],
    ["овощи", ["помидор", "огурец", "огурц", "перец", "капуст", "морков", "картоф", "картош", "кабач", "баклаж", "лук", "чеснок", "свекл", "тыкв", "грибы", "брокколи", "цветн"]],
    ["фрукты", ["яблок", "банан", "апельсин", "груш", "виноград", "ягод", "клубник", "малин", "лимон", "мандарин", "киви", "персик", "слив", "абрикос", "авокадо"]],
    ["хлеб", ["хлеб", "батон", "булк", "лаваш", "багет", "выпечк", "тортил"]],
    ["яйца", ["яйц", "яйк"]],
    ["заморозка", ["заморож", "мороженн", "пельмен", "вареник", "наггетс"]],
    ["бакалея", ["крупа", "рис", "гречк", "макарон", "паста", "мука", "сахар", "соль", "консерв", "тушенк", "фасол", "чечевиц", "горох", "масло растит", "уксус", "специ", "чай", "кофе", "мед", "орех", "сухофрукт"]],
  ];
  function classifyFood(name) {
    const n = normName(name);
    // молотый/чёрный/душистый перец и т.п. — специя (бакалея), не свежий овощ
    if (n.includes("перец") && /(черн|молот|горош|душист|паприк|чили|красн)/.test(n)) return "бакалея";
    for (const [cat, kws] of FOOD_KEYWORDS) { if (kws.some(k => n.includes(k))) return cat; }
    return "прочее";
  }
  function todayPlusDays(days) { const d = new Date(); d.setDate(d.getDate() + days); return d.toISOString().slice(0, 10); }
  // Единая точка добавления в кладовку: ставит дефолтный срок по категории, не перетирая ручной
  function addToPantry(name) {
    const n = normName(name);
    Store.pantry.items[n] = true;
    Store.pantry.expiry = Store.pantry.expiry || {};
    if (Store.pantry.expiry[n] == null) Store.pantry.expiry[n] = todayPlusDays(SHELF_LIFE[classifyFood(name)] || 7);
  }
  // Результат fridge-scan: чипы продуктов (toggle) → добавить выбранные в кладовку
  function openScanResultSheet(items) {
    const picked = new Set(items);
    openSheet("📷 Распознано", `
      <p class="muted" style="margin-bottom:10px">Отметьте, что добавить в кладовку.</p>
      <div class="chips wrap" id="scanChips">${items.map(n => `<button class="chip active" data-scan="${esc(n)}">${esc(n)}</button>`).join("")}</div>
      <button class="btn primary block" id="scanAdd" style="margin-top:14px">Добавить в кладовку</button>
    `);
    document.querySelectorAll("#scanChips [data-scan]").forEach(b => b.onclick = () => {
      const n = b.dataset.scan;
      if (picked.has(n)) { picked.delete(n); b.classList.remove("active"); } else { picked.add(n); b.classList.add("active"); }
    });
    $("#scanAdd").onclick = () => {
      picked.forEach(addToPantry);
      Store.save("pantry"); closeSheet(); renderShopping(); toast("Добавлено в кладовку: " + picked.size);
    };
  }
  function addManualPrompt() {
    const name = prompt("Что добавить?"); if (!name) return;
    const qty = prompt("Количество (можно пусто):", "");
    Store.shopping.manual.push({ name: name.trim(), qty: qty ? parseFloat(qty.replace(",", ".")) || null : null, unit: "", group: "Прочее" });
    Store.save("shopping"); updateBadge(); renderShopping();
  }
  function copyShopping() {
    const groups = aggregateShopping();
    let text = "Список покупок\n";
    Object.entries(groups).forEach(([g, items]) => {
      text += "\n" + g + ":\n";
      items.forEach(it => { if (!Store.shopping.checked[it.key]) text += "— " + it.name + (it.qty != null ? " " + fmtNum(it.qty) + (it.unit ? " " + it.unit : "") : "") + "\n"; });
    });
    copyText(text.trim());
  }
  // Рецепт → текст для шаринга/копирования
  function recipeToText(r) {
    const ings = r.ingredients.map(i => "— " + i.name + (i.qty != null ? " " + fmtNum(i.qty) + (i.unit ? " " + i.unit : "") : "")).join("\n");
    const steps = r.steps.map((s, i) => (i + 1) + ". " + (s.title ? s.title + ": " : "") + s.text).join("\n");
    return `${r.title} (${r.cuisine} · ${r.category})\n\nИнгредиенты:\n${ings}\n\nМетод:\n${steps}` + (r.serveWith ? `\n\nС чем подавать: ${r.serveWith}` : "");
  }
  function shareRecipe(r) {
    const text = recipeToText(r);
    if (navigator.share) navigator.share({ title: r.title, text }).catch(() => {});
    else copyText(text);
  }
  // AI-персонализация рецепта: выбор режима → эндпоинт → editable draft
  function openPersonalizeSheet(r) {
    if (!window.CookAssistant) { toast("Ассистент недоступен"); return; }
    openSheet("✨ Персонализировать", `
      <p class="muted" style="margin-bottom:12px">AI перепишет рецепт под запрос — откроется черновик для проверки и сохранения.</p>
      <div class="chips wrap">
        <button class="chip" data-pmode="kid">👶 Детская версия</button>
        <button class="chip" data-pmode="hide_veg">🥕 Спрячь овощи</button>
        <button class="chip" data-pmode="vegan">🌱 Веган</button>
        <button class="chip" data-pmode="healthy">🥗 Полезнее</button>
        <button class="chip" data-pmode="no_allergen">🚫 Без аллергена…</button>
        <button class="chip" data-pmode="scale">🔢 Другое число порций…</button>
      </div>
    `);
    document.querySelectorAll("[data-pmode]").forEach(b => b.onclick = () => guardAuth(async () => {
      const mode = b.dataset.pmode;
      let arg = "";
      if (mode === "no_allergen") { arg = (prompt("Какой аллерген убрать? (глютен / молоко / яйца / орехи / рыба / соя)") || "").trim(); if (!arg) return; }
      if (mode === "scale") { arg = (prompt("На сколько порций пересчитать?", String(r.baseServings || 2)) || "").trim(); if (!arg) return; }
      closeSheet(); toast("Готовлю вариант… (10–20 сек)");
      try { startDraft(await window.CookAssistant.personalizeRecipe(r, mode, arg)); }
      catch (e) { toast(e.message || "Не получилось"); }
    }));
  }
  // Добавить рецепт в свои коллекции/папки (toggle) + создать новую
  function openCollectionSheet(id) {
    const names = Object.keys(Store.collections);
    const chips = names.map(n => {
      const inCol = (Store.collections[n] || []).includes(id);
      return `<button class="chip ${inCol ? "active" : ""}" data-col="${esc(n)}">${esc(n)}${inCol ? " ✓" : ""}</button>`;
    }).join("");
    openSheet("📁 В коллекцию", `
      <p class="muted" style="margin-bottom:10px">Добавьте рецепт в свои подборки — они появятся в «Избранном».</p>
      <div class="chips wrap" id="colChips">${chips || '<span class="muted">Пока нет коллекций.</span>'}</div>
      <div class="dyn-row" style="margin-top:12px"><input id="colNew" placeholder="Новая коллекция (напр. Праздник)"><button class="btn sm" id="colAdd">＋</button></div>
    `);
    document.querySelectorAll("#colChips [data-col]").forEach(b => b.onclick = () => {
      const n = b.dataset.col, arr = Store.collections[n] || (Store.collections[n] = []);
      const i = arr.indexOf(id);
      if (i >= 0) arr.splice(i, 1); else arr.push(id);
      Store.save("collections"); toast(i >= 0 ? "Убрано" : "Добавлено"); openCollectionSheet(id);
    });
    $("#colAdd").onclick = () => {
      const n = ($("#colNew").value || "").trim(); if (!n) return;
      if (!Store.collections[n]) Store.collections[n] = [];
      if (!Store.collections[n].includes(id)) Store.collections[n].push(id);
      Store.save("collections"); toast("Добавлено в «" + n + "»"); openCollectionSheet(id);
    };
  }
  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(() => toast("Скопировано"), () => fallbackCopy(text));
    else fallbackCopy(text);
  }
  function fallbackCopy(text) {
    const ta = document.createElement("textarea"); ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0"; document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); toast("Скопировано"); } catch (e) { toast("Не удалось скопировать"); }
    ta.remove();
  }

  /* ============================================================
     Кукинг-мод (#/cook/:id)
     ============================================================ */
  let cookState = null;
  let _visBound = false;
  function fmtTimer(sec) { const m = Math.floor(sec / 60), s = sec % 60; return s ? `${m}:${String(s).padStart(2, "0")}` : `${m} мин`; }

  function renderCook(id) {
    const r = getRecipe(id);
    if (!r) { location.hash = "#/"; return; }
    cookState = { r, idx: 0, timers: {} };
    requestWakeLock();
    drawCook();
  }
  function drawCook() {
    const { r, idx } = cookState;
    const sv = recipeServings[r.id] || r.baseServings;
    const serve = r.serveWith || r.notes || "";
    const hasServe = !!serve;
    const total = r.steps.length + (hasServe ? 1 : 0);
    const onServe = hasServe && idx === r.steps.length;
    const view = $("#view");
    view.innerHTML = `<div class="cook" id="cookRoot">
      <div class="cook-top">
        <span class="cook-progress">${onServe ? "Подача" : `Шаг ${idx + 1} из ${total}`}</span>
        <span class="cook-serv"><button id="cookSvMinus">−</button>${sv} порц<button id="cookSvPlus">+</button></span>
        ${voiceSupported() ? `<button class="iconbtn ${voiceOn ? "on" : ""}" id="cookMic" title="Голосовое управление">🎤</button>` : ""}
        <button class="iconbtn" id="cookAsk" title="Спросить ассистента">✦</button>
        <button class="iconbtn" id="cookIngs" title="Ингредиенты">📋</button>
        <button class="iconbtn" id="cookExit" title="Выйти">✕</button>
      </div>
      <div class="cook-body" id="cookBody">
        ${onServe ? cookServeHtml(serve, true) : cookStepHtml(r.steps[idx], idx, idx, r, sv)}
      </div>
      <div class="cook-nav">
        <button class="btn ghost" id="cookPrev" ${idx === 0 ? "disabled" : ""}>← Назад</button>
        ${idx < total - 1
          ? `<button class="btn primary" id="cookNext">Дальше →</button>`
          : `<button class="btn primary" id="cookDone">✓ Готово</button>`}
      </div>
    </div>`;

    $("#cookExit").onclick = () => { releaseWakeLock(); clearCookTimers(); location.hash = "#/recipe/" + r.id; };
    const mic = $("#cookMic"); if (mic) mic.onclick = () => { if (voiceOn) stopVoice(); else startVoice(); drawCook(); };
    $("#cookAsk").onclick = () => {
      if (!window.CookAssistant) return;
      const step = onServe ? null : { idx, title: r.steps[idx].title || "", text: r.steps[idx].text || "" };
      window.CookAssistant.openOverlay({ recipe: r, step });
    };
    $("#cookSvMinus").onclick = () => cookServings(-1);
    $("#cookSvPlus").onclick = () => cookServings(+1);
    $("#cookIngs").onclick = () => openIngredientsSheet(r, sv);
    const prev = $("#cookPrev"); if (prev) prev.onclick = () => { if (cookState.idx > 0) { cookState.idx--; drawCook(); } };
    const next = $("#cookNext"); if (next) next.onclick = () => { if (cookState.idx < total - 1) { cookState.idx++; drawCook(); } };
    const done = $("#cookDone"); if (done) done.onclick = () => {
      const mem = getMem(r.id); mem.madeLog = mem.madeLog || []; mem.madeLog.push(new Date().toISOString()); saveMem();
      releaseWakeLock(); clearCookTimers(); toast("Готово! Отмечено, что готовил."); location.hash = "#/recipe/" + r.id;
    };
    bindCookTimers(); bindCookIngTaps(r, sv); bindCookSwipe(total);
  }
  // Смена порций прямо в кукинг-моде (общая session-карта с деталью/покупками)
  function cookServings(d) {
    const r = cookState.r;
    recipeServings[r.id] = Math.max(1, Math.min(20, (recipeServings[r.id] || r.baseServings) + d));
    drawCook();
  }
  // --- Голосовое управление кукинг-модом (Web Speech API, $0) ---
  let cookRecog = null, voiceOn = false;
  function voiceSupported() { return !!(window.SpeechRecognition || window.webkitSpeechRecognition); }
  function cookTotal() { const r = cookState.r; return r.steps.length + ((r.serveWith || r.notes) ? 1 : 0); }
  function cookNextStep() { if (cookState && cookState.idx < cookTotal() - 1) { cookState.idx++; drawCook(); } }
  function cookPrevStep() { if (cookState && cookState.idx > 0) { cookState.idx--; drawCook(); } }
  function handleVoice(t) {
    if (/дальше|следующ|вперёд|вперед|next/.test(t)) cookNextStep();
    else if (/назад|предыдущ|обратно|back/.test(t)) cookPrevStep();
    else if (/таймер|время|засеки/.test(t)) { const b = document.querySelector(".cook-timer"); if (b) b.click(); }
    else if (/ингредиент|состав|продукт/.test(t)) openIngredientsSheet(cookState.r, recipeServings[cookState.r.id] || cookState.r.baseServings);
    else if (/стоп|выход|закрой|хватит|заверши/.test(t)) { stopVoice(); location.hash = "#/recipe/" + cookState.r.id; }
  }
  function startVoice() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { toast("Голос не поддерживается браузером"); return; }
    stopVoice();
    cookRecog = new SR();
    cookRecog.lang = "ru-RU"; cookRecog.continuous = true; cookRecog.interimResults = false;
    cookRecog.onresult = (e) => handleVoice((e.results[e.results.length - 1][0].transcript || "").toLowerCase());
    cookRecog.onerror = () => {};
    cookRecog.onend = () => { if (voiceOn && cookRecog) { try { cookRecog.start(); } catch (e) {} } };
    voiceOn = true;
    try { cookRecog.start(); toast("🎤 Голос: «дальше», «назад», «таймер», «ингредиенты», «стоп»"); } catch (e) {}
  }
  function stopVoice() { voiceOn = false; if (cookRecog) { try { cookRecog.onend = null; cookRecog.stop(); } catch (e) {} cookRecog = null; } }
  function cookStepHtml(s, i, idx, r, sv) {
    const cls = i === idx ? "current" : "dim";
    const title = s.title ? `<div class="cook-step-title">${esc(s.title)}</div>` : "";
    const text = linkifyIngredients(s.text, r);
    const timers = parseTimers(s);
    const timerBtns = (i === idx && timers.length) ? timers.map((t, ti) => `<button class="cook-timer" data-timer="${t.sec}" data-tid="${i}_${ti}" data-label="${esc(t.label || "")}">⏱ ${fmtTimer(t.sec)}${t.label ? " · " + esc(t.label) : ""}</button>`).join(" ") : "";
    return `<div class="cook-step ${cls}">${title}<div class="cook-step-text">${text}</div>${timerBtns ? "<div>" + timerBtns + "</div>" : ""}</div>`;
  }
  function cookServeHtml(serve, isCurrent) {
    return `<div class="cook-step cook-serve ${isCurrent ? "current" : "dim"}">
      <div class="cook-step-title">С чем подавать</div>
      <div class="cook-step-text">${esc(serve)}</div>
    </div>`;
  }
  // Свайп влево/вправо = следующий/предыдущий шаг
  function bindCookSwipe(total) {
    const body = $("#cookBody");
    let x0 = null, y0 = null;
    body.addEventListener("touchstart", e => { x0 = e.changedTouches[0].clientX; y0 = e.changedTouches[0].clientY; }, { passive: true });
    body.addEventListener("touchend", e => {
      if (x0 == null) return;
      const dx = e.changedTouches[0].clientX - x0, dy = e.changedTouches[0].clientY - y0;
      x0 = null;
      if (Math.abs(dx) < 50 || Math.abs(dx) < Math.abs(dy)) return; // горизонтальный жест
      if (dx < 0 && cookState.idx < total - 1) { cookState.idx++; drawCook(); }
      else if (dx > 0 && cookState.idx > 0) { cookState.idx--; drawCook(); }
    }, { passive: true });
  }
  // Линкуем названия ингредиентов в тексте шага для тапа
  function linkifyIngredients(text, r) {
    const safe = esc(text);
    const names = [...new Set((r.ingredients || []).map(i => i.name).filter(Boolean))].sort((a, b) => b.length - a.length);
    if (!names.length) return safe;
    const alt = names.map(n => esc(n).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|");
    // Единый проход с глобальной заменой: все вхождения, границы слова (Unicode),
    // без перекрытия HTML (replace идёт по исходной строке, не входя в вставленные span).
    let re;
    try { re = new RegExp("(?<![\\p{L}\\p{N}])(" + alt + ")(?![\\p{L}\\p{N}])", "giu"); }
    catch (e) { re = new RegExp("(" + alt + ")", "gi"); } // fallback: старые движки без lookbehind
    return safe.replace(re, m => `<span class="ing-tap" data-ing="${m}">${m}</span>`);
  }
  function bindCookIngTaps(r, sv) {
    $("#cookBody").querySelectorAll(".ing-tap").forEach(el => el.onclick = () => {
      const tapped = (el.dataset.ing || "").toLowerCase();
      const ing = r.ingredients.find(i => i.name.toLowerCase() === tapped);
      if (ing) toast(ing.name + ": " + fmtQtyUnit(ing.qty, ing.unit, sv, r.baseServings));
    });
  }
  // Парсинг таймеров: явный step.timer + «N минут/мин/сек» из текста
  function parseTimers(s) {
    const res = [];
    if (s.timer) res.push({ sec: s.timer, label: "" });
    const re = /(\d+)\s*(минут\w*|мин|сек\w*|час\w*|ч)\b/gi;
    let m;
    while ((m = re.exec(s.text))) {
      const n = parseInt(m[1], 10); const u = m[2].toLowerCase();
      let sec = u.startsWith("сек") ? n : u.startsWith("ч") || u.startsWith("час") ? n * 3600 : n * 60;
      if (!res.some(t => t.sec === sec)) res.push({ sec, label: "" });
    }
    return res;
  }
  // Таймеры на абсолютном времени (endAt), а не на счётчике: переживают сворачивание
  // вкладки/блокировку экрана (setInterval в фоне тормозится — обратный отсчёт бы дрейфовал).
  // Единый тикер (не привязан к кнопке) переживает навигацию по шагам и шлёт уведомление
  // о финише, даже если открыт другой шаг.
  function timerRemaining(t) { return Math.max(0, Math.round((t.endAt - Date.now()) / 1000)); }
  function ensureNotifyPermission() {
    try { if ("Notification" in window && Notification.permission === "default") Notification.requestPermission(); } catch (e) {}
  }
  function notifyTimer(t) {
    try { if ("Notification" in window && Notification.permission === "granted")
      new Notification("Таймер готов", { body: fmtTimer(t.total) + (t.label ? " · " + t.label : ""), tag: "cook-timer" }); } catch (e) {}
  }
  function startTicker() {
    if (!cookState || cookState.ticker) return;
    if (!_visBound) { _visBound = true; document.addEventListener("visibilitychange", () => { if (!document.hidden) tickAllTimers(); }); }
    cookState.ticker = setInterval(tickAllTimers, 500);
  }
  function tickAllTimers() {
    if (!cookState) return;
    let active = 0;
    for (const tid of Object.keys(cookState.timers)) {
      const t = cookState.timers[tid];
      if (t.fired) continue;
      const remaining = timerRemaining(t);
      const btn = $('[data-tid="' + tid + '"]');
      if (remaining <= 0) {
        t.fired = true; delete cookState.timers[tid];
        beep(); notifyTimer(t); toast("Таймер! " + fmtTimer(t.total));
        if (btn) { btn.textContent = "✓ Готово"; btn.classList.remove("running"); }
      } else {
        active++;
        if (btn) btn.textContent = "⏱ " + fmtTimer(remaining) + " · стоп";
      }
    }
    if (!active && cookState.ticker) { clearInterval(cookState.ticker); cookState.ticker = null; }
  }
  function bindCookTimers() {
    $("#cookBody").querySelectorAll("[data-timer]").forEach(btn => {
      const tid = btn.dataset.tid;
      const total = parseInt(btn.dataset.timer, 10);
      const running = cookState.timers[tid] && !cookState.timers[tid].fired;
      if (running) { btn.classList.add("running"); btn.textContent = "⏱ " + fmtTimer(timerRemaining(cookState.timers[tid])) + " · стоп"; }
      btn.onclick = () => {
        if (cookState.timers[tid] && !cookState.timers[tid].fired) { stopTimer(tid, btn); return; }
        ensureNotifyPermission();
        cookState.timers[tid] = { endAt: Date.now() + total * 1000, total, label: btn.dataset.label || "", fired: false };
        btn.classList.add("running");
        btn.textContent = "⏱ " + fmtTimer(total) + " · стоп";
        startTicker();
      };
    });
  }
  function stopTimer(tid, btn) {
    delete cookState.timers[tid];
    if (btn) { btn.classList.remove("running"); btn.textContent = "⏱ " + fmtTimer(parseInt(btn.dataset.timer, 10)); }
  }
  function clearCookTimers() {
    if (cookState) { if (cookState.ticker) { clearInterval(cookState.ticker); cookState.ticker = null; } cookState.timers = {}; }
  }
  function openIngredientsSheet(r, sv) {
    // Чекбоксы общие с деталью (cb_ingChecks) — прогресс сохраняется и синкается
    openSheet("Ингредиенты", `<ul class="ingredients" id="ings">${r.ingredients.map((ing, i) => ingredientRow(r, ing, i, sv)).join("")}</ul>`);
    bindIngredientRows(r);
  }

  /* Wake Lock */
  let wakeLock = null;
  async function requestWakeLock() {
    try { if ("wakeLock" in navigator) wakeLock = await navigator.wakeLock.request("screen"); } catch (e) { /* тихий fallback */ }
  }
  function releaseWakeLock() { try { if (wakeLock) { wakeLock.release(); wakeLock = null; } } catch (e) {} }

  /* Бип */
  let audioCtx = null;
  function beep() {
    try {
      audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      const beepOnce = (t) => { const o = audioCtx.createOscillator(), g = audioCtx.createGain(); o.connect(g); g.connect(audioCtx.destination); o.frequency.value = 880; g.gain.value = 0.18; o.start(t); o.stop(t + 0.18); };
      const now = audioCtx.currentTime; beepOnce(now); beepOnce(now + 0.3); beepOnce(now + 0.6);
    } catch (e) {}
  }

  /* ============================================================
     Шторка/оверлей
     ============================================================ */
  function openSheet(title, html) {
    closeSheet();
    const ov = document.createElement("div"); ov.className = "overlay"; ov.id = "sheet";
    ov.innerHTML = `<div class="sheet"><button class="btn ghost sm sheet-close" id="sheetClose">Закрыть</button><h3>${esc(title)}</h3>${html}</div>`;
    document.body.appendChild(ov);
    ov.addEventListener("click", e => { if (e.target === ov) closeSheet(); });
    $("#sheetClose").onclick = closeSheet;
    return ov;
  }
  function closeSheet() { const s = $("#sheet"); if (s) s.remove(); }

  // Первый запуск: разовое приветствие с обзором возможностей
  function maybeOnboard() {
    if (LS.get("cb_seen")) return;
    openSheet("Добро пожаловать 👋", `
      <p class="muted" style="margin-bottom:12px">Ваша личная поваренная книга. Коротко о главном:</p>
      <ul class="onboard-list">
        <li>🔎 <b>Каталог и фильтры</b> — поиск по кухне, времени, сложности, кладовке</li>
        <li>🍳 <b>Режим готовки</b> — пошагово, таймеры, экран не гаснет</li>
        <li>🛒 <b>Список покупок</b> — собирается из рецептов, вычитает кладовку</li>
        <li>🗓 <b>План на неделю</b> — авто-план по вкусам + КБЖУ</li>
        <li>🏠 <b>Готовлю из того, что есть</b> — подбор по кладовке</li>
        <li>✦ <b>Ассистент</b> — вопросы по рецептам и заменам</li>
        <li>☁️ <b>Синхронизация</b> между устройствами</li>
      </ul>
      <button class="btn primary block" id="onboardOk" style="margin-top:14px">Понятно, начать</button>
    `);
    $("#onboardOk").onclick = () => { LS.set("cb_seen", true); closeSheet(); };
  }

  /* ============================================================
     План на неделю (#/plan)
     ============================================================ */
  const DAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
  const MEALS = ["Завтрак", "Обед", "Ужин"];
  // Суммы КБЖУ по набору рецептов (одна порция на заполненный слот)
  function slotNutrition(ids) {
    const t = { kcal: 0, protein: 0, fat: 0, carbs: 0, n: 0 };
    ids.forEach(rid => {
      const r = getRecipe(rid); if (!r) return;
      t.n++;
      if (r.kcal != null) t.kcal += r.kcal;
      if (r.protein != null) t.protein += r.protein;
      if (r.fat != null) t.fat += r.fat;
      if (r.carbs != null) t.carbs += r.carbs;
    });
    return t;
  }
  // goal — опц. {kcal,protein,fat,carbs}: показываем «X/цель» и подсветку перебора
  function nutriLine(t, goal) {
    if (!t.n && !goal) return "";
    const seg = (val, tgt) => tgt ? `${fmtNum(val)}/${tgt}` : `${fmtNum(val)}`;
    const over = goal && goal.kcal && t.kcal > goal.kcal * 1.05;
    return `<div class="plan-nutri muted${over ? " over-goal" : ""}">🔥 ${seg(t.kcal, goal && goal.kcal)} ккал · Б ${seg(t.protein, goal && goal.protein)} · Ж ${seg(t.fat, goal && goal.fat)} · У ${seg(t.carbs, goal && goal.carbs)} г</div>`;
  }
  function todayKey() { const d = new Date(); return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0"); }
  function goalSet() { const g = Store.goals || {}; return !!(g.kcal || g.protein || g.fat || g.carbs); }
  // Авто-план: заполнить пустые слоты по вкусам, с учётом профиля, категорийно, без повторов
  const MEAL_CATS = {
    "Завтрак": ["Завтрак", "Выпечка"],
    "Обед": ["Суп", "Основное", "Салат"],
    "Ужин": ["Основное", "Гарнир", "Салат", "Суп"],
  };
  let autoRollSeed = 0;
  function pickFrom(pool, used, cats, di, meal) {
    const cand = pool.filter(r => !used.has(r.id) && (!cats.length || cats.includes(r.category)));
    const list = cand.length ? cand : pool.filter(r => !used.has(r.id));
    if (!list.length) return null;
    const off = (autoRollSeed + di * 3 + MEALS.indexOf(meal)) % list.length;
    return list[off];
  }
  function autoFillPlan() {
    autoRollSeed++;
    const ranked = recommend(100).filter(profileAllows);
    const pool = ranked.concat(allRecipes().filter(r => profileAllows(r) && !ranked.includes(r)));
    const used = new Set(Object.values(Store.plan));
    DAYS.forEach((d, di) => MEALS.forEach(meal => {
      const key = d + "|" + meal;
      if (Store.plan[key]) return; // ручные не трогаем
      const m = pickFrom(pool, used, MEAL_CATS[meal] || [], di, meal);
      if (m) { Store.plan[key] = m.id; used.add(m.id); }
    }));
    Store.save("plan"); renderPlan();
    toast("План собран — жми ещё раз для другого варианта");
  }
  function openChildSheet() {
    const c = Store.child || {};
    openSheet("👶 Профиль ребёнка", `
      <div class="row2">
        <div class="field"><label>Имя</label><input id="ch_name" value="${esc(c.name || "")}"></div>
        <div class="field"><label>Возраст</label><input id="ch_age" type="number" inputmode="numeric" value="${esc(c.age || "")}"></div>
      </div>
      <div class="field"><label>Не ест (через запятую)</label><input id="ch_dislikes" value="${esc((c.dislikes || []).join(", "))}"></div>
      <div class="field"><label>Аллергии (через запятую)</label><input id="ch_allergies" value="${esc((c.allergies || []).join(", "))}"></div>
      <p class="muted">Фильтр «★ Дочке» спрячет блюда с этими продуктами. AI-режим «спрячь овощи» — на карточке рецепта.</p>
      <button class="btn primary block" id="ch_save" style="margin-top:12px">Сохранить</button>
    `);
    $("#ch_save").onclick = () => {
      Store.child = {
        name: $("#ch_name").value.trim(), age: $("#ch_age").value.trim(),
        dislikes: $("#ch_dislikes").value.split(",").map(s => s.trim()).filter(Boolean),
        allergies: $("#ch_allergies").value.split(",").map(s => s.trim()).filter(Boolean),
      };
      Store.save("child"); closeSheet(); toast("Профиль ребёнка сохранён");
    };
  }
  function openGoalSheet() {
    const g = Store.goals || {};
    openSheet("🎯 Цель на день", `
      <p class="muted" style="margin-bottom:10px">Дневная норма — планер и «Сегодня» покажут попадание. 0 = не учитывать.</p>
      <div class="row2">
        <div class="field"><label>Калории</label><input id="g_kcal" type="number" inputmode="numeric" value="${g.kcal || ""}"></div>
        <div class="field"><label>Белки, г</label><input id="g_protein" type="number" inputmode="numeric" value="${g.protein || ""}"></div>
      </div>
      <div class="row2">
        <div class="field"><label>Жиры, г</label><input id="g_fat" type="number" inputmode="numeric" value="${g.fat || ""}"></div>
        <div class="field"><label>Углеводы, г</label><input id="g_carbs" type="number" inputmode="numeric" value="${g.carbs || ""}"></div>
      </div>
      <button class="btn primary block" id="g_save" style="margin-top:12px">Сохранить</button>
    `);
    $("#g_save").onclick = () => {
      Store.goals = { kcal: +$("#g_kcal").value || 0, protein: +$("#g_protein").value || 0, fat: +$("#g_fat").value || 0, carbs: +$("#g_carbs").value || 0 };
      Store.save("goals"); closeSheet(); renderPlan(); toast("Цель сохранена");
    };
  }
  // Дневник съеденного растёт по дню — держим только последние 30 дней (иначе синк-блоб пухнет)
  function pruneEaten() {
    const keys = Object.keys(Store.eaten || {});
    if (keys.length <= 30) return;
    keys.sort(); // YYYY-MM-DD лексикографически = хронологически
    keys.slice(0, keys.length - 30).forEach(k => delete Store.eaten[k]);
  }
  function eatToday(id) {
    const k = todayKey();
    Store.eaten[k] = Store.eaten[k] || [];
    Store.eaten[k].push(id); pruneEaten(); Store.save("eaten");
    toast("Отмечено: съедено сегодня");
  }
  function renderPlan() {
    const view = $("#view");
    const empty = !Object.keys(Store.plan).length;
    const weekIds = Object.entries(Store.plan).filter(([k]) => DAYS.includes(k.split("|")[0])).map(([, rid]) => rid);
    const g = goalSet() ? Store.goals : null;
    const weekGoal = g ? { kcal: g.kcal * 7, protein: g.protein * 7, fat: g.fat * 7, carbs: g.carbs * 7 } : null;
    const eatenIds = Store.eaten[todayKey()] || [];
    view.innerHTML = `
      <div class="section-head"><h2>План на неделю</h2></div>
      <div class="btn-row" style="margin-bottom:12px">
        <button class="btn ghost sm" id="planGoal">🎯 Цель на день${g && g.kcal ? ` · ${g.kcal} ккал` : ""}</button>
      </div>
      <div class="plan-day today-card">
        <h4>🍽 Сегодня съедено</h4>
        ${eatenIds.length ? `<div class="chips wrap">${eatenIds.map((rid, i) => { const r = getRecipe(rid); return r ? `<button class="chip active" data-uneat="${i}">${esc(r.title)} ✕</button>` : ""; }).join("")}</div>` : `<div class="muted">Пока ничего. Открой рецепт → «🍽 Съел сегодня».</div>`}
        ${nutriLine(slotNutrition(eatenIds), g)}
      </div>
      <div class="section-head" style="margin-top:18px"><h2 style="font-size:20px">Меню недели</h2></div>
      ${empty ? `<div class="plan-empty muted">Пока пусто — 21 слот на неделю. Нажмите «✨ Авто-план недели», чтобы заполнить по вашим вкусам, или добавляйте блюда вручную.</div>` : ""}
      ${DAYS.map(d => {
        const dayIds = MEALS.map(meal => Store.plan[d + "|" + meal]).filter(Boolean);
        return `
        <div class="plan-day">
          <h4>${d}</h4>
          ${MEALS.map(meal => {
            const key = d + "|" + meal; const rid = Store.plan[key]; const r = rid && getRecipe(rid);
            return `<div class="plan-slot">
              <span class="muted" style="width:74px">${meal}</span>
              ${r ? `<a href="#/recipe/${esc(r.id)}" style="flex:1;color:var(--accent)">${esc(r.title)}</a><button class="del-x" data-clear="${esc(key)}">✕</button>`
                  : `<button class="btn sm ghost" data-pick="${esc(key)}" style="flex:1">＋ выбрать</button>`}
            </div>`;
          }).join("")}
          ${nutriLine(slotNutrition(dayIds), g)}
        </div>`;
      }).join("")}
      ${weekIds.length ? `<div class="plan-week-total"><b>Итого за неделю</b>${nutriLine(slotNutrition(weekIds), weekGoal)}</div>` : ""}
      <button class="btn block" id="planAuto" style="margin-top:10px">✨ Авто-план недели</button>
      <button class="btn primary block" id="planToShop" style="margin-top:8px">🛒 Собрать список покупок на неделю</button>
    `;
    view.querySelectorAll("[data-pick]").forEach(b => b.onclick = () => pickRecipeForPlan(b.dataset.pick));
    view.querySelectorAll("[data-clear]").forEach(b => b.onclick = () => { delete Store.plan[b.dataset.clear]; Store.save("plan"); renderPlan(); });
    view.querySelectorAll("[data-uneat]").forEach(b => b.onclick = () => { const arr = Store.eaten[todayKey()] || []; arr.splice(+b.dataset.uneat, 1); Store.eaten[todayKey()] = arr; Store.save("eaten"); renderPlan(); });
    $("#planGoal").onclick = () => openGoalSheet();
    $("#planAuto").onclick = () => autoFillPlan();
    $("#planToShop").onclick = () => {
      let n = 0;
      Object.entries(Store.plan).forEach(([key, rid]) => { const r = getRecipe(rid); if (r) { addRecipeToShopping(rid, Store.planServings[key] || r.baseServings); n++; } });
      updateBadge(); toast(n ? "Добавлено блюд: " + n : "План пуст"); if (n) location.hash = "#/shopping";
    };
  }
  function pickRecipeForPlan(key) {
    const recipes = allRecipes();
    openSheet("Выбрать блюдо", `<div class="search"><span>🔎</span><input id="planSearch" placeholder="Поиск…"></div><div id="planResults">${recipes.map(r => `<button class="btn ghost block" style="justify-content:flex-start;margin-bottom:6px" data-rid="${esc(r.id)}">${esc(r.title)} <span class="muted">· ${esc(r.cuisine)}</span></button>`).join("")}</div>`);
    const bind = () => $("#planResults").querySelectorAll("[data-rid]").forEach(b => b.onclick = () => { Store.plan[key] = b.dataset.rid; Store.save("plan"); closeSheet(); renderPlan(); });
    bind();
    $("#planSearch").addEventListener("input", e => {
      const q = normName(e.target.value);
      $("#planResults").innerHTML = recipes.filter(r => normName(r.title).includes(q)).map(r => `<button class="btn ghost block" style="justify-content:flex-start;margin-bottom:6px" data-rid="${esc(r.id)}">${esc(r.title)} <span class="muted">· ${esc(r.cuisine)}</span></button>`).join("");
      bind();
    });
  }

  /* ============================================================
     Добавить / импорт (#/add)
     ============================================================ */
  function renderAdd() {
    const view = $("#view");
    view.innerHTML = `
      <div class="section-head"><h2>Добавить рецепт</h2></div>
      <div class="chips wrap">
        <button class="chip active" data-tab="manual">Вручную</button>
        <button class="chip" data-tab="import">Импорт (ссылка/фото)</button>
        <button class="chip" data-tab="backup">Бэкап / печать</button>
      </div>
      <div id="addBody"></div>
    `;
    const tabs = view.querySelectorAll("[data-tab]");
    tabs.forEach(t => t.onclick = () => { tabs.forEach(x => x.classList.remove("active")); t.classList.add("active"); addTab(t.dataset.tab); });
    if (pendingDraft) { manualForm(normalizeDraft(pendingDraft)); pendingDraft = null; toast("Черновик готов — проверьте и сохраните"); }
    else addTab("manual");
  }
  function addTab(tab) {
    if (tab === "manual") return manualForm();
    if (tab === "import") return importForm();
    if (tab === "backup") return backupTab();
  }
  function manualForm(draft) {
    draft = draft || { title: "", cuisine: "", category: "Основное", time: 30, difficulty: 1, baseServings: 2, forKid: false, ingredients: [{}], steps: [{}], tags: [] };
    const cats = ["Завтрак", "Суп", "Основное", "Гарнир", "Салат", "Десерт", "Выпечка", "Закуска", "Напиток"];
    $("#addBody").innerHTML = `
      <div class="field"><label>Название</label><input id="f_title" value="${esc(draft.title)}"></div>
      <div class="row2">
        <div class="field"><label>Кухня</label><input id="f_cuisine" list="cuisineList" value="${esc(draft.cuisine)}"><datalist id="cuisineList">${Object.keys(CUISINE_COLOR).map(c => `<option value="${esc(c)}">`).join("")}</datalist></div>
        <div class="field"><label>Категория</label><select id="f_category">${cats.map(c => `<option ${draft.category === c ? "selected" : ""}>${c}</option>`).join("")}</select></div>
      </div>
      <div class="row2">
        <div class="field"><label>Время (мин)</label><input id="f_time" type="number" value="${draft.time}"></div>
        <div class="field"><label>Порций</label><input id="f_servings" type="number" value="${draft.baseServings}"></div>
      </div>
      <div class="field"><label><input type="checkbox" id="f_kid" ${draft.forKid ? "checked" : ""}> Для дочки</label></div>
      <div class="row2">
        <div class="field"><label>Калории (порция)</label><input id="f_kcal" type="number" value="${draft.kcal || ""}"></div>
        <div class="field"><label>Белки, г</label><input id="f_protein" type="number" value="${draft.protein || ""}"></div>
      </div>
      <div class="row2">
        <div class="field"><label>Жиры, г</label><input id="f_fat" type="number" value="${draft.fat || ""}"></div>
        <div class="field"><label>Углеводы, г</label><input id="f_carbs" type="number" value="${draft.carbs || ""}"></div>
      </div>
      <div class="field"><label>Аллергены (через запятую)</label><input id="f_allergens" value="${esc((draft.allergens || []).join(", "))}"></div>
      <div class="field"><label>Фото блюда</label><input id="f_photo" type="file" accept="image/*"><div id="f_photoPrev">${draft.photo ? `<img src="${esc(draft.photo)}" style="max-width:120px;border-radius:8px;margin-top:8px">` : ""}</div></div>
      <div class="field"><label>Ингредиенты (название · кол-во · ед · раздел)</label><div id="f_ings"></div><button class="btn sm" id="addIng">＋ ингредиент</button></div>
      <div class="field"><label>Шаги (заголовок · что делать · таймер)</label><div id="f_steps"></div><button class="btn sm" id="addStep">＋ шаг</button></div>
      <div class="field"><label>С чем подавать</label><input id="f_serve" value="${esc(draft.serveWith || "")}"></div>
      <div class="btn-row"><button class="btn primary" id="saveRecipe">Сохранить</button><button class="btn" id="exportRecipe">Экспорт JSON</button></div>
    `;
    const ingsBox = $("#f_ings"), stepsBox = $("#f_steps");
    function ingRow(ing) { ing = ing || {}; const d = document.createElement("div"); d.className = "dyn-row"; d.innerHTML = `<input placeholder="название" class="i-name" value="${esc(ing.name || "")}"><input placeholder="кол-во" class="i-qty" style="max-width:70px" value="${ing.qty != null ? ing.qty : ""}"><input placeholder="ед" class="i-unit" style="max-width:60px" value="${esc(ing.unit || "")}"><input placeholder="раздел" class="i-group" style="max-width:90px" value="${esc(ing.group || "")}"><button class="del-x">✕</button>`; d.querySelector(".del-x").onclick = () => d.remove(); return d; }
    function stepRow(s) { s = s || {}; const d = document.createElement("div"); d.className = "dyn-row"; d.style.flexWrap = "wrap"; d.innerHTML = `<input placeholder="заголовок шага" class="s-title" style="flex:1 1 100%;margin-bottom:6px" value="${esc(s.title || "")}"><textarea placeholder="что делать" class="s-text" style="flex:1">${esc(s.text || "")}</textarea><input placeholder="таймер сек" class="s-timer" style="max-width:80px" value="${s.timer || ""}"><button class="del-x">✕</button>`; d.querySelector(".del-x").onclick = () => d.remove(); return d; }
    (draft.ingredients.length ? draft.ingredients : [{}]).forEach(i => ingsBox.appendChild(ingRow(i)));
    (draft.steps.length ? draft.steps : [{}]).forEach(s => stepsBox.appendChild(stepRow(s)));
    $("#addIng").onclick = () => ingsBox.appendChild(ingRow());
    $("#addStep").onclick = () => stepsBox.appendChild(stepRow());

    // Фото блюда → resized JPEG dataURL (хранится в самом рецепте)
    let photoData = draft.photo || "";
    $("#f_photo").onchange = () => {
      const f = $("#f_photo").files[0]; if (!f) return;
      const reader = new FileReader();
      reader.onload = () => {
        const img = new Image();
        img.onload = () => {
          const max = 600, sc = Math.min(1, max / Math.max(img.width, img.height));
          const c = document.createElement("canvas"); c.width = Math.round(img.width * sc); c.height = Math.round(img.height * sc);
          c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
          photoData = c.toDataURL("image/jpeg", 0.82);
          $("#f_photoPrev").innerHTML = `<img src="${photoData}" style="max-width:120px;border-radius:8px;margin-top:8px">`;
        };
        img.src = reader.result;
      };
      reader.readAsDataURL(f);
    };

    function collect() {
      const title = $("#f_title").value.trim();
      const ingredients = [...ingsBox.querySelectorAll(".dyn-row")].map(d => ({
        name: d.querySelector(".i-name").value.trim(),
        qty: d.querySelector(".i-qty").value ? parseFloat(d.querySelector(".i-qty").value.replace(",", ".")) : null,
        unit: d.querySelector(".i-unit").value.trim(),
        group: d.querySelector(".i-group").value.trim() || "Прочее",
        staple: false
      })).filter(i => i.name);
      const steps = [...stepsBox.querySelectorAll(".dyn-row")].map(d => { const o = { text: d.querySelector(".s-text").value.trim() }; const ti = d.querySelector(".s-title").value.trim(); if (ti) o.title = ti; const t = d.querySelector(".s-timer").value; if (t) o.timer = parseInt(t, 10); return o; }).filter(s => s.text);
      const numOr = (sel, d) => { const v = parseInt($(sel).value, 10); return Number.isFinite(v) ? v : d; };
      const allergens = $("#f_allergens").value.split(",").map(s => s.trim()).filter(Boolean);
      const r = {
        id: (title.toLowerCase().replace(/[^a-zа-я0-9]+/gi, "-").replace(/^-|-$/g, "") || "recipe") + "-" + Math.random().toString(36).slice(2, 6),
        title, forKid: $("#f_kid").checked, category: $("#f_category").value, cuisine: $("#f_cuisine").value.trim() || "Прочая",
        photo: photoData || "", time: parseInt($("#f_time").value, 10) || 0, difficulty: draft.difficulty || 1,
        baseServings: parseInt($("#f_servings").value, 10) || 1, tags: draft.tags || [], ingredients, steps,
        serveWith: $("#f_serve").value.trim(), notes: draft.notes || "", allergens
      };
      // нутриенты из полей формы
      ["kcal", "protein", "fat", "carbs"].forEach(k => { const v = numOr("#f_" + k, null); if (v != null) r[k] = v; });
      // прочие доп. поля из черновика (ИИ/импорт), если есть
      ["prepTime", "cookTime", "equipment", "kidNote"].forEach(k => { if (draft[k] != null && draft[k] !== "") r[k] = draft[k]; });
      return r;
    }
    $("#saveRecipe").onclick = () => { const r = collect(); if (!r.title || !r.ingredients.length) { toast("Нужны название и ингредиенты"); return; } Store.userRecipes.push(r); Store.save("userRecipes"); toast("Рецепт сохранён"); location.hash = "#/recipe/" + r.id; };
    $("#exportRecipe").onclick = () => copyText(JSON.stringify(collect(), null, 2));
  }

  function importForm() {
    $("#addBody").innerHTML = `
      <div class="field"><label>Импорт по ссылке (страница рецепта)</label>
        <div class="dyn-row"><input id="impUrl" placeholder="https://…"><button class="btn sm" id="impUrlBtn">Импорт</button></div>
      </div>
      <div class="field"><label>Импорт по фото страницы / рукописи</label>
        <input id="impPhoto" type="file" accept="image/*"><button class="btn sm" id="impPhotoBtn" style="margin-top:8px">Распознать</button>
      </div>
      <p class="muted">Импорт обращается к бэкенду (требуется секрет и запущенный сервер). Результат — черновик, который можно поправить и сохранить.</p>
      <div id="impStatus"></div>
    `;
    $("#impUrlBtn").onclick = () => guardAuth(async () => {
      const url = $("#impUrl").value.trim(); if (!url) return;
      $("#impStatus").textContent = "Импортирую…";
      try { const draft = await window.CookAssistant.importUrl(url); openDraft(draft); }
      catch (e) { $("#impStatus").textContent = "Ошибка импорта: " + e.message; }
    });
    $("#impPhotoBtn").onclick = () => guardAuth(async () => {
      const f = $("#impPhoto").files[0]; if (!f) return;
      $("#impStatus").textContent = "Распознаю…";
      try { const draft = await window.CookAssistant.importPhoto(f); openDraft(draft); }
      catch (e) { $("#impStatus").textContent = "Ошибка распознавания: " + e.message; }
    });
    function openDraft(draft) {
      document.querySelectorAll("[data-tab]").forEach(t => t.classList.toggle("active", t.dataset.tab === "manual"));
      manualForm(normalizeDraft(draft)); toast("Черновик готов — проверьте и сохраните");
    }
  }
  function normalizeDraft(d) {
    const r = {
      title: d.title || "", cuisine: d.cuisine || "", category: d.category || "Основное",
      time: d.time || 30, difficulty: d.difficulty || 1, baseServings: d.baseServings || 2, forKid: !!d.forKid,
      tags: d.tags || [], serveWith: d.serveWith || "", notes: d.notes || "",
      ingredients: (d.ingredients || []).map(i => typeof i === "string" ? { name: i, group: "Прочее" } : i),
      steps: (d.steps || []).map(s => typeof s === "string" ? { text: s } : s)
    };
    ["kcal", "protein", "fat", "carbs", "prepTime", "cookTime", "equipment", "allergens", "kidNote"].forEach(k => { if (d[k] != null && d[k] !== "") r[k] = d[k]; });
    return r;
  }
  // Открыть AI/импорт-черновик в форме «Добавить» из любого экрана
  let pendingDraft = null;
  function startDraft(draft) {
    const conflict = draftAllergenConflict(draft);
    if (conflict.length) toast("⚠ Возможен исключённый аллерген: " + conflict.join(", ") + " — проверьте состав перед готовкой");
    pendingDraft = draft;
    if (location.hash === "#/add") renderAdd(); else location.hash = "#/add";
  }

  function backupTab() {
    $("#addBody").innerHTML = `
      <div class="field"><label>Резервная копия (все данные: рецепты, список, кладовка, память, план)</label>
        <div class="btn-row"><button class="btn" id="bkExport">⬇ Экспорт JSON</button><button class="btn" id="bkImportBtn">⬆ Импорт JSON</button><input id="bkFile" type="file" accept="application/json" class="hidden"></div>
      </div>
      <div class="field"><label>Печать книги</label><button class="btn" id="printBook">🖨 Печать / PDF</button></div>
    `;
    $("#bkExport").onclick = () => {
      const data = { v: 1, userRecipes: Store.userRecipes, shopping: Store.shopping, pantry: Store.pantry, memory: Store.memory, plan: Store.plan, ingChecks: Store.ingChecks, profile: Store.profile, planServings: Store.planServings, goals: Store.goals, eaten: Store.eaten, collections: Store.collections, child: Store.child };
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "cookbook-backup.json"; a.click();
    };
    $("#bkImportBtn").onclick = () => $("#bkFile").click();
    $("#bkFile").onchange = e => {
      const f = e.target.files[0]; if (!f) return;
      const reader = new FileReader();
      reader.onload = () => {
        try {
          const d = JSON.parse(reader.result);
          ["userRecipes", "shopping", "pantry", "memory", "plan", "ingChecks", "profile", "planServings", "goals", "eaten", "collections", "child"].forEach(k => { if (d[k]) { Store[k] = d[k]; Store.save(k); } });
          toast("Импортировано"); updateBadge();
        } catch (err) { toast("Битый файл"); }
      };
      reader.readAsText(f);
    };
    $("#printBook").onclick = () => printBook();
  }
  function printBook() {
    const recipes = allRecipes();
    const win = $("#view");
    const prev = win.innerHTML;
    win.innerHTML = recipes.map(r => `<article class="recipe-print"><h1>${esc(r.title)}</h1><p class="muted">${esc(r.cuisine)} · ${esc(r.category)} · ${r.time} мин · ${r.baseServings} порц.</p><div class="label">Ингредиенты</div><ul class="ingredients">${r.ingredients.map(i => `<li><span class="ing-name">${esc(i.name)}</span><span class="ing-qty">${fmtQtyUnit(i.qty, i.unit, r.baseServings, r.baseServings)}</span></li>`).join("")}</ul><div class="label">Метод</div><ol class="steps">${r.steps.map(s => `<li><div class="step-text">${esc(s.text)}</div></li>`).join("")}</ol></article>`).join("");
    window.print();
    setTimeout(() => { win.innerHTML = prev; router(); }, 300);
  }

  /* ============================================================
     Роутер
     ============================================================ */
  function router() {
    closeSheet();
    stopVoice(); // уходим с кукинг-мода → выключаем микрофон
    const hash = location.hash || "#/";
    const m = hash.match(/^#\/(\w+)?\/?(.*)$/);
    const route = m && m[1] ? m[1] : "";
    const arg = m && m[2] ? decodeURIComponent(m[2]) : "";
    window.scrollTo(0, 0);
    updateBadge();
    updateTabbar(route);
    if (route === "recipe") return renderRecipe(arg);
    if (route === "cook") return renderCook(arg);
    if (route === "shopping") return renderShopping();
    if (route === "today") return renderToday();
    if (route === "saved") return renderSaved();
    if (route === "assistant") return window.CookAssistant ? window.CookAssistant.renderView($("#view")) : null;
    if (route === "plan") return renderPlan();
    if (route === "add") return renderAdd();
    return renderList();
  }

  // Экспорт для assistant.js
  window.Cookbook = {
    Store, getRecipe, allRecipes, applySubstitution, toast, esc, addRecipeToShopping, updateBadge, normName
  };
  function applySubstitution(recipeId, sub) {
    // записать в личную память
    if (recipeId) {
      const mem = getMem(recipeId); mem.substitutions = mem.substitutions || [];
      mem.substitutions.push({ original: sub.original, replacement: sub.replacement, note: sub.note || "" }); saveMem();
    }
    // обновить позицию в списке покупок, если есть
    const targetKey = normName(sub.original);
    (Store.shopping.manual || []).forEach(m => { if (normName(m.name) === targetKey) m.name = sub.replacement; });
    Store.save("shopping");
    toast("Замена применена: " + sub.replacement);
  }

  // Подсветка активного таба нижнего навбара по текущему маршруту
  function updateTabbar(route) {
    const map = { "": "catalog", "recipe": "catalog", "today": "today", "shopping": "shopping", "plan": "plan", "assistant": "assistant" };
    const active = map[route] || "";
    document.querySelectorAll("#tabbar .tab").forEach(t => t.classList.toggle("active", t.dataset.tab === active));
  }
  window.addEventListener("hashchange", router);
  function boot() { router(); maybeOnboard(); }
  document.addEventListener("DOMContentLoaded", boot);
  if (document.readyState !== "loading") boot();

  // Синк: перерисовать при подтягивании серверных данных + первичный merge
  window.addEventListener("cb-synced", router);
  if (window.CookSync) window.CookSync.boot();
})();
