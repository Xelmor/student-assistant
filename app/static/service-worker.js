const CACHE_NAME = 'student-assistant-v40-dark-only-v1';
const APP_SHELL = [
  '/static/vendor/bootstrap/bootstrap.min.css',
  '/static/vendor/bootstrap/bootstrap.bundle.min.js',
  '/static/css/style.css?v=20260611-dark-only-v1',
  '/static/css/core/base.css',
  '/static/css/core/responsive.css',
  '/static/css/core/mobile.css',
  '/static/css/pages/dashboard.css',
  '/static/css/pages/dashboard-theme.css?v=20260607-dark-dashboard-v2',
  '/static/css/pages/tasks-theme.css?v=20260607-dark-tasks',
  '/static/css/pages/subjects-theme.css?v=20260608-dark-subjects',
  '/static/css/pages/schedule-theme.css?v=20260608-dark-schedule',
  '/static/css/pages/entities.css',
  '/static/css/pages/profile.css?v=20260610-dark-profile-v1',
  '/static/css/pages/calendar.css?v=20260609-week-timeline',
  '/static/css/pages/notes-theme.css?v=20260610-dark-notes-v1',
  '/static/css/pages/landing.css?v=20260610-landing-nav-v2',
  '/static/css/pages/auth-theme.css?v=20260610-dark-auth-v1',
  '/static/css/pages/navbar-tools.css?v=20260611-dark-only-v1',
  '/static/css/pages/empty-state.css?v=20260610-empty-states-v1',
  '/static/css/pages/actions-feedback.css?v=20260610-actions-feedback-v1',
  '/static/css/pages/mobile-app.css?v=20260610-mobile-app-v1',
  '/static/css/pages/motion-system.css?v=20260611-motion-v1',
  '/static/css/pages/user-preferences.css?v=20260611-dark-only-v1',
  '/static/css/pages/local-profile.css?v=20260611-local-profile-v1',
  '/static/css/pages/profile-simple.css?v=20260611-dark-only-v1',
  '/static/css/pages/password-recovery.css?v=20260611-password-recovery-v1',
  '/static/js/user-preferences.js?v=20260611-dark-only-v1',
  '/static/js/base.js?v=20260611-motion-v1',
  '/static/js/actions-feedback.js?v=20260611-preferences-v1',
  '/static/js/navbar-tools.js?v=20260611-preferences-v1',
  '/static/js/pwa.js?v=20260611-dark-only-v1',
  '/static/js/password-recovery.js?v=20260611-password-recovery-v1',
  '/static/js/dashboard.js?v=20260611-preferences-v1',
  '/static/js/tasks.js?v=20260611-motion-v1',
  '/static/js/subjects.js?v=20260611-motion-v1',
  '/static/js/schedule.js?v=20260611-motion-v1',
  '/static/js/calendar.js?v=20260611-motion-v1',
  '/static/js/notes.js?v=20260611-motion-v1',
  '/static/images/dashboard/night-study-hero.png',
  '/static/pwa/icon-app.svg?v=20260610-purple-sa-v1',
  '/manifest.webmanifest?v=20260610-purple-sa-v1',
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
