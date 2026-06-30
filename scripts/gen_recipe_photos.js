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
const FETCH = !!args.fetch;   // этап 1: скачать кандидатов + manifest.json (без API)
const APPLY = !!args.apply;   // этап 3: по verdicts.json вписать фото (без API)
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
const KEY = (DRY || FETCH || APPLY) ? "" : apiKey();

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
async function getJSON(url) {
  const res = await fetch(url, { headers: { "User-Agent": UA } });
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.json();
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

async function searchCommons(recipe, term) {
  const core = coreTitle(recipe.title);
  // term (англ./родное название блюда из terms.json) ищется в Commons НАМНОГО лучше русского title
  const queries = term
    ? [...new Set([term, term + " dish", term + " food", core])]
    : [...new Set([core, core + " " + recipe.cuisine, recipe.title.replace(/[«»"]/g, "")])];
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
async function searchWikipediaLead(recipe, term) {
  const titles = [...new Set([term, coreTitle(recipe.title)].filter(Boolean))];
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
async function gatherCandidates(recipe, term, enabled) {
  const merged = [];
  const seen = new Set();
  for (const name of enabled) {
    let res = [];
    try { res = await SOURCES[name](recipe, term); } catch {}
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
        const full = path.join(TMP, "full.jpg");
        // Commons: thumb можно расширить до 1100px через URL. Остальные источники — берём full напрямую.
        const urls = chosen.src === "commons"
          ? [...new Set([widen(chosen.thumb, 1100), widen(chosen.thumb, 800), chosen.full].filter(Boolean))]
          : [...new Set([chosen.full, chosen.thumb].filter(Boolean))];
        let src = null;
        for (const u of urls) { try { await download(u, full); src = full; break; } catch {} }
        // фолбэк: уже скачанное 480px-превью (для карточки ~440px достаточно)
        if (!src && fs.existsSync(chosen.file)) { src = chosen.file; console.log(`    (HD недоступен — беру локальное превью)`); }
        if (!src) throw new Error("все URL дали ошибку и нет локального превью");
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
