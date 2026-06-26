/* ============================================================
   AI-ассистент: чат с фото + импорт рецептов.
   Клиент к бэкенду /api/v1/cookbook/* (Vision+Haiku через AnthropicPool).
   UI диалога: полноэкранная вьюха #/assistant и оверлей с ингредиента.
   Состояние диалога — localStorage cb_assistant.
   ============================================================ */
(function () {
  'use strict';

  const API = "/api/v1/cookbook";
  const SECRET_KEY = "cb_secret";

  function getSecret() {
    let s = localStorage.getItem(SECRET_KEY);
    if (!s) { s = prompt("Код доступа к ассистенту (один раз):") || ""; if (s) localStorage.setItem(SECRET_KEY, s); }
    return s;
  }
  function authHeaders() { return { "X-Cookbook-Secret": getSecret() }; }

  function loadHistory() { try { return JSON.parse(localStorage.getItem("cb_assistant") || "[]"); } catch (e) { return []; } }
  function saveHistory(h) { try { localStorage.setItem("cb_assistant", JSON.stringify(h.slice(-40))); } catch (e) {} }

  function fileToDataURL(file) {
    return new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(file); });
  }
  function esc(s) { return window.Cookbook ? window.Cookbook.esc(s) : String(s); }

  /* ---------- API ---------- */
  async function callAssistant(payload) {
    const fd = new FormData();
    fd.append("message", payload.message || "");
    fd.append("context", JSON.stringify(payload.context || {}));
    fd.append("history", JSON.stringify(payload.history || []));
    (payload.files || []).forEach((f, i) => fd.append("photos", f, f.name || ("photo" + i + ".jpg")));
    const resp = await fetch(API + "/assistant", { method: "POST", headers: authHeaders(), body: fd });
    if (resp.status === 401) { localStorage.removeItem(SECRET_KEY); throw new Error("Неверный код доступа"); }
    if (resp.status === 429) throw new Error("Лимит запросов на сегодня исчерпан");
    if (!resp.ok) throw new Error("Сервер недоступен (" + resp.status + ")");
    return resp.json(); // { reply, substitution? }
  }
  async function importUrl(url) {
    const resp = await fetch(API + "/import", { method: "POST", headers: Object.assign({ "Content-Type": "application/json" }, authHeaders()), body: JSON.stringify({ url }) });
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    return (await resp.json()).recipe;
  }
  async function importPhoto(file) {
    const fd = new FormData(); fd.append("photo", file, file.name || "page.jpg");
    const resp = await fetch(API + "/import", { method: "POST", headers: authHeaders(), body: fd });
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    return (await resp.json()).recipe;
  }

  /* ---------- Рендер сообщений ---------- */
  function msgHtml(m) {
    if (m.role === "substitution") {
      const s = m.sub;
      return `<div class="sub-card">
        <div class="label">Предложена замена</div>
        <p><b>${esc(s.original)}</b> → <b>${esc(s.replacement)}</b></p>
        ${s.note ? `<p class="muted">${esc(s.note)}</p>` : ""}
        <div class="btn-row" style="margin-top:8px">
          <button class="btn sm primary" data-applysub='${esc(JSON.stringify(s))}'>Применить</button>
          <button class="btn sm" data-notesub='${esc(JSON.stringify(s))}'>В заметки</button>
        </div>
      </div>`;
    }
    const imgs = (m.images || []).map(src => `<img src="${esc(src)}" alt="">`).join("");
    return `<div class="msg ${m.role === "user" ? "user" : "bot"}">${esc(m.text || "")}${imgs}</div>`;
  }

  /* ---------- Полноэкранная вьюха ---------- */
  function renderView(container, ctx) {
    const history = loadHistory();
    container.innerHTML = `
      <div class="section-head"><h2>Ассистент</h2><a href="#/" class="btn ghost sm" style="margin-left:auto">К списку</a></div>
      <p class="muted" style="margin-bottom:8px">Сфоткайте товар в магазине и спросите «то ли это?», обсудите замену — как в чате.</p>
      <div class="chat" id="chat">${history.map(msgHtml).join("")}</div>
      <div class="chat-input">
        <form id="chatForm">
          <label class="iconbtn" title="Фото">📷<input id="chatPhoto" type="file" accept="image/*" capture="environment" multiple class="hidden"></label>
          <input id="chatText" type="text" placeholder="Спросить ассистента…" autocomplete="off">
          <button class="iconbtn" type="submit">➤</button>
        </form>
      </div>
      <div class="thumb-strip" id="thumbs" style="position:fixed;bottom:74px;left:16px;right:16px;max-width:760px;margin:0 auto"></div>
    `;
    wireChat(container, ctx || {});
    scrollChat();
  }

  /* ---------- Оверлей с ингредиента ---------- */
  function openOverlay(ctx) {
    const ov = document.createElement("div"); ov.className = "overlay"; ov.id = "assistOverlay";
    ov.innerHTML = `<div class="sheet" style="max-height:90vh;display:flex;flex-direction:column">
      <button class="btn ghost sm sheet-close" id="aClose">Закрыть</button>
      <h3>Спросить про: ${esc(ctx.ingredient ? ctx.ingredient.name : (ctx.recipe ? ctx.recipe.title : ""))}</h3>
      <div class="chat" id="chat" style="flex:1;overflow-y:auto;padding-bottom:10px"></div>
      <form id="chatForm" style="display:flex;gap:10px;align-items:center;border-top:1px solid var(--line);padding-top:10px">
        <label class="iconbtn" title="Фото">📷<input id="chatPhoto" type="file" accept="image/*" capture="environment" multiple class="hidden"></label>
        <input id="chatText" type="text" placeholder="Это подойдёт? Чем заменить?" autocomplete="off" style="flex:1;height:46px;padding:0 14px;border:1px solid var(--line);border-radius:999px;background:var(--white-warm)">
        <button class="iconbtn" type="submit">➤</button>
      </form>
      <div class="thumb-strip" id="thumbs" style="margin-top:8px"></div>
    </div>`;
    document.body.appendChild(ov);
    ov.addEventListener("click", e => { if (e.target === ov) ov.remove(); });
    document.getElementById("aClose").onclick = () => ov.remove();
    // первичная подсказка
    const chat = ov.querySelector("#chat");
    chat.innerHTML = msgHtml({ role: "bot", text: ctx.ingredient ? `Спросите про «${ctx.ingredient.name}» — пришлите фото товара с полки, подскажу то это или нет и чем заменить.` : "Чем помочь по рецепту?" });
    wireChat(ov, ctx, true);
  }

  /* ---------- Общая логика чата ---------- */
  function wireChat(root, ctx, isOverlay) {
    const chat = root.querySelector("#chat");
    const text = root.querySelector("#chatText");
    const photo = root.querySelector("#chatPhoto");
    const thumbs = root.querySelector("#thumbs");
    const form = root.querySelector("#chatForm");
    let pending = []; // File[]

    photo.addEventListener("change", async () => {
      for (const f of photo.files) pending.push(f);
      photo.value = "";
      thumbs.innerHTML = "";
      for (const f of pending) { const url = await fileToDataURL(f); const img = document.createElement("img"); img.src = url; thumbs.appendChild(img); }
    });

    bindSubButtons(root, ctx);

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const message = text.value.trim();
      if (!message && !pending.length) return;
      const imgUrls = [];
      for (const f of pending) imgUrls.push(await fileToDataURL(f));
      // показать сообщение юзера
      appendMsg(chat, { role: "user", text: message, images: imgUrls });
      const history = isOverlay ? [] : loadHistory();
      if (!isOverlay) { history.push({ role: "user", text: message }); saveHistory(history); }
      text.value = ""; const sending = pending; pending = []; thumbs.innerHTML = "";
      const typing = appendMsg(chat, { role: "bot", text: "…" });

      try {
        const ctxPayload = {
          recipe: ctx.recipe ? { id: ctx.recipe.id, title: ctx.recipe.title, ingredients: ctx.recipe.ingredients } : null,
          ingredient: ctx.ingredient || null
        };
        const res = await callAssistant({ message, files: sending, context: ctxPayload, history: (isOverlay ? [] : history.slice(-10)) });
        typing.remove();
        appendMsg(chat, { role: "bot", text: res.reply || "(пустой ответ)" });
        if (!isOverlay) { history.push({ role: "bot", text: res.reply }); saveHistory(history); }
        if (res.substitution) {
          const sub = Object.assign({}, res.substitution);
          if (ctx.recipe) sub._recipeId = ctx.recipe.id;
          const node = appendMsg(chat, { role: "substitution", sub });
          bindSubButtons(root, ctx);
        }
      } catch (err) {
        typing.remove();
        appendMsg(chat, { role: "bot", text: "⚠ " + err.message + "\n(Ассистенту нужен запущенный бэкенд и код доступа.)" });
      }
      scrollChat(chat);
    });
  }

  function bindSubButtons(root, ctx) {
    root.querySelectorAll("[data-applysub]").forEach(b => b.onclick = () => {
      const sub = JSON.parse(b.dataset.applysub);
      if (window.Cookbook) window.Cookbook.applySubstitution(ctx.recipe ? ctx.recipe.id : sub._recipeId, sub);
    });
    root.querySelectorAll("[data-notesub]").forEach(b => b.onclick = () => {
      const sub = JSON.parse(b.dataset.notesub);
      if (window.Cookbook && (ctx.recipe || sub._recipeId)) {
        window.Cookbook.applySubstitution(ctx.recipe ? ctx.recipe.id : sub._recipeId, { original: sub.original, replacement: sub.replacement, note: sub.note });
      }
    });
  }

  function appendMsg(chat, m) {
    const wrap = document.createElement("div");
    wrap.innerHTML = msgHtml(m);
    const node = wrap.firstElementChild;
    chat.appendChild(node);
    scrollChat(chat);
    return node;
  }
  function scrollChat(chat) {
    chat = chat || document.getElementById("chat");
    if (chat) chat.scrollTop = chat.scrollHeight;
    else window.scrollTo(0, document.body.scrollHeight);
  }

  window.CookAssistant = { renderView, openOverlay, importUrl, importPhoto };
})();
