// sw.js — service worker for the cactus board: caches the page shell only.
// Never caches /api/*, /login, or any URL with a query string; offline shows one line.
const CACHE = "cactus-shell-v1";
const SHELL = "/";

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.add(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.startsWith("/api/") || url.pathname === "/login" || url.search) return;
  if (url.pathname !== SHELL) return;
  e.respondWith(
    fetch(req)
      .then((res) => {
        if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(SHELL, copy)); }
        return res;
      })
      .catch(() => caches.match(SHELL).then((hit) => hit || new Response("board offline", {
        status: 503, headers: { "Content-Type": "text/plain" },
      })))
  );
});
