/* Service Worker кукбука — офлайн + установка на телефон.
   VERSION синхронен с ?v= в index.html (менять вместе на каждый релиз).
   Кэши: shell (оболочка) + data (recipes.js) версионированные; photos — нет (id-неизменны). */
const VERSION = '20260701w';
const SHELL = `shell-${VERSION}`;
const DATA = `data-${VERSION}`;
const PHOTOS = 'photos-v1';
const PHOTO_CAP = 400;

const SHELL_ASSETS = [
  '/', '/index.html', '/manifest.json',
  `/css/cookbook.css?v=${VERSION}`,
  `/js/app.js?v=${VERSION}`,
  `/js/assistant.js?v=${VERSION}`,
  `/js/sync.js?v=${VERSION}`,
  '/icons/icon-192.png', '/icons/icon-512.png',
];
const DATA_ASSETS = [`/data/recipes.js?v=${VERSION}`];

self.addEventListener('install', (e) => {
  e.waitUntil((async () => {
    const s = await caches.open(SHELL);
    await s.addAll(SHELL_ASSETS).catch(() => {});   // не валим install из-за одного 404 (напр. шрифты)
    const d = await caches.open(DATA);
    await d.addAll(DATA_ASSETS);                     // recipes.js — критично для офлайна
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (e) => {
  e.waitUntil((async () => {
    const keep = new Set([SHELL, DATA, PHOTOS]);
    for (const k of await caches.keys()) if (!keep.has(k)) await caches.delete(k);
    await self.clients.claim();
  })());
});

async function cacheFirst(req, cacheName) {
  const cache = await caches.open(cacheName);
  const hit = await cache.match(req, { ignoreVary: true });
  if (hit) return hit;
  try {
    const res = await fetch(req);
    if (res && (res.ok || res.type === 'opaque')) cache.put(req, res.clone()).catch(() => {});
    return res;
  } catch (e) {
    return hit || Response.error();
  }
}

async function photo(req) {
  const cache = await caches.open(PHOTOS);
  const hit = await cache.match(req, { ignoreVary: true });
  if (hit) return hit;
  try {
    const res = await fetch(req);
    if (res && res.ok) {
      cache.put(req, res.clone()).then(() => trim(cache));
    }
    return res;
  } catch (e) {
    return hit || Response.error();
  }
}

async function trim(cache) {
  const keys = await cache.keys();
  if (keys.length <= PHOTO_CAP) return;
  for (let i = 0; i < keys.length - PHOTO_CAP; i++) await cache.delete(keys[i]);
}

async function nav(req) {
  try {
    return await fetch(req);
  } catch (e) {
    const cache = await caches.open(SHELL);
    return (await cache.match('/index.html')) || (await cache.match('/')) || Response.error();
  }
}

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  // Никогда не кэшим API (ассистент/синк/логин) — всегда сеть
  if (url.origin === location.origin && url.pathname.startsWith('/api/')) return;
  if (url.pathname.startsWith('/img/recipes/')) { e.respondWith(photo(req)); return; }
  if (req.mode === 'navigate') { e.respondWith(nav(req)); return; }
  // Оболочка/данные (тот же origin) + Google Fonts — cache-first
  if (url.origin === location.origin || /fonts\.(googleapis|gstatic)\.com$/.test(url.host)) {
    e.respondWith(cacheFirst(req, url.origin === location.origin ? (url.pathname.startsWith('/data/') ? DATA : SHELL) : SHELL));
  }
});
