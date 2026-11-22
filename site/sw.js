const VERSION = "v0.1";
const SHELL = "nbt-shell-" + VERSION;
const DATA = "nbt-data-" + VERSION;
const SCOPE = new URL(self.registration.scope);
const SHELL_ASSETS = [
  "./index.html", "./styles.css", "./manifest.webmanifest", "./app-config.json",
  "./js/app.js", "./js/calendar.js", "./js/plan.js", "./js/storage.js", "./js/push.js",
  "./js/ui.js", "./js/dashboard.js", "./js/plan-view.js", "./js/settings.js",
  "./icons/icon-192.png", "./icons/icon-512.png", "./icons/apple-touch-icon.png",
];

self.addEventListener("install", event => {
  event.waitUntil((async () => {
    const shell = await caches.open(SHELL);
    await shell.addAll(SHELL_ASSETS);
    try {
      const data = await caches.open(DATA);
      await data.addAll(["./data/latest.json", "./data/calendar.json", "./data/push.json"]);
    } catch {
      // The shell can open before the first successful data build.
    }
  })());
});

self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter(name =>
      /^(nbt-shell-|nbt-data-)/.test(name) && ![SHELL, DATA].includes(name)
    ).map(name => caches.delete(name)));
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", event => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || !url.href.startsWith(SCOPE.href)) return;
  if (url.href.startsWith(new URL("./data/", SCOPE).href)) {
    event.respondWith((async () => {
      const cache = await caches.open(DATA);
      try {
        const response = await fetch(request, { cache: "no-cache" });
        if (!response.ok) return (await cache.match(request)) ?? response;
        try {
          await cache.put(request, response.clone());
        } catch {
          // Return fresh data even if the device lacks cache space.
        }
        return response;
      } catch {
        return (await cache.match(request)) ?? Response.error();
      }
    })());
  } else {
    event.respondWith((async () => {
      const cache = await caches.open(SHELL);
      if (request.mode === "navigate") return (await cache.match("./index.html")) ?? fetch(request);
      return (await cache.match(request)) ?? fetch(request);
    })());
  }
});

self.addEventListener("push", event => {
  let data = {};
  try {
    data = event.data?.json() ?? {};
  } catch {
    // The app still opens if a notification arrives without JSON.
  }
  event.waitUntil(self.registration.showNotification(data?.title ?? "NISA 買い時", {
    body: data?.body ?? "アプリで最新の参考指標を確認できます。",
    icon: "./icons/icon-192.png",
  }));
});

self.addEventListener("notificationclick", event => {
  event.notification.close();
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    const open = windows.find(client => client.url.startsWith(SCOPE.href));
    if (open) await open.focus();
    else await self.clients.openWindow(SCOPE.href);
  })());
});
