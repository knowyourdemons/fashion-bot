#!/usr/bin/env node
/*
 * AI-фото для бесфотных рецептов через Cloudflare Workers AI ($0 free tier).
 * Пайплайн: Llama (рецепт → визуальный промпт) → FLUX schnell (картинка) → QA (Claude Code) → apply+reuse.
 * Family-aware: 1 генерация на term-семью, фото раздаётся всем членам (как gen_recipe_photos --reuse).
 * Резюмируемо (источник истины — recipes.js + aigen_manifest.json).
 *
 * Usage:
 *   node scripts/gen_ai_photos.js --gen --limit=40 [--minfam=2]   # генерация (Llama+FLUX) для N семей
 *   # → Claude Code читает .photo_tmp/aigen/<repId>.jpg, пишет .photo_tmp/aigen_verdicts.json {repId: "ok"|"bad"}
 *   node scripts/gen_ai_photos.js --apply                          # webp + setPhoto для одобренных + reuse семье
 *   node scripts/gen_ai_photos.js --dry                            # сколько семей без фото
 */
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

const ROOT = path.resolve(__dirname, "..");
const RECIPES_PATH = path.join(ROOT, "landing/data/recipes.js");
const IMG_DIR = path.join(ROOT, "landing/img/recipes");
const TMP = path.join(ROOT, ".photo_tmp");
const AIGEN_DIR = path.join(TMP, "aigen");
const MANIFEST = path.join(TMP, "aigen_manifest.json");
const VERDICTS = path.join(TMP, "aigen_verdicts.json");
const TERMS = path.join(TMP, "terms.json");

const args = Object.fromEntries(process.argv.slice(2).map(a => {
  const m = a.match(/^--([^=]+)(?:=(.*))?$/);
  return m ? [m[1], m[2] === undefined ? true : m[2]] : [a, true];
}));
const LIMIT = args.limit ? parseInt(args.limit, 10) : Infinity;
const MINFAM = args.minfam ? parseInt(args.minfam, 10) : 1;
const CONC = args.conc ? parseInt(args.conc, 10) : 3;
const STEPS = args.steps ? parseInt(args.steps, 10) : 6;
const PROMPT_MODEL = args.promptmodel || "@cf/meta/llama-3.3-70b-instruct-fp8-fast";

function env(key) {
  const m = fs.readFileSync(path.join(ROOT, ".env"), "utf8").match(new RegExp("^" + key + "=(.+)$", "m"));
  return m ? m[1].trim() : "";
}
const ACCT = env("CLOUDFLARE_ACCOUNT_ID") || (env("CLOUDFLARE_R2_ENDPOINT").match(/[0-9a-f]{32}/) || [""])[0];
const TOKEN = env("CLOUDFLARE_API_TOKEN");
const CF = (model) => `https://api.cloudflare.com/client/v4/accounts/${ACCT}/ai/run/${model}`;

const sleep = ms => new Promise(r => setTimeout(r, ms));
function loadRecipes() { global.window = {}; delete require.cache[require.resolve(RECIPES_PATH)]; require(RECIPES_PATH); return global.window.RECIPES; }
const norm = t => String(t || "").toLowerCase().trim();

