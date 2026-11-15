// Minimal service worker: makes the site installable as an app.
// Nothing is cached, so the library is always live.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});
