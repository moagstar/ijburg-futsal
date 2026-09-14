const CACHE_NAME = "ijburg-futsal-v1";
const NETWORK_FIRST_FILES = new Set([
  "index.html",
  "matches.txt",
  "script.js",
  "styles.css",
]);

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((names) => Promise.all(
        names
          .filter((name) => name !== CACHE_NAME)
          .map((name) => caches.delete(name)),
      ))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  const fileName = url.pathname.split("/").pop() || "index.html";
  const isAvatar = url.pathname.includes("/avatars/");

  if (
    event.request.method !== "GET" ||
    url.origin !== self.location.origin ||
    (event.request.mode !== "navigate" && !NETWORK_FIRST_FILES.has(fileName) && !isAvatar)
  ) {
    return;
  }

  event.respondWith(
    (async () => {
      try {
        const response = await fetch(event.request, {
          cache: isAvatar ? "no-cache" : "no-store",
        });
        if (response.ok) {
          const cache = await caches.open(CACHE_NAME);
          await cache.put(event.request, response.clone());
        }
        return response;
      } catch {
        return (await caches.match(event.request)) || Response.error();
      }
    })(),
  );
});
