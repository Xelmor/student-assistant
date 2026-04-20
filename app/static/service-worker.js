const CACHE_NAME = 'student-assistant-v5';
const APP_SHELL = [
  '/static/css/style.css?v=20260420-mobilequick',
  '/static/css/base.css?v=20260420-mobilequick',
  '/static/css/dashboard.css?v=20260420-mobilequick',
  '/static/css/entities.css?v=20260420-mobilequick',
  '/static/css/profile.css?v=20260420-mobilequick',
  '/static/css/calendar.css?v=20260420-mobilequick',
  '/static/css/responsive.css?v=20260420-mobilequick',
  '/static/css/mobile.css?v=20260420-mobilequick',
  '/static/css/landing.css?v=20260420-mobilequick',
  '/static/js/pwa.js?v=20260420-mobilequick',
  '/static/pwa/icon-app.svg',
  '/manifest.webmanifest',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)).catch(() => Promise.resolve())
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') {
    return;
  }

  const requestUrl = new URL(event.request.url);
  const isStaticAsset = requestUrl.origin === self.location.origin && (
    requestUrl.pathname.startsWith('/static/') ||
    requestUrl.pathname === '/manifest.webmanifest'
  );

  if (!isStaticAsset) {
    return;
  }

  event.respondWith(
    caches.match(event.request).then((cachedResponse) => {
      if (cachedResponse) {
        return cachedResponse;
      }

      return fetch(event.request)
        .then((networkResponse) => {
          if (!networkResponse || networkResponse.status !== 200 || networkResponse.type !== 'basic') {
            return networkResponse;
          }

          const responseClone = networkResponse.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, responseClone)).catch(() => {});
          return networkResponse;
        });
    })
  );
});