async function cfRun(model, payload, tries = 4) {
  for (let a = 1; a <= tries; a++) {
    try {
      const r = await fetch(CF(model), { method: "POST", headers: { Authorization: "Bearer " + TOKEN, "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      if (r.ok) return r.json();
      if ((r.status === 429 || r.status >= 500) && a < tries) { await sleep(1500 * a); continue; }
      throw new Error("CF " + r.status + " " + (await r.text()).slice(0, 120));
    } catch (e) { if (a >= tries) throw e; await sleep(1500 * a); }
  }
}

// Llama: рецепт → визуальный англ-промпт (описание ВИДА блюда, не иностранного имени)
const PROMPT_SYS =
  "You write image-generation prompts for food photos. Given a dish (Russian title, cuisine, ingredients), " +
  "output ONE concise English sentence describing how the FINISHED dish LOOKS: its form, main visible components, " +
  "color, the vessel (plate/bowl/glass), and garnish. Describe APPEARANCE, do not just repeat a foreign dish name " +
  "the image model won't know. No measurements, no preamble. End the sentence with: " +
  "', professional food photography, top-down, natural daylight, appetizing, high detail, no text'.";

async function llamaPrompt(r) {
  const ings = (r.ingredients || []).slice(0, 8).map(i => i.name).join(", ");
  const user = `Dish: ${r.title}. Cuisine: ${r.cuisine}. Category: ${r.category}. Main ingredients: ${ings}.`;
  const res = await cfRun(PROMPT_MODEL, { messages: [{ role: "system", content: PROMPT_SYS }, { role: "user", content: user }], max_tokens: 160 });
  let out = res.result && res.result.response;
  if (out && typeof out === "object") out = JSON.stringify(out);
  out = String(out || "").trim().replace(/^["']|["']$/g, "");
  return out || `${r.title}, professional food photography, top-down, natural daylight, appetizing`;
}

async function fluxGen(prompt) {
  const res = await cfRun("@cf/black-forest-labs/flux-1-schnell", { prompt, steps: STEPS });
  if (!res.result || !res.result.image) throw new Error("no image");
  return Buffer.from(res.result.image, "base64");
}

function toWebp(srcPath, destPath) {
  const PY = `import sys
from PIL import Image
im=Image.open(sys.argv[1]).convert("RGB")
w,h=im.size; m=1024
if max(w,h)>m:
    s=m/max(w,h); im=im.resize((round(w*s),round(h*s)), Image.LANCZOS)
im.save(sys.argv[2],"WEBP",quality=82,method=6)`;
  execFileSync("python3", ["-c", PY, srcPath, destPath], { stdio: "ignore" });
}

// батч-запись photo (избегаем гонки)
function setPhotosBatch(map) {
  let txt = fs.readFileSync(RECIPES_PATH, "utf8"); let n = 0;
  for (const [id, rel] of Object.entries(map)) {
    const at = txt.indexOf(`id: ${JSON.stringify(id)},`);
    if (at < 0) continue;
    const nextObj = txt.indexOf("\n  {", at + 1); const end = nextObj < 0 ? txt.length : nextObj;
    const seg = txt.slice(at, end); const rel2 = seg.indexOf('photo: ""');
    if (rel2 < 0) continue;
    const abs = at + rel2;
    txt = txt.slice(0, abs) + `photo: ${JSON.stringify(rel)}` + txt.slice(abs + 'photo: ""'.length); n++;
  }
  fs.writeFileSync(RECIPES_PATH, txt); return n;
}

async function mapPool(items, conc, fn, onProgress) {
  let idx = 0, done = 0;
  async function worker() { while (idx < items.length) { const i = idx++; try { await fn(items[i], i); } catch {} done++; if (onProgress) onProgress(done); } }
  await Promise.all(Array.from({ length: Math.min(conc, items.length) }, worker));
}

function families(recipes, terms) {
  const fam = {};
  for (const r of recipes) { if (r.photo) continue; const t = norm(terms[r.id] || r.title); (fam[t] = fam[t] || []).push(r); }
  return fam;
}

(async function main() {
  if (!ACCT || !TOKEN) throw new Error("нет CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN в .env");
  for (const d of [AIGEN_DIR]) if (!fs.existsSync(d)) fs.mkdirSync(d, { recursive: true });
  const terms = fs.existsSync(TERMS) ? JSON.parse(fs.readFileSync(TERMS, "utf8")) : {};
  const recipes = loadRecipes();
  const fam = families(recipes, terms);
  const score = r => (r.ingredients || []).length + (r.steps || []).length;
  // представитель семьи = самый детальный
  let famList = Object.entries(fam).filter(([, a]) => a.length >= MINFAM)
    .map(([k, a]) => ({ key: k, rep: a.slice().sort((x, y) => score(y) - score(x))[0], members: a.map(r => r.id) }))
    .sort((x, y) => y.members.length - x.members.length); // большие семьи первыми

  if (args.dry) {
    console.log(`Бесфотных: ${recipes.filter(r => !r.photo).length} | семей(>=${MINFAM}): ${famList.length} | покрывают ${famList.reduce((s, f) => s + f.members.length, 0)} рецептов`);
    return;
  }

  if (args.gen) {
    let manifest = fs.existsSync(MANIFEST) ? JSON.parse(fs.readFileSync(MANIFEST, "utf8")) : [];
    const done = new Set(manifest.map(m => m.repId));
    const todo = famList.filter(f => !done.has(f.rep.id)).slice(0, LIMIT);
    console.log(`AIGEN: уже ${done.size}, к генерации ${todo.length} семей. модель промпта: ${PROMPT_MODEL}, FLUX steps: ${STEPS}, conc: ${CONC}`);
    let ok = 0, fail = 0;
    await mapPool(todo, CONC, async (f) => {
      try {
        const prompt = await llamaPrompt(f.rep);
        const buf = await fluxGen(prompt);
        const file = path.join(AIGEN_DIR, `${f.rep.id}.jpg`);
        fs.writeFileSync(file, buf);
        manifest.push({ repId: f.rep.id, famKey: f.key, title: f.rep.title, cuisine: f.rep.cuisine, category: f.rep.category, members: f.members, prompt, file });
        ok++;
      } catch (e) { fail++; }
    }, d => { if (d % 20 === 0) { fs.writeFileSync(MANIFEST, JSON.stringify(manifest, null, 2)); console.log(`  …${d}/${todo.length} (ok ${ok} fail ${fail})`); } });
    fs.writeFileSync(MANIFEST, JSON.stringify(manifest, null, 2));
    console.log(`\nAIGEN готов. Сгенерено: ${ok} | ошибок: ${fail} | манифест: ${MANIFEST}`);
    console.log(`Дальше: Claude Code читает кадры, пишет ${VERDICTS} ({"<repId>": "ok"|"bad"}), затем --apply.`);
    return;
  }

  if (args.apply) {
    if (!fs.existsSync(MANIFEST) || !fs.existsSync(VERDICTS)) throw new Error("нет aigen_manifest.json / aigen_verdicts.json");
    const manifest = JSON.parse(fs.readFileSync(MANIFEST, "utf8"));
    const verdicts = JSON.parse(fs.readFileSync(VERDICTS, "utf8"));
    const photoless = new Set(recipes.filter(r => !r.photo).map(r => r.id));
    const applied = {}; let ok = 0, skip = 0, bad = 0;
    for (const m of manifest) {
      const v = verdicts[m.repId];
      if (v !== "ok") { if (v === "bad") bad++; else skip++; continue; }
      try {
        const out = path.join(IMG_DIR, `${m.repId}.webp`);
        toWebp(m.file, out);
        const rel = `img/recipes/${m.repId}.webp?v=1`;
        // фото — представителю и всем живым членам семьи без фото (reuse)
        for (const id of m.members) if (photoless.has(id)) applied[id] = rel;
        ok++;
      } catch (e) { skip++; }
    }
    const n = setPhotosBatch(applied);
    console.log(`AIGEN-APPLY: одобрено семей ${ok} (bad ${bad}, skip ${skip}) → вписано фото ${n} рецептам (с reuse).`);
    console.log(`Осталось без фото: ${loadRecipes().filter(r => !r.photo).length}`);
    return;
  }

  console.log("укажи режим: --dry | --gen | --apply");
})();
