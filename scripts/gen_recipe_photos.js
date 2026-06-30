#!/usr/bin/env node
/*
 * Фото для рецептов ($0-путь): Wikimedia Commons → Sonnet-QA «блюдо — главный объект» → WebP → вписать в recipes.js.
 * Заполняет только рецепты с photo:"". Резюмируемо (источник истины — сам файл).
 *
 * Usage:
 *   node scripts/gen_recipe_photos.js --only=Вьетнамская,Финская   # ограничить кухнями (прототип)
 *   node scripts/gen_recipe_photos.js --limit=30                   # не больше N рецептов за прогон
 *   node scripts/gen_recipe_photos.js --dry                        # только показать, сколько без фото
 *
 * НЕ запускать одновременно с gen_recipes.js — оба пишут recipes.js.
 */
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

const ROOT = path.resolve(__dirname, "..");
const RECIPES_PATH = path.join(ROOT, "landing/data/recipes.js");
const IMG_DIR = path.join(ROOT, "landing/img/recipes");
const TMP = path.join(ROOT, ".photo_tmp");
const UA = "fashioncastle-cookbook/1.0 (personal use; contact stas)";

const args = Object.fromEntries(process.argv.slice(2).map(a => {
  const m = a.match(/^--([^=]+)(?:=(.*))?$/);
  return m ? [m[1], m[2] === undefined ? true : m[2]] : [a, true];
}));
const ONLY = args.only ? String(args.only).split(",").map(s => s.trim()).filter(Boolean) : null;
const LIMIT = args.limit ? parseInt(args.limit, 10) : Infinity;
const DRY = !!args.dry;
const PROBE = !!args.probe;   // этап 0: метадата-only — у кого есть кандидаты и из каких источников (без скачивания)
const FETCH = !!args.fetch;   // этап 1: скачать кандидатов + manifest.json (без API)
const APPLY = !!args.apply;   // этап 3: по verdicts.json вписать фото (без API)
const APPLY_TRUSTED = !!args["apply-trusted"]; // авто-применение wiki|mealdb из probe.json (без QA)
const FETCH_QA = !!args["fetch-qa"]; // скачать кадры Tier B (wiki/commons из probe.json) для QA-агентов
const REUSE = !!args.reuse;   // дать бесфотным вариантам фото базового блюда (по term-семье)
const QA_MODEL = args.model || "claude-sonnet-4-6";
const N_CAND = args.cand ? parseInt(args.cand, 10) : 4;       // макс. кандидатов с ОДНОГО источника
const ALL_SOURCES = ["commons", "openverse", "wikipedia", "mealdb"];
// openverse за Cloudflare JS-челленджем (403) — без headless-браузера недоступен, вне дефолта
const DEFAULT_SOURCES = ["wikipedia", "mealdb", "commons"];
const ENABLED_SOURCES = args.sources ? String(args.sources).split(",").map(s => s.trim()).filter(s => ALL_SOURCES.includes(s)) : DEFAULT_SOURCES;
const CAND_CAP = args.candcap ? parseInt(args.candcap, 10) : 8; // макс. кандидатов на рецепт после мержа всех источников
const MANIFEST = path.join(TMP, "manifest.json");
const VERDICTS = path.join(TMP, "verdicts.json");

