const CACHE = "carrick-shell-v1";
const ASSETS = ["/app", "/styles.css", "/app.js", "/offline.js", "/capture.js", "/analytics.js", "/manifest.webmanifest", "/brand/carrick-mark.svg"];
self.addEventListener("install", event => event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(ASSETS)).then(() => self.skipWaiting())));
self.addEventListener("activate", event => event.waitUntil(
  caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith("carrick-shell-") && key !== CACHE).map(key => caches.delete(key)))).then(() => self.clients.claim())
));
self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;
  const key = url.pathname === "/app/" ? "/app" : url.pathname;
  if (!ASSETS.includes(key)) return;
  event.respondWith((async () => {
    try {
      const response = await fetch(event.request);
      if (response.ok) await (await caches.open(CACHE)).put(key, response.clone());
      return response;
    } catch (error) {
      const cached = await (await caches.open(CACHE)).match(key);
      if (cached) return cached;
      throw error;
    }
  })());
});
