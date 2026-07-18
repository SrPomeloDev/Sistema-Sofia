const CACHE = 'sofia-ltda-v4';
const STATIC_FILES = [
  '/',
  '/camiones',
  '/camiones/login',
  '/static/manifest.json',
  '/static/icons/logo.svg',
  '/static/icons/logo-192.svg',
  '/static/icons/logo-192.png',
  '/static/icons/logo-180.png',
  '/static/icons/logo-152.png',
  '/static/icons/logo-512.png',
  '/static/icons/favicon.svg',
  '/static/camiones/index.html',
  '/static/camiones/login.html',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(STATIC_FILES))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;
  event.respondWith(
    caches.match(event.request).then((cached) => {
      const fetchPromise = fetch(event.request).then((response) => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE).then((cache) => cache.put(event.request, clone));
        }
        return response;
      }).catch(() => cached);
      return cached || fetchPromise;
    })
  );
});
