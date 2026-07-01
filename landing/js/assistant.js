/* ============================================================
   AI-ассистент: чат с фото + импорт рецептов.
   Клиент к бэкенду /api/v1/cookbook/* (Vision+Haiku через AnthropicPool).
   UI диалога: полноэкранная вьюха #/assistant и оверлей с ингредиента.
   Состояние диалога — localStorage cb_assistant.
   ============================================================ */
(function () {
  'use strict';

  const API = "/api/v1/cookbook";
  const SESSION_KEY = "cb_session_token";
  const SECRET_KEY = "cb_secret"; // тихий фолбэк (file:// / ручная установка)

  let _config = null;
  async function getConfig() {
    if (_config) return _config;
    try { const r = await fetch(API + "/config"); _config = await r.json(); }
    catch (e) { _config = { botUsername: "", ssoEnabled: false }; }
    return _config;
  }
  function getSession() { return localStorage.getItem(SESSION_KEY) || ""; }
  function getSecret() { return localStorage.getItem(SECRET_KEY) || ""; }
  function isAuthed() { return !!getSession() || !!getSecret(); }
  function authHeaders() {
    const h = {};
    const s = getSession(); if (s) h["X-Cookbook-Session"] = s;
    const sec = getSecret(); if (sec) h["X-Cookbook-Secret"] = sec;
    return h;
  }
  function clearSession() { localStorage.removeItem(SESSION_KEY); }

  // Telegram Login Widget → /auth/telegram → сессия
  window.onTelegramAuth = async function (user) {
    try {
      const r = await fetch(API + "/auth/telegram", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(user)
      });
      if (!r.ok) {
        const msg = r.status === 403 ? "Этому аккаунту вход не разрешён" : "Не удалось войти";
        alert(msg); return;
      }
      const data = await r.json();
      localStorage.setItem(SESSION_KEY, data.token);
      // Оповещаем ВСЕ открытые экраны логина (полный вид + оверлей): каждый
      // перерисовывает свой контекст. Единый window._cbOnLogin ломался, когда
      // второй гейт перезаписывал колбэк первого и видимая кнопка не пропадала.
      window.dispatchEvent(new CustomEvent("cb-auth", { detail: { name: data.name } }));
    } catch (e) { alert("Ошибка входа: " + e.message); }
  };

  async function renderLoginGate(chatEl, onDone) {
    const cfg = await getConfig();
    window.addEventListener("cb-auth", (e) => onDone(e.detail && e.detail.name), { once: true });
    if (!cfg.ssoEnabled || !cfg.botUsername) {
      chatEl.innerHTML = `<div class="msg bot">Вход недоступен: SSO не настроен на сервере. Можно задать код доступа вручную (localStorage <b>cb_secret</b>).</div>`;
      return;
    }
    chatEl.innerHTML = `<div class="msg bot" style="max-width:100%">
      Чтобы пользоваться ассистентом и импортом, войдите через Telegram — доступ только для своих.
      <div id="tgLoginBtn" style="margin-top:12px"></div>
    </div>`;
    const s = document.createElement("script");
    s.async = true;
    s.src = "https://telegram.org/js/telegram-widget.js?22";
    s.setAttribute("data-telegram-login", cfg.botUsername);
    s.setAttribute("data-size", "large");
    s.setAttribute("data-onauth", "onTelegramAuth(user)");
    s.setAttribute("data-request-access", "write");
    const holder = chatEl.querySelector("#tgLoginBtn");
    if (holder) holder.appendChild(s);
  }

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
    if (resp.status === 401) { clearSession(); throw new Error("Сессия истекла — войдите через Telegram заново"); }
    if (resp.status === 403) { throw new Error("Этому аккаунту вход не разрешён"); }
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
  async function personalizeRecipe(recipe, mode, arg) {
    const resp = await fetch(API + "/personalize", { method: "POST", headers: Object.assign({ "Content-Type": "application/json" }, authHeaders()), body: JSON.stringify({ recipe, mode, arg: arg || "" }) });
    if (resp.status === 401) { clearSession(); throw new Error("Войдите через Telegram"); }
    if (!resp.ok) throw new Error("Не получилось (" + resp.status + ")");
    return (await resp.json()).recipe;
  }
  async function generateRecipe(payload) {
    const resp = await fetch(API + "/generate", { method: "POST", headers: Object.assign({ "Content-Type": "application/json" }, authHeaders()), body: JSON.stringify(payload) });
    if (resp.status === 401) { clearSession(); throw new Error("Войдите через Telegram"); }
    if (!resp.ok) throw new Error("Не получилось (" + resp.status + ")");
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
    const chatEl = container.querySelector("#chat");
    if (!isAuthed()) {
      renderLoginGate(chatEl, () => renderView(container, ctx));
      return;
    }
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
    const chat = ov.querySelector("#chat");
    if (!isAuthed()) {
      renderLoginGate(chat, () => { chat.innerHTML = ""; startOverlayChat(); });
      return;
    }
    startOverlayChat();

    function startOverlayChat() {
      chat.innerHTML = msgHtml({ role: "bot", text: ctx.ingredient ? `Спросите про «${ctx.ingredient.name}» — пришлите фото товара с полки, подскажу то это или нет и чем заменить.` : "Чем помочь по рецепту?" });
      wireChat(ov, ctx, true);
    }
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

  window.CookAssistant = { renderView, openOverlay, importUrl, importPhoto, personalizeRecipe, generateRecipe };
})();
