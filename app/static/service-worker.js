const CACHE_NAME = 'student-assistant-v60-device-sync';
const APP_SHELL = [
  '/static/css/theme.css?v=20260922-graphite',
  '/static/vendor/bootstrap/bootstrap.min.css',
  '/static/vendor/bootstrap/bootstrap.bundle.min.js',
  '/static/css/style.css?v=20260922-graphite',
  '/static/css/core/base.css?v=20260922-graphite',
  '/static/css/core/responsive.css?v=20260922-graphite',
  '/static/css/core/mobile.css?v=20260922-graphite',
  '/static/css/pages/dashboard.css?v=20260922-graphite',
  '/static/css/pages/dashboard-theme.css?v=20260922-graphite',
  '/static/css/pages/onboarding.css?v=20260922-graphite',
  '/static/css/pages/onboarding-chat.css?v=20260922-graphite',
  '/static/css/pages/tasks-theme.css?v=20260922-graphite',
  '/static/css/pages/subjects-theme.css?v=20260922-graphite',
  '/static/css/pages/schedule-theme.css?v=20260922-graphite',
  '/static/css/pages/entities.css?v=20260922-graphite',
  '/static/css/pages/profile.css?v=20260922-graphite',
  '/static/css/pages/calendar.css?v=20260922-graphite',
  '/static/css/pages/notes-theme.css?v=20260922-graphite',
  '/static/css/pages/landing.css?v=20260922-graphite',
  '/static/css/pages/auth-theme.css?v=20260922-graphite',
  '/static/css/pages/navbar-tools.css?v=20260922-graphite',
  '/static/css/pages/empty-state.css?v=20260922-graphite',
  '/static/css/pages/actions-feedback.css?v=20260922-graphite',
  '/static/css/pages/mobile-app.css?v=20260922-graphite',
  '/static/css/pages/motion-system.css?v=20260922-graphite',
  '/static/css/pages/user-preferences.css?v=20260922-graphite',
  '/static/css/pages/local-profile.css?v=20260922-graphite',
  '/static/css/pages/profile-simple.css?v=20260922-graphite',
  '/static/css/pages/password-recovery.css?v=20260922-graphite',
  '/static/css/pages/error-pages.css?v=20260922-graphite',
  '/static/css/pages/about.css?v=20260922-graphite',
  '/static/css/pages/entry.css?v=20260922-graphite',
  '/static/css/pages/device-sync.css?v=20260922-sync-v1',
  '/static/js/user-preferences.js?v=20260922-graphite',
  '/static/js/base.js?v=20260611-motion-v1',
  '/static/js/actions-feedback.js?v=20260612-telegram-v1',
  '/static/js/navbar-tools.js?v=20260611-preferences-v1',
  '/static/js/pwa.js?v=20260612-telegram-v1',
  '/static/js/profile-telegram.js?v=20260612-telegram-v1',
  '/static/js/auth-password-hint.js?v=20260612-password-hint-v1',
  '/static/js/password-recovery.js?v=20260611-password-recovery-v1',
  '/static/js/error-page.js?v=20260612-error-pages-v1',
  '/static/js/entry.js?v=20260920-entry-v3',
  '/static/js/device-sync.js?v=20260922-sync-v1',
  '/static/js/dashboard.js?v=20260612-onboarding-chat-v1',
  '/static/js/onboarding-chat.js?v=20260922-graphite',
  '/static/js/tasks.js?v=20260611-motion-v1',
  '/static/js/subjects.js?v=20260611-motion-v1',
  '/static/js/schedule.js?v=20260611-motion-v1',
  '/static/js/calendar.js?v=20260612-onboarding-v1',
  '/static/js/notes.js?v=20260611-motion-v1',
  '/static/images/dashboard/night-study-hero.png',
  '/static/pwa/icon-app.svg?v=20260922-graphite',
  '/manifest.webmanifest?v=20260922-graphite',
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
