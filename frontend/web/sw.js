/* Raahat offline support.
 *
 * Keeps the page, the hospital list and first-aid cards on the phone so 108, first aid and a
 * distance-sorted hospital list still work with no signal. Always tries the network first, so a
 * new deploy or re-checked data reaches people as soon as they are online.
 */
"use strict";

const CACHE = "raahat-v2";
const SHELL = [
  "/", "/app.js", "/styles.css",
  "/api/i18n", "/api/injuries", "/api/situations", "/api/facilities", "/api/sources", "/api/conditions",
  "/api/checklist", "/api/localities", "/api/helplines",
  "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css",
  "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js",
];

self.addEventListener("install", (event) => {
  // One failed file (e.g. the CDN) shouldn't stop the rest from being saved.
  event.waitUntil(caches.open(CACHE).then((c) => Promise.all(SHELL.map((u) => c.add(u).catch(() => {}))))
    .then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

function cacheable(url) {
  if (url.origin === self.location.origin) return !url.pathname.startsWith("/api/admin") && url.pathname !== "/api/health";
  return url.hostname === "cdnjs.cloudflare.com";
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || !cacheable(url)) return; // POSTs (search, questions) go straight to the network

  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    try {
      const res = await fetch(req);
      if (res.ok) cache.put(req, res.clone());
      return res;
    } catch {
      const hit = await cache.match(req);
      if (hit) return hit;
      // A first-aid card not yet seen in this language: the English one is better than nothing.
      if (url.pathname === "/api/first_aid" || url.pathname === "/api/danger_signs") {
        url.searchParams.set("language", "en");
        const en = await cache.match(url.toString());
        if (en) return en;
      }
      if (req.mode === "navigate") return (await cache.match("/")) || Response.error();
      return Response.error();
    }
  })());
});
