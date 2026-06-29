#!/usr/bin/env node
/*
 * Генерация классических блюд по кухням до заданного минимума.
 * Дописывает в landing/data/recipes.js (append-only, не переформатирует существующие).
 *
 * Usage:
 *   node scripts/gen_recipes.js --floor=20 --only=Вьетнамская,Финская
 *   node scripts/gen_recipes.js --floor=20            # все кухни ниже floor
 *   node scripts/gen_recipes.js --floor=20 --dry      # только показать дефицит, без вызовов
 *
 * Ключ берётся из .env (ANTHROPIC_API_KEYS, первый из пула). Модель — Opus.
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const RECIPES_PATH = path.join(ROOT, "landing/data/recipes.js");

const args = Object.fromEntries(process.argv.slice(2).map(a => {
  const m = a.match(/^--([^=]+)(?:=(.*))?$/);
  return m ? [m[1], m[2] === undefined ? true : m[2]] : [a, true];
}));
const FLOOR = parseInt(args.floor || "20", 10);
const ONLY = args.only ? String(args.only).split(",").map(s => s.trim()).filter(Boolean) : null;
const DRY = !!args.dry;
const PER_CALL = parseInt(args.batch || "6", 10);
const MODEL = args.model || "claude-opus-4-8";

// ── API key ──
function apiKey() {
  const env = fs.readFileSync(path.join(ROOT, ".env"), "utf8");
  const m = env.match(/^ANTHROPIC_API_KEYS=(.+)$/m);
  if (!m) throw new Error("ANTHROPIC_API_KEYS не найден в .env");
  return m[1].trim().replace(/^["']|["']$/g, "").split(",")[0].trim();
}
const KEY = DRY ? "" : apiKey();

// ── recipes I/O ──
function loadRecipes() {
  global.window = {};
  delete require.cache[require.resolve(RECIPES_PATH)];
  require(RECIPES_PATH);
  return global.window.RECIPES;
}
function cuisineCounts(recipes) {
  const c = {};
  for (const r of recipes) c[r.cuisine] = (c[r.cuisine] || 0) + 1;
  return c;
}

// ── translit для id ──
const TR = { а:"a",б:"b",в:"v",г:"g",д:"d",е:"e",ё:"e",ж:"zh",з:"z",и:"i",й:"y",к:"k",л:"l",м:"m",н:"n",о:"o",п:"p",р:"r",с:"s",т:"t",у:"u",ф:"f",х:"h",ц:"c",ч:"ch",ш:"sh",щ:"sch",ъ:"",ы:"y",ь:"",э:"e",ю:"yu",я:"ya" };
function slug(title) {
  return String(title).toLowerCase().split("").map(ch => TR[ch] !== undefined ? TR[ch] : ch)
    .join("").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40) || "recipe";
}
function uniqueId(base, used) {
  let id = base, i = 2;
  while (used.has(id)) { id = base + "-" + i++; }
  used.add(id);
  return id;
}

// ── сериализация (стиль существующего файла) ──
const J = s => JSON.stringify(String(s == null ? "" : s));
const arr = a => "[" + (a || []).map(J).join(", ") + "]";
const num = (v, d = 0) => Number.isFinite(+v) ? Math.round(+v) : d;
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, num(v, lo)));
function serIng(i) {
  const qty = (i.qty === null || i.qty === undefined || i.qty === "") ? "null" : Number(i.qty);
  return `      { name: ${J(i.name)}, qty: ${qty}, unit: ${J(i.unit)}, group: ${J(i.group || "Прочее")}, staple: ${!!i.staple} }`;
}
function serStep(s) {
  const p = [];
  if (s.title) p.push(`title: ${J(s.title)}`);
  p.push(`text: ${J(s.text)}`);
  if (s.timer) p.push(`timer: ${num(s.timer)}`);
  return `      { ${p.join(", ")} }`;
}
function serRecipe(r) {
  const L = [];
  L.push("  {");
  L.push(`    id: ${J(r.id)}, title: ${J(r.title)}, forKid: ${!!r.forKid}, kidNote: ${J(r.kidNote || "")},`);
  L.push(`    category: ${J(r.category)}, cuisine: ${J(r.cuisine)}, photo: "",`);
  L.push(`    prepTime: ${num(r.prepTime)}, cookTime: ${num(r.cookTime)}, time: ${num(r.time) || (num(r.prepTime) + num(r.cookTime))}, difficulty: ${clamp(r.difficulty, 1, 3)}, baseServings: ${num(r.baseServings, 2) || 2}, kcal: ${num(r.kcal)},`);
  L.push(`    equipment: ${arr(r.equipment)}, allergens: ${arr(r.allergens)}, tags: ${arr(r.tags)},`);
  L.push(`    ingredients: [`);
  L.push(r.ingredients.map(serIng).join(",\n"));
  L.push(`    ],`);
  L.push(`    steps: [`);
  L.push(r.steps.map(serStep).join(",\n"));
  L.push(`    ],`);
  if (r.serveWith) L.push(`    serveWith: ${J(r.serveWith)},`);
  L.push(`    notes: ${J(r.notes || "")}`);
  L.push("  }");
  return L.join("\n");
}
function appendRecipes(newRecipes) {
  let txt = fs.readFileSync(RECIPES_PATH, "utf8");
  const idx = txt.lastIndexOf("\n];");
  if (idx < 0) throw new Error("не найден конец массива (\\n];)");
  const insert = newRecipes.map(r => ",\n" + serRecipe(r)).join("");
  txt = txt.slice(0, idx) + insert + txt.slice(idx);
  fs.writeFileSync(RECIPES_PATH, txt);
}

// ── Anthropic tool-use ──
const ING_SCHEMA = { type: "object", required: ["name", "unit", "group", "staple"], properties: { name: { type: "string" }, qty: { type: ["number", "null"] }, unit: { type: "string" }, group: { type: "string" }, staple: { type: "boolean" } } };
const STEP_SCHEMA = { type: "object", required: ["title", "text"], properties: { title: { type: "string" }, text: { type: "string" }, timer: { type: "integer" } } };
const RECIPE_SCHEMA = {
  type: "object",
  required: ["title", "category", "time", "difficulty", "baseServings", "ingredients", "steps", "serveWith", "notes", "forKid"],
  properties: {
    title: { type: "string" }, forKid: { type: "boolean" }, kidNote: { type: "string" },
    category: { type: "string", enum: ["Завтрак", "Суп", "Основное", "Гарнир", "Салат", "Десерт", "Выпечка", "Закуска", "Напиток"] },
    prepTime: { type: "integer" }, cookTime: { type: "integer" }, time: { type: "integer" },
    difficulty: { type: "integer", minimum: 1, maximum: 3 }, baseServings: { type: "integer" }, kcal: { type: "integer" },
    equipment: { type: "array", items: { type: "string" } }, allergens: { type: "array", items: { type: "string" } }, tags: { type: "array", items: { type: "string" } },
    ingredients: { type: "array", minItems: 2, items: ING_SCHEMA },
    steps: { type: "array", minItems: 2, items: STEP_SCHEMA },
    serveWith: { type: "string" }, notes: { type: "string" }
  }
};
const TOOL = { name: "add_recipes", description: "Добавить сгенерированные рецепты", input_schema: { type: "object", required: ["recipes"], properties: { recipes: { type: "array", items: RECIPE_SCHEMA } } } };

const SYSTEM = `Ты — опытный шеф-повар и кулинарный редактор. Генерируешь КЛАССИЧЕСКИЕ, аутентичные блюда конкретной национальной кухни — те, что реально готовят и узнают.
Правила:
- title — ТОЛЬКО название блюда. Без пояснений, без комментариев про стоп-список, без слов «не подходит / нельзя / нет / вместо». Если придуманное блюдо есть в стоп-списке — молча выбери другое, ничего не объясняя.
- Реальные пропорции и метрические единицы (г, мл, шт, ст.л., ч.л.). qty=null + unit="по вкусу" для соли/перца/специй по вкусу.
- ingredients[].group — раздел магазина (Овощи, Мясо, Рыба, Молочное, Бакалея, Специи, Зелень, Заморозка, Прочее). staple=true для базовых запасов (соль, масло, мука, сахар).
- steps: у КАЖДОГО шага обязателен короткий title (1–4 слова) + понятный text. timer (в СЕКУНДАХ) там, где есть явное время варки/выпечки/настаивания.
- serveWith — ОБЯЗАТЕЛЬНО непустое «с чем подавать» (1–2 предложения). notes — полезный совет/нюанс.
- time — ориентировочное АКТИВНОЕ время готовки в минутах (обычно ≤180). Долгое пассивное время (маринование, брожение, расстойка, охлаждение на ночь) НЕ суй в time — опиши его словами в notes.
- category строго из списка. difficulty 1..3. forKid=true, если блюдо подходит ребёнку 3–6 лет (не острое, не алкоголь); тогда kidNote — короткая оговорка или "".
- Русский язык. Без выдуманных блюд — только настоящая классика этой кухни. НЕ повторяй блюда из стоп-списка и их вариации.`;

async function callOpus(cuisine, count, avoidTitles) {
  const body = {
    model: MODEL, max_tokens: 16000, system: SYSTEM,
    tools: [TOOL], tool_choice: { type: "tool", name: "add_recipes" },
    messages: [{ role: "user", content: `Кухня: ${cuisine}. Дай ${count} разных классических блюд этой кухни (разнообразь категории: основное, суп, закуска, десерт, выпечка и т.д., где уместно).\nСТОП-СПИСОК (НЕ повторять, и не их вариации): ${avoidTitles.join("; ") || "—"}` }]
  };
  for (let attempt = 1; attempt <= 4; attempt++) {
    const res = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: { "x-api-key": KEY, "anthropic-version": "2023-06-01", "content-type": "application/json" },
      body: JSON.stringify(body)
    });
    if (res.ok) {
      const data = await res.json();
      const tool = (data.content || []).find(c => c.type === "tool_use");
      if (tool && tool.input && Array.isArray(tool.input.recipes)) return tool.input.recipes;
      return [];
    }
    if (res.status === 429 || res.status >= 500) { await sleep(2000 * attempt); continue; }
    throw new Error(`API ${res.status}: ${(await res.text()).slice(0, 300)}`);
  }
  throw new Error("API: исчерпаны попытки");
}
const sleep = ms => new Promise(r => setTimeout(r, ms));
const norm = s => String(s || "").toLowerCase().replace(/ё/g, "е").replace(/[^a-zа-я0-9]+/gi, "").trim();
// Подстраховка: вычистить из названия рассуждения модели про стоп-список
function cleanTitle(t) {
  t = String(t || "").trim();
  if (/(не подходит|нельзя|\bнет\b|вместо)/i.test(t)) {
    const parts = t.split(/[—;]| - /).map(s => s.trim()).filter(Boolean);
    t = parts[parts.length - 1] || t;
  }
  return t.trim();
}

(async function main() {
  let recipes = loadRecipes();
  const counts = cuisineCounts(recipes);
  let cuisines = Object.keys(counts).sort((a, b) => counts[a] - counts[b]);
  if (ONLY) cuisines = cuisines.filter(c => ONLY.includes(c));
  const targets = cuisines.filter(c => counts[c] < FLOOR);

  console.log(`Floor=${FLOOR}, модель=${MODEL}. Кухонь под добор: ${targets.length}`);
  let totalNeed = 0;
  for (const c of targets) { console.log(`  ${c}: ${counts[c]} → +${FLOOR - counts[c]}`); totalNeed += FLOOR - counts[c]; }
  console.log(`Итого новых: ~${totalNeed}`);
  if (DRY || !targets.length) return;

  const usedIds = new Set(recipes.map(r => r.id));
  let grandTotal = 0;
  for (const cuisine of targets) {
    const have = recipes.filter(r => r.cuisine === cuisine).map(r => r.title);
    const seen = new Set(have.map(norm));
    let need = FLOOR - counts[cuisine];
    const fresh = [];
    let guard = 0;
    while (need > 0 && guard++ < 6) {
      const ask = Math.min(need, PER_CALL);
      let gen;
      try { gen = await callOpus(cuisine, ask, [...have, ...fresh.map(r => r.title)]); }
      catch (e) { console.error(`  [${cuisine}] ошибка: ${e.message}`); break; }
      let added = 0;
      for (const g of gen) {
        if (!g || !g.title || !Array.isArray(g.ingredients) || !Array.isArray(g.steps)) continue;
        g.title = cleanTitle(g.title);
        if (!g.title || seen.has(norm(g.title))) continue;
        seen.add(norm(g.title));
        g.cuisine = cuisine;
        if (num(g.time) > 360) g.time = (num(g.prepTime) + num(g.cookTime)) || 60; // не раздувать карточку пассивным временем
        g.id = uniqueId(slug(g.title), usedIds);
        fresh.push(g);
        added++; need--;
        if (need <= 0) break;
      }
      console.log(`  [${cuisine}] +${added} (нужно ещё ${Math.max(0, need)})`);
      if (added === 0) break; // модель не даёт новых — выходим
    }
    if (fresh.length) {
      appendRecipes(fresh);
      grandTotal += fresh.length;
      recipes = loadRecipes(); // обновить для целостности usedIds на следующих
    }
  }
  console.log(`\nГОТОВО. Добавлено всего: ${grandTotal}. Рецептов в базе: ${loadRecipes().length}`);
})();
