const CACHE_VERSION = "bookflow-pwa-v1";
const APP_SHELL_CACHE = `${CACHE_VERSION}-app-shell`;
const ASSET_CACHE = `${CACHE_VERSION}-assets`;

const APP_SHELL_URLS = [
  "/app",
  "/app/",
  "/app/index.html",
  "/app/reader",
  "/app/reader.html",
  "/app/book",
  "/app/book.html",
  "/app/toc",
  "/app/toc.html",
  "/app/login",
  "/app/login.html",
  "/app/styles.css",
  "/app/app.js",
  "/app/manifest.webmanifest",
  "/app/icons/icon-192.png",
  "/app/icons/icon-512.png"
];

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(APP_SHELL_CACHE);
    await cache.addAll(APP_SHELL_URLS);
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(
      keys
        .filter((key) => key.startsWith("bookflow-pwa-") && ![APP_SHELL_CACHE, ASSET_CACHE].includes(key))
        .map((key) => caches.delete(key))
    );
    await self.clients.claim();
  })());
});

function canonicalAppPath(pathname) {
  if (pathname === "/app" || pathname === "/app/" || pathname === "/app/feed") {
    return "/app/index.html";
  }
  if (pathname === "/app/reader") {
    return "/app/reader.html";
  }
  if (pathname === "/app/book") {
    return "/app/book.html";
  }
  if (pathname === "/app/toc") {
    return "/app/toc.html";
  }
  if (pathname === "/app/login" || pathname === "/app/login/") {
    return "/app/login.html";
  }
  return pathname;
}

async function handleAppNavigation(request, url) {
  try {
    const network = await fetch(request);
    if (network && network.ok) {
      const cache = await caches.open(APP_SHELL_CACHE);
      const key = canonicalAppPath(url.pathname);
      await cache.put(key, network.clone());
    }
    return network;
  } catch (err) {
    const cache = await caches.open(APP_SHELL_CACHE);
    const key = canonicalAppPath(url.pathname);
    return (await cache.match(key)) || (await cache.match("/app/index.html")) || Response.error();
  }
}

async function handleAppAsset(request, event) {
  const cache = await caches.open(ASSET_CACHE);
  const cached = await cache.match(request);

  const networkPromise = fetch(request)
    .then(async (response) => {
      if (response && response.ok) {
        await cache.put(request, response.clone());
      }
      return response;
    })
    .catch(() => null);

  if (cached) {
    if (event && typeof event.waitUntil === "function") {
      event.waitUntil(networkPromise.then(() => undefined));
    }
    return cached;
  }

  const network = await networkPromise;
  if (network) {
    return network;
  }

  return new Response("", { status: 504, statusText: "Gateway Timeout" });
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") {
    return;
  }

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) {
    return;
  }

  if (!url.pathname.startsWith("/app/")) {
    return;
  }

  if (url.pathname === "/app/sw.js") {
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(handleAppNavigation(request, url));
    return;
  }

  event.respondWith(handleAppAsset(request, event));
});
