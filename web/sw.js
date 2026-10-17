// v378 — Para que se pueda instalar como app en el celular. Siempre pide a la
// red primero (los datos cambian a cada rato); sin red, lo último guardado.
const CACHE = 'sharpicks-v1';
self.addEventListener('install', (e) => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', (e) => {
  const u = new URL(e.request.url);
  if (e.request.method !== 'GET' || u.origin !== location.origin) return;
  e.respondWith(fetch(e.request).then((r) => {
    const c = r.clone(); caches.open(CACHE).then((k) => k.put(e.request, c)); return r;
  }).catch(() => caches.match(e.request)));
});
