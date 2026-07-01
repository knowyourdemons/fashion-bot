/* ============================================================
   Синк личного состояния между устройствами (по Telegram id).
   Offline-first: localStorage — источник правды, синк в фоне.
   Last-write-wins по rev (Date.now() мс). Работает только при
   Telegram-сессии; без логина/офлайна приложение как раньше.
   Грузится ДО app.js: к моменту Store.save() window.CookSync готов.
   ============================================================ */
(function () {
  'use strict';
  const API = "/api/v1/cookbook";
  const SYNC_KEYS = ["shopping", "pantry", "memory", "userRecipes", "plan", "ingChecks", "profile"];
  const REV_KEY = "cb_rev";

  function session() { return localStorage.getItem("cb_session_token") || ""; }
  function getRevMap() { try { return JSON.parse(localStorage.getItem(REV_KEY) || "{}"); } catch (e) { return {}; } }
  function saveRevMap(m) { try { localStorage.setItem(REV_KEY, JSON.stringify(m)); } catch (e) {} }
  function readLocal(key) { try { const v = localStorage.getItem("cb_" + key); return v == null ? undefined : JSON.parse(v); } catch (e) { return undefined; } }
  function headers() { const h = { "Content-Type": "application/json" }; const s = session(); if (s) h["X-Cookbook-Session"] = s; return h; }

  // Применить серверную копию ключа локально (без повторного push) + перерисовать
  function applyServer(key, sv, revMap) {
    if (window.Cookbook && window.Cookbook.Store && typeof window.Cookbook.Store.set === "function") {
      window.Cookbook.Store.set(key, sv.v);
    } else {
      try { localStorage.setItem("cb_" + key, JSON.stringify(sv.v)); } catch (e) {}
    }
    revMap[key] = sv.rev;
  }

  async function getState() {
    const r = await fetch(API + "/state", { headers: headers() });
    if (!r.ok) throw new Error("state " + r.status);
    return (await r.json()).states || {};
  }
  async function putState(states) {
    const r = await fetch(API + "/state", { method: "PUT", headers: headers(), body: JSON.stringify({ states }) });
    if (!r.ok) throw new Error("put " + r.status);
    return (await r.json()).newer || {};
  }

  // ---- push (дебаунс, коалесценция dirty-ключей) ----
  const dirty = new Set();
  let timer = null;
  function push(key) {
    if (!session() || SYNC_KEYS.indexOf(key) < 0) return;
    const revMap = getRevMap();
    revMap[key] = Date.now();      // штампуем момент изменения
    saveRevMap(revMap);
    dirty.add(key);
    clearTimeout(timer);
    timer = setTimeout(flush, 1500);
  }
  async function flush() {
    if (!session() || !dirty.size) return;
    const revMap = getRevMap();
    const states = {};
    dirty.forEach(k => { states[k] = { v: readLocal(k), rev: revMap[k] || Date.now() }; });
    dirty.clear();
    try {
      const newer = await putState(states);   // сервер вернул ключи, где его копия свежее
      const keys = Object.keys(newer);
      if (keys.length) {
        keys.forEach(k => applyServer(k, newer[k], revMap));
        saveRevMap(revMap);
        window.dispatchEvent(new CustomEvent("cb-synced"));
      }
    } catch (e) { /* офлайн — localStorage уже содержит данные, повторим при следующем сохранении */ }
  }

  // ---- boot (первый merge при старте/логине) ----
  async function boot() {
    if (!session()) return;
    let server;
    try { server = await getState(); } catch (e) { return; }   // офлайн/не авторизованы — тихо
    const revMap = getRevMap();
    const toPush = {};
    let changed = false;
    for (const key of SYNC_KEYS) {
      const sv = server[key];
      const lr = revMap[key];
      const hasLocal = localStorage.getItem("cb_" + key) != null;
      if (sv && (!lr || sv.rev > lr)) {
        applyServer(key, sv, revMap); changed = true;          // сервер новее (или локальное не штамповано)
      } else if (hasLocal) {
        const rev = lr || Date.now();                          // сид существующих локальных данных
        revMap[key] = rev;
        toPush[key] = { v: readLocal(key), rev };
      }
    }
    saveRevMap(revMap);
    if (changed) window.dispatchEvent(new CustomEvent("cb-synced"));
    if (Object.keys(toPush).length) { try { await putState(toPush); } catch (e) {} }
  }

  // Первый merge после успешного Telegram-логина (assistant.js шлёт cb-auth)
  window.addEventListener("cb-auth", () => boot());

  window.CookSync = { push, boot };
})();