function apiKey() {
  const env = fs.readFileSync(path.join(ROOT, ".env"), "utf8");
  const m = env.match(/^ANTHROPIC_API_KEYS=(.+)$/m);
  if (!m) throw new Error("ANTHROPIC_API_KEYS не найден в .env");
  return m[1].trim().replace(/^["']|["']$/g, "").split(",")[0].trim();
}
// ключ нужен только старому API-режиму QA; fetch/apply/dry работают на Max через Claude Code
const KEY = (DRY || PROBE || FETCH || FETCH_QA || APPLY || APPLY_TRUSTED || REUSE) ? "" : apiKey();
const PROBE_MANIFEST = path.join(TMP, "probe.json");

function loadRecipes() {
  global.window = {};
  delete require.cache[require.resolve(RECIPES_PATH)];
  require(RECIPES_PATH);
  return global.window.RECIPES;
}

// ── вписать photo для конкретного id (хирургически, без переформатирования) ──
function setPhoto(id, relPath) {
  let txt = fs.readFileSync(RECIPES_PATH, "utf8");
  const tok = `id: ${JSON.stringify(id)}`;
  const at = txt.indexOf(tok);
  if (at < 0) return false;
  const nextObj = txt.indexOf("\n  {", at + 1);
  const end = nextObj < 0 ? txt.length : nextObj;
  const rel = txt.slice(at, end).indexOf('photo: ""');
  if (rel < 0) return false;
  const abs = at + rel;
  txt = txt.slice(0, abs) + `photo: ${JSON.stringify(relPath)}` + txt.slice(abs + 'photo: ""'.length);
  fs.writeFileSync(RECIPES_PATH, txt);
  return true;
}

const sleep = ms => new Promise(r => setTimeout(r, ms));
// пул конкурентности: N воркеров тянут из общей очереди (сеть-bound — даёт x6-x10)
async function mapPool(items, conc, fn, onProgress) {
  let idx = 0, done = 0;
  async function worker() {
    while (idx < items.length) {
      const i = idx++;
      try { await fn(items[i], i); } catch {}
      done++;
      if (onProgress) onProgress(done);
    }
  }
  await Promise.all(Array.from({ length: Math.min(conc, items.length) }, worker));
}
// глобальный троттл: минимум MIN_GAP мс между любыми search-API запросами (бережём от 429)
const MIN_GAP = args.gap ? parseInt(args.gap, 10) : 150;
let _lastReq = 0;
async function throttle() {
  const now = Date.now();
  const wait = _lastReq + MIN_GAP - now;
  if (wait > 0) await sleep(wait);
  _lastReq = Date.now();
}
async function getJSON(url) {
  await throttle();
  for (let a = 1; a <= 4; a++) {
    const res = await fetch(url, { headers: { "User-Agent": UA } });
    if (res.ok) return res.json();
    if ((res.status === 429 || res.status >= 500) && a < 4) { await sleep(1000 * a); continue; }
    throw new Error("HTTP " + res.status);
  }
}
async function download(url, dest) {
  // upload.wikimedia.org троттлит — ретраи с бэкоффом на 429/5xx
  for (let a = 1; a <= 5; a++) {
    const res = await fetch(url, { headers: { "User-Agent": UA } });
    if (res.ok) {
      const buf = Buffer.from(await res.arrayBuffer());
      fs.writeFileSync(dest, buf);
      return buf;
    }
    if ((res.status === 429 || res.status >= 500) && a < 5) { await sleep(1200 * a); continue; }
    throw new Error("dl HTTP " + res.status);
  }
}

// ── Wikimedia Commons: кандидаты по названию блюда ──
const coreTitle = t => String(t).replace(/\(.*?\)/g, "").replace(/[«»"]/g, "").trim();
function widen(thumburl, px) { return thumburl ? thumburl.replace(/\/\d+px-/, `/${px}px-`) : thumburl; }

// ── HD-загрузка: upload.wikimedia.org лупит 429 на оригиналы/широкие thumb.
//    Надёжный путь — попросить рендер нужной ширины через Commons API (он отдаёт валидный thumburl ≤ оригинала). ──
function fileTitleFromUrl(u) {
  // .../commons/a/a7/Borscht_served.jpg  ИЛИ  .../commons/thumb/a/a7/Borscht_served.jpg/330px-...
  const m = String(u || "").match(/\/commons\/(?:thumb\/)?[0-9a-f]\/[0-9a-f]{2}\/([^/]+?)(?:\/\d+px-[^/]+)?$/);
  return m ? decodeURIComponent(m[1]).replace(/_/g, " ") : null;
}
async function commonsThumbUrl(fileTitle, px) {
  const api = "https://commons.wikimedia.org/w/api.php?action=query&titles="
    + encodeURIComponent("File:" + fileTitle) + "&prop=imageinfo&iiprop=url&iiurlwidth=" + px + "&format=json";
  const d = await getJSON(api);
  const p = Object.values((d.query && d.query.pages) || {})[0];
  const ii = p && p.imageinfo && p.imageinfo[0];
  return ii ? (ii.thumburl || ii.url) : null;
}
async function downloadHD(cand, dest, px) {
  px = px || 1000;
  if (cand.src === "mealdb") { await download(cand.full, dest); return; }
  // commons / wikipedia — оба файлы upload.wikimedia.org. Прямая загрузка thumb/оригинала лупит 429;
  // надёжно — попросить рендер нужной ширины через Commons API (отдаёт валидный thumburl).
  const title = fileTitleFromUrl(cand.full || cand.thumb);
  let url = null;
  if (title) { try { url = await commonsThumbUrl(title, px); } catch {} }
  await download(url || cand.thumb || cand.full, dest);
}
// батч-запись photo за один проход (избегаем гонки concurrent setPhoto на recipes.js)
function setPhotosBatch(map) {
  let txt = fs.readFileSync(RECIPES_PATH, "utf8");
  let n = 0;
  for (const [id, relPath] of Object.entries(map)) {
    const tok = `id: ${JSON.stringify(id)}`;
    const at = txt.indexOf(tok);
    if (at < 0) continue;
    const nextObj = txt.indexOf("\n  {", at + 1);
    const end = nextObj < 0 ? txt.length : nextObj;
    const rel = txt.slice(at, end).indexOf('photo: ""');
    if (rel < 0) continue; // уже проставлено (резюм) или формат иной
    const abs = at + rel;
    txt = txt.slice(0, abs) + `photo: ${JSON.stringify(relPath)}` + txt.slice(abs + 'photo: ""'.length);
    n++;
  }
  fs.writeFileSync(RECIPES_PATH, txt);
  return n;
}

async function searchCommons(recipe, term, light) {
  const core = coreTitle(recipe.title);
  // term (англ./родное название блюда из terms.json) ищется в Commons НАМНОГО лучше русского title
  let queries = term
    ? [...new Set([term, term + " dish", term + " food", core])]
    : [...new Set([core, core + " " + recipe.cuisine, recipe.title.replace(/[«»"]/g, "")])];
  if (light) queries = queries.slice(0, 1); // probe: достаточно одного запроса для детекта присутствия
  const found = new Map(); // title -> {thumb480, full}
  for (const q of queries) {
    const url = "https://commons.wikimedia.org/w/api.php?action=query&generator=search&gsrsearch="
      + encodeURIComponent(q) + "&gsrnamespace=6&gsrlimit=6&prop=imageinfo&iiprop=url|mime&iiurlwidth=480&format=json";
    let data;
    try { data = await getJSON(url); } catch { continue; }
    const pages = (data.query && data.query.pages) || {};
    for (const p of Object.values(pages)) {
      const ii = p.imageinfo && p.imageinfo[0];
      if (!ii || !/jpeg|jpg/.test(ii.mime || "")) continue;
      if (found.has(p.title)) continue;
      found.set(p.title, { thumb: ii.thumburl || ii.url, full: ii.url, src: "commons" });
      if (found.size >= N_CAND) break;
    }
    if (found.size >= N_CAND) break;
  }
  return [...found.values()];
}

// ── Openverse: CC-агрегатор (Flickr, музеи). Без ключа (анонимный rate-limit). ──
async function searchOpenverse(recipe, term) {
  const q = term || coreTitle(recipe.title);
  const url = "https://api.openverse.org/v1/images/?q=" + encodeURIComponent(q)
    + "&license_type=all-cc&extension=jpg&mature=false&page_size=6";
  const out = [];
  try {
    const data = await getJSON(url);
    for (const im of (data.results || [])) {
      const full = im.url, thumb = im.thumbnail || im.url;
      if (!full) continue;
      out.push({ thumb, full, src: "openverse" });
      if (out.length >= N_CAND) break;
    }
  } catch {}
  return out;
}

// ── Wikipedia lead image: курированное главное фото статьи блюда (REST, без ключа) ──
async function searchWikipediaLead(recipe, term, light) {
  let titles = [...new Set([term, coreTitle(recipe.title)].filter(Boolean))];
  if (light) titles = titles.slice(0, 1); // probe: только основной термин
  for (const t of titles) {
    for (const lang of ["en", "ru"]) {
      const url = `https://${lang}.wikipedia.org/api/rest_v1/page/summary/` + encodeURIComponent(t.replace(/ /g, "_"));
      try {
        const data = await getJSON(url);
        const full = data.originalimage && data.originalimage.source;
        const thumb = (data.thumbnail && data.thumbnail.source) || full;
        if (full && /\.(jpe?g|png)/i.test(full)) return [{ thumb, full, src: "wikipedia" }];
      } catch {}
    }
  }
  return [];
}

// ── TheMealDB: точное фото блюда, если оно есть в их базе (~300 блюд, без ключа) ──
async function searchMealDB(recipe, term) {
  const q = term || coreTitle(recipe.title);
  const url = "https://www.themealdb.com/api/json/v1/1/search.php?s=" + encodeURIComponent(q);
  const out = [];
  try {
    const data = await getJSON(url);
    for (const meal of (data.meals || [])) {
      if (meal.strMealThumb) out.push({ thumb: meal.strMealThumb + "/preview", full: meal.strMealThumb, src: "mealdb" });
      if (out.length >= 2) break;
    }
  } catch {}
  return out;
}

// ── собрать кандидатов из всех источников, дедуп по host+path ──
const SOURCES = { commons: searchCommons, openverse: searchOpenverse, wikipedia: searchWikipediaLead, mealdb: searchMealDB };
async function gatherCandidates(recipe, term, enabled, light) {
  const merged = [];
  const seen = new Set();
  for (const name of enabled) {
    let res = [];
    try { res = await SOURCES[name](recipe, term, light); } catch {}
    for (const c of res) {
      let key; try { const u = new URL(c.full); key = u.host + u.pathname; } catch { key = c.full; }
      if (seen.has(key)) continue;
      seen.add(key); merged.push(c);
    }
  }
  return merged;
}

// ── Sonnet-QA: выбрать лучшее, где блюдо — главный объект ──
async function qaPick(recipe, images /* [{b64}] */) {
  const content = [{
    type: "text",
    text: `Это фото-кандидаты для рецепта «${recipe.title}» (кухня: ${recipe.cuisine}, категория: ${recipe.category}).\n`
      + `Выбери индекс кадра, где САМО блюдо «${recipe.title}» — главный, узнаваемый объект, занимающий центр и БОЛЬШУЮ часть кадра, аппетитный.\n`
      + `ОТКЛОНЯЙ кадр (не выбирай его), если выполняется хоть одно:\n`
      + `— блюдо лишь основа/подложка под топпинг (икра, соус, начинка, крем), который ДОМИНИРУЕТ в кадре;\n`
      + `— в кадре доминирует гарнир, напиток, столовые приборы или посторонний предмет;\n`
      + `— есть водяные знаки, логотипы, надписи, руки людей, упаковка или вывеска;\n`
      + `— это явно НЕ то блюдо.\n`
      + `Если НИ ОДИН кадр не показывает само блюдо крупно, чисто и аппетитно — верни best = -1. Кандидаты пронумерованы с 0.`
  }];
  images.forEach((im, i) => {
    content.push({ type: "text", text: `Кандидат ${i}:` });
    content.push({ type: "image", source: { type: "base64", media_type: "image/jpeg", data: im.b64 } });
  });
  const body = {
    model: QA_MODEL, max_tokens: 300,
    tools: [{ name: "pick", description: "Выбор лучшего фото", input_schema: { type: "object", required: ["best"], properties: { best: { type: "integer" }, reason: { type: "string" } } } }],
    tool_choice: { type: "tool", name: "pick" },
    messages: [{ role: "user", content }]
  };
  for (let a = 1; a <= 4; a++) {
    const res = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST", headers: { "x-api-key": KEY, "anthropic-version": "2023-06-01", "content-type": "application/json" }, body: JSON.stringify(body)
    });
    if (res.ok) {
      const data = await res.json();
      const tool = (data.content || []).find(c => c.type === "tool_use");
      return tool ? { best: tool.input.best, reason: tool.input.reason || "" } : { best: -1 };
    }
    if (res.status === 429 || res.status >= 500) { await sleep(2000 * a); continue; }
    throw new Error("QA API " + res.status + ": " + (await res.text()).slice(0, 200));
  }
  return { best: -1 };
}

function toWebp(srcPath, destPath) {
  const PY = `import sys
from PIL import Image
src,dst=sys.argv[1],sys.argv[2]
im=Image.open(src).convert("RGB")
w,h=im.size; m=1100
if max(w,h)>m:
    s=m/max(w,h); im=im.resize((round(w*s),round(h*s)), Image.LANCZOS)
im.save(dst,"WEBP",quality=82,method=6)`;
  execFileSync("python3", ["-c", PY, srcPath, destPath], { stdio: "ignore" });
}

(async function main() {
  if (!fs.existsSync(IMG_DIR)) fs.mkdirSync(IMG_DIR, { recursive: true });
  if (!fs.existsSync(TMP)) fs.mkdirSync(TMP, { recursive: true });

  let recipes = loadRecipes();
  let pool = recipes.filter(r => !r.photo);
  if (ONLY) pool = pool.filter(r => ONLY.includes(r.cuisine));
  console.log(`Без фото: ${pool.length}${ONLY ? " (кухни: " + ONLY.join(", ") + ")" : ""}. Лимит за прогон: ${LIMIT === Infinity ? "—" : LIMIT}`);
  if (DRY) return;

  // ── ЭТАП 0: --probe — метадата-only: у кого есть кандидаты и из каких источников (без скачивания) ──
  if (PROBE) {
    const TERMS = fs.existsSync(path.join(TMP, "terms.json"))
      ? JSON.parse(fs.readFileSync(path.join(TMP, "terms.json"), "utf8")) : {};
    // резюмируемость: подхватываем уже опрошенные
    let results = fs.existsSync(PROBE_MANIFEST) ? JSON.parse(fs.readFileSync(PROBE_MANIFEST, "utf8")) : [];
    const done = new Set(results.map(x => x.id));
    const todo = pool.filter(r => !done.has(r.id));
    console.log(`PROBE: всего без фото ${pool.length}, уже опрошено ${done.size}, осталось ${todo.length}. Источники: ${ENABLED_SOURCES.join(", ")}. terms: ${Object.keys(TERMS).length}`);
    const CONC = args.conc ? parseInt(args.conc, 10) : 6;
    const base = done.size;
    const slice = todo.slice(0, LIMIT);
    await mapPool(slice, CONC, async (r) => {
      let cands;
      try { cands = await gatherCandidates(r, TERMS[r.id], ENABLED_SOURCES, true); } catch { cands = []; }
      const sources = cands.reduce((a, c) => { a[c.src] = (a[c.src] || 0) + 1; return a; }, {});
      results.push({ id: r.id, title: r.title, cuisine: r.cuisine, category: r.category,
        sources, candidates: cands.map(c => ({ thumb: c.thumb, full: c.full, src: c.src })) });
    }, (d) => { if (d % 100 === 0) { fs.writeFileSync(PROBE_MANIFEST, JSON.stringify(results)); console.log(`  …${base + d}/${pool.length}`); } });
    fs.writeFileSync(PROBE_MANIFEST, JSON.stringify(results));
    // coverage-отчёт
    const tally = { total: results.length, any: 0, wikipedia: 0, mealdb: 0, commons: 0, empty: 0, trusted: 0, commonsOnly: 0 };
    for (const x of results) {
      const has = s => (x.sources[s] || 0) > 0;
      if (has("wikipedia")) tally.wikipedia++;
      if (has("mealdb")) tally.mealdb++;
      if (has("commons")) tally.commons++;
      const trusted = has("wikipedia") || has("mealdb");
      if (trusted) tally.trusted++;
      if (!trusted && has("commons")) tally.commonsOnly++;
      if (Object.keys(x.sources).length) tally.any++; else tally.empty++;
    }
    console.log(`\n=== COVERAGE (${tally.total} рецептов) ===`);
    console.log(`  есть хоть один кандидат: ${tally.any} (${(100*tally.any/tally.total).toFixed(0)}%) | пусто: ${tally.empty}`);
    console.log(`  wikipedia-lead: ${tally.wikipedia} | mealdb: ${tally.mealdb} | commons: ${tally.commons}`);
    console.log(`  ДОВЕРЕННЫЕ (wiki|mealdb, авто-траст): ${tally.trusted} | ТОЛЬКО commons (нужен QA): ${tally.commonsOnly}`);
    console.log(`  probe.json: ${PROBE_MANIFEST}`);
    return;
  }

  // ── --reuse — бесфотным вариантам дать фото базового блюда той же term-семьи (без новых файлов) ──
  if (REUSE) {
    const TERMS = fs.existsSync(path.join(TMP, "terms.json"))
      ? JSON.parse(fs.readFileSync(path.join(TMP, "terms.json"), "utf8")) : {};
    const norm = t => String(t || "").toLowerCase().trim();
    const byTerm = {};
    for (const r of recipes) { const t = norm(TERMS[r.id] || r.title); (byTerm[t] = byTerm[t] || []).push(r); }
    const map = {}; // photolessId -> donor.photo
    for (const r of recipes) {
      if (r.photo) continue;
      const grp = byTerm[norm(TERMS[r.id] || r.title)] || [];
      const donor = grp.find(g => g.photo);
      if (donor) map[r.id] = donor.photo; // делим тот же webp-путь
    }
    const n = setPhotosBatch(map);
    console.log(`REUSE: семей-доноров использовано, вписано ${n} фото (переиспользование, без новых файлов).`);
    console.log(`Осталось без фото: ${loadRecipes().filter(r => !r.photo).length}`);
    return;
  }

  // ── --apply-trusted — авто-применение wiki|mealdb из probe.json (без QA, тиринг по доверию) ──
  if (APPLY_TRUSTED) {
    if (!fs.existsSync(PROBE_MANIFEST)) throw new Error("нет probe.json — сначала --probe");
    const probe = JSON.parse(fs.readFileSync(PROBE_MANIFEST, "utf8"));
    const photoless = new Set(recipes.filter(r => !r.photo).map(r => r.id));
    // --require=mealdb — только Tier A (надёжный авто-траст). По умолчанию любой trusted.
    const REQUIRE = args.require ? String(args.require) : null;
    let targets = probe.filter(x => photoless.has(x.id) && (REQUIRE
      ? x.candidates.some(c => c.src === REQUIRE)
      : x.candidates.some(c => c.src === "wikipedia" || c.src === "mealdb")));
    if (ONLY) targets = targets.filter(x => ONLY.includes(x.cuisine));
    targets = targets.slice(0, LIMIT);
    const CONC = args.conc ? parseInt(args.conc, 10) : 5;
    console.log(`APPLY-TRUSTED: к применению ${targets.length}${REQUIRE ? " (только " + REQUIRE + ")" : " (wiki|mealdb)"}. conc=${CONC}`);
    const applied = {}; // id -> relPath (батч-запись)
    let ok = 0, fail = 0;
    const flush = () => { const n = setPhotosBatch(applied); if (n) console.log(`    batch: вписано ${n}`); };
    await mapPool(targets, CONC, async (x) => {
      // предпочтение mealdb (надёжный матч блюда), затем wiki
      const pref = REQUIRE ? [REQUIRE] : ["mealdb", "wikipedia"];
      const cand = pref.map(s => x.candidates.find(c => c.src === s)).find(Boolean);
      const tmp = path.join(TMP, `hd_${x.id}.jpg`);
      try {
        await downloadHD(cand, tmp);
        const out = path.join(IMG_DIR, `${x.id}.webp`);
        toWebp(tmp, out);
        try { fs.unlinkSync(tmp); } catch {}
        applied[x.id] = `img/recipes/${x.id}.webp?v=1`;
        ok++;
      } catch (e) { fail++; }
    }, (d) => { if (d % 100 === 0) { flush(); console.log(`  …${d}/${targets.length} (ok ${ok} fail ${fail})`); } });
    flush();
    console.log(`\nAPPLY-TRUSTED готов. Применено: ${ok} | ошибок: ${fail}`);
    console.log(`Осталось без фото: ${loadRecipes().filter(r => !r.photo).length}`);
    return;
  }

  // ── --fetch-qa — скачать кадры Tier B (wiki/commons из probe.json) для QA-агентов (резюмируемо) ──
  if (FETCH_QA) {
    if (!fs.existsSync(PROBE_MANIFEST)) throw new Error("нет probe.json — сначала --probe");
    const probe = JSON.parse(fs.readFileSync(PROBE_MANIFEST, "utf8"));
    const photoless = new Set(recipes.filter(r => !r.photo).map(r => r.id));
    let manifest = fs.existsSync(MANIFEST) ? JSON.parse(fs.readFileSync(MANIFEST, "utf8")) : [];
    const done = new Set(manifest.map(m => m.id));
    // Tier B: photoless, есть кандидаты, mealdb уже применён (Tier A) → берём wiki/commons
    let targets = probe.filter(x => photoless.has(x.id) && x.candidates.length
      && !x.candidates.some(c => c.src === "mealdb") && !done.has(x.id));
    if (ONLY) targets = targets.filter(x => ONLY.includes(x.cuisine));
    targets = targets.slice(0, LIMIT);
    const CONC = args.conc ? parseInt(args.conc, 10) : 4;
    const QADIR = path.join(TMP, "qa");
    if (!fs.existsSync(QADIR)) fs.mkdirSync(QADIR, { recursive: true });
    console.log(`FETCH-QA: уже скачано ${done.size}, к загрузке ${targets.length}. conc=${CONC}`);
    let nF = 0, nE = 0;
    await mapPool(targets, CONC, async (x) => {
      const dir = path.join(QADIR, x.id);
      if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
      const cands = [];
      for (let i = 0; i < x.candidates.length; i++) {
        const c = x.candidates[i];
        const file = path.join(dir, `c${i}.jpg`);
        // надёжная загрузка QA-превью через Commons API (480px), а не прямой thumb (429)
        try { await downloadHD(c, file, 480); cands.push({ i, file, thumb: c.thumb, full: c.full, src: c.src }); } catch {}
      }
      if (cands.length) { cands.forEach((c, k) => c.i = k); manifest.push({ id: x.id, title: x.title, cuisine: x.cuisine, category: x.category, candidates: cands }); nF++; }
      else nE++;
    }, (d) => { if (d % 50 === 0) { fs.writeFileSync(MANIFEST, JSON.stringify(manifest, null, 2)); console.log(`  …${d}/${targets.length} (ok ${nF})`); } });
    fs.writeFileSync(MANIFEST, JSON.stringify(manifest, null, 2));
    console.log(`\nFETCH-QA готов. С кадрами: ${manifest.length} | пропущено: ${nE}. Манифест: ${MANIFEST}`);
    return;
  }

  // ── ЭТАП 1: --fetch — скачать кандидатов + manifest (без API; QA делает Claude Code на Max) ──
  if (FETCH) {
    const TERMS = fs.existsSync(path.join(TMP, "terms.json"))
      ? JSON.parse(fs.readFileSync(path.join(TMP, "terms.json"), "utf8")) : {};
    // если термины заданы — обрабатываем ТОЛЬКО рецепты из terms.json (точный контроль батча)
    if (Object.keys(TERMS).length) pool = pool.filter(r => TERMS[r.id]);
    console.log(`К обработке: ${pool.length}${Object.keys(TERMS).length ? " (по terms.json)" : ""}`);
    console.log(`Источники: ${ENABLED_SOURCES.join(", ")}`);
    const manifest = [];
    let nF = 0, nE = 0, processed = 0;
    for (const r of pool) {
      if (processed >= LIMIT) break;
      processed++;
      let cands;
      try { cands = await gatherCandidates(r, TERMS[r.id], ENABLED_SOURCES); } catch { cands = []; }
      cands = cands.slice(0, CAND_CAP);
      if (!cands.length) { nE++; console.log(`  ∅ ${r.title} — нет кандидатов`); continue; }
      const dir = path.join(TMP, r.id);
      if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
      const candidates = [];
      for (let i = 0; i < cands.length; i++) {
        const file = path.join(dir, `c${i}.jpg`);
        try { await download(cands[i].thumb, file); candidates.push({ i, file, thumb: cands[i].thumb, full: cands[i].full, src: cands[i].src }); }
        catch {}
        await sleep(250);
      }
      if (!candidates.length) { nE++; console.log(`  ∅ ${r.title} — не скачалось`); continue; }
      // переиндексируем (i = позиция в скачанном списке), чтобы verdicts совпадали с файлами cN.jpg
      candidates.forEach((c, k) => c.i = k);
      const bySrc = candidates.reduce((a, c) => { a[c.src] = (a[c.src] || 0) + 1; return a; }, {});
      manifest.push({ id: r.id, title: r.title, cuisine: r.cuisine, category: r.category, candidates });
      nF++; console.log(`  • ${r.title} — ${candidates.length} канд. [${Object.entries(bySrc).map(([s, n]) => s + ":" + n).join(" ")}]`);
    }
    fs.writeFileSync(MANIFEST, JSON.stringify(manifest, null, 2));
    console.log(`\nFETCH готов. Рецептов с кандидатами: ${nF} | без: ${nE}`);
    console.log(`Манифест: ${MANIFEST}`);
    console.log(`Дальше: Claude Code читает кадры, пишет ${VERDICTS} ({"<id>": <индекс лучшего | -1>}), затем --apply.`);
    return;
  }

  // ── ЭТАП 3: --apply — по verdicts.json вписать выбранные фото (без API) ──
  if (APPLY) {
    if (!fs.existsSync(MANIFEST) || !fs.existsSync(VERDICTS)) throw new Error("нет manifest.json/verdicts.json в .photo_tmp");
    const manifest = JSON.parse(fs.readFileSync(MANIFEST, "utf8"));
    const verdicts = JSON.parse(fs.readFileSync(VERDICTS, "utf8"));
    let ok = 0, skip = 0;
    for (const m of manifest) {
      const v = verdicts[m.id];
      if (v == null || v < 0 || v >= m.candidates.length) { skip++; console.log(`  ✗ ${m.title} — пропуск (verdict=${v})`); continue; }
      const chosen = m.candidates[v];
      try {
        const full = path.join(TMP, `hd_${m.id}.jpg`);
        // HD через Commons API thumburl (downloadHD), фолбэк — локальное превью (для карточки ~440px достаточно)
        let src = null;
        try { await downloadHD(chosen, full); src = full; } catch {}
        if (!src && chosen.file && fs.existsSync(chosen.file)) { src = chosen.file; console.log(`    (HD недоступен — беру локальное превью)`); }
        if (!src) throw new Error("HD недоступен и нет локального превью");
        const out = path.join(IMG_DIR, `${m.id}.webp`);
        toWebp(src, out);
        const kb = Math.round(fs.statSync(out).size / 1024);
        if (setPhoto(m.id, `img/recipes/${m.id}.webp?v=1`)) { ok++; console.log(`  ✓ ${m.title} → ${m.id}.webp (${kb}KB)`); }
        else console.log(`  ! ${m.title} — не удалось вписать photo`);
      } catch (e) { console.log(`  ! ${m.title} — ${e.message}`); }
    }
    console.log(`\nAPPLY готов. Вписано: ${ok} | пропущено: ${skip}`);
    console.log(`Осталось без фото: ${loadRecipes().filter(r => !r.photo).length}`);
    return;
  }

  let done = 0, ok = 0, noCand = 0, rejected = 0, processed = 0;
  for (const r of pool) {
    if (processed >= LIMIT) break;
    processed++;
    let cands;
    try { cands = await searchCommons(r); } catch (e) { cands = []; }
    if (!cands.length) { noCand++; console.log(`  ∅ ${r.title} — нет кандидатов`); continue; }

    // скачать thumbs (480) для QA
    const imgs = [];
    for (let i = 0; i < cands.length; i++) {
      try {
        const buf = await download(cands[i].thumb, path.join(TMP, `c${i}.jpg`));
        imgs.push({ b64: buf.toString("base64"), cand: cands[i] });
      } catch {}
    }
    if (!imgs.length) { noCand++; console.log(`  ∅ ${r.title} — кандидаты не скачались`); continue; }

    let verdict;
    try { verdict = await qaPick(r, imgs); }
    catch (e) { console.log(`  ! ${r.title} — QA ошибка: ${e.message}`); continue; }

    if (verdict.best == null || verdict.best < 0 || verdict.best >= imgs.length) {
      rejected++; console.log(`  ✗ ${r.title} — QA отклонил (${verdict.reason || "нет подходящих"})`); continue;
    }
    const chosen = imgs[verdict.best].cand;
    try {
      const full = path.join(TMP, "full.jpg");
      await download(widen(chosen.thumb, 1100) || chosen.full, full);
      const out = path.join(IMG_DIR, `${r.id}.webp`);
      toWebp(full, out);
      const kb = Math.round(fs.statSync(out).size / 1024);
      if (setPhoto(r.id, `img/recipes/${r.id}.webp?v=1`)) { ok++; console.log(`  ✓ ${r.title} → ${r.id}.webp (${kb}KB)`); }
      else console.log(`  ! ${r.title} — не удалось вписать photo`);
    } catch (e) { console.log(`  ! ${r.title} — обработка фото: ${e.message}`); }
    done++;
  }
  console.log(`\nГОТОВО. Обработано: ${processed} | фото добавлено: ${ok} | нет кандидатов: ${noCand} | QA отклонил: ${rejected}`);
  console.log(`Осталось без фото: ${loadRecipes().filter(r => !r.photo).length}`);
})();
