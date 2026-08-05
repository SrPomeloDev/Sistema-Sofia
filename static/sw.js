const CACHE = 'sofia-ltda-v18';
const STATIC_FILES = [
  '/',
  '/camiones',
  '/camiones/login',
  '/manifest.json',
  '/static/icons/logo-180.png',
  '/static/icons/logo-152.png',
  '/static/icons/logo-192.png',
  '/static/icons/logo-512.png',
  '/static/icons/camion-sofia.png',
  '/static/icons/favicon.png',
  '/static/design.css',
  '/static/theme.js',
  '/static/camiones/index.html',
  '/static/camiones/login.html',
  '/rutas',
  '/rutas/login',
  '/static/rutas/index.html',
  '/static/rutas/login.html',
  '/jornaleros',
  '/jornaleros/login',
  '/static/jornaleros/index.html',
  '/static/jornaleros/login.html',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(STATIC_FILES))
  );
  self.skipWaiting();
});

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') self.skipWaiting();
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

  // Navegaciones (HTML): siempre red primero, caché como respaldo.
  // Evita que los usuarios vean versiones viejas cacheadas.
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          const clone = response.clone();
          caches.open(CACHE).then((cache) => cache.put(event.request, clone));
          return response;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }

  // Assets estáticos: caché primero, actualización en segundo plano.
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



