/* ============================
   Eshara Service Worker v2.0
   FIXED & OPTIMIZED
   ============================ */
'use strict';

const CACHE_NAME   = 'eshara-v5';
const STATIC_ASSETS = [
  '/',
  '/index.html',
  '/manifest.json',
  'https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@300;400;600;700&family=Space+Mono&display=swap',
];

/* ── Install: cache static assets ── */
self.addEventListener('install', event => {
  console.log('Service Worker installing...');
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      console.log('Caching static assets');
      return cache.addAll(STATIC_ASSETS);
    })
  );
  self.skipWaiting();
});

/* ── Activate: remove old caches ── */
self.addEventListener('activate', event => {
  console.log('Service Worker activating...');
  event.waitUntil(
    caches.keys().then(keys => {
      console.log('Removing old caches:', keys);
      return Promise.all(
        keys.filter(k => k !== CACHE_NAME).map(k => {
          console.log('Deleting cache:', k);
          return caches.delete(k);
        })
      );
    })
  );
  self.clients.claim();
});

/* ── Fetch: cache-first for static, network-first for API ── */
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  
  // Don't cache API calls (/predict)
  if (url.pathname.startsWith('/predict')) {
    event.respondWith(
      fetch(event.request)
        .then(res => {
          console.log('API response:', res.status);
          return res;
        })
        .catch(err => {
          console.log('API offline, returning fallback');
          return new Response(JSON.stringify({ error: 'offline' }), {
            headers: { 'Content-Type': 'application/json' }
          });
        })
    );
    return;
  }

  // Cache-first for everything else
  event.respondWith(
    caches.match(event.request).then(cached => {
      if (cached) {
        console.log('Serving from cache:', url.pathname);
        return cached;
      }
      
      return fetch(event.request)
        .then(res => {
          // Cache successful GET responses
          if (res.ok && event.request.method === 'GET') {
            const clone = res.clone();
            caches.open(CACHE_NAME).then(cache => {
              console.log('Caching response:', url.pathname);
              cache.put(event.request, clone);
            });
          }
          return res;
        })
        .catch(err => {
          console.log('Fetch failed, trying fallback');
          return caches.match('/index.html');
        });
    })
  );
});

/* ── Message handler for cache busting ── */
self.addEventListener('message', event => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    console.log('Skipping waiting, activating new service worker');
    self.skipWaiting();
  }
  if (event.data && event.data.type === 'CLEAR_CACHE') {
    console.log('Clearing all caches');
    caches.keys().then(keys => {
      Promise.all(keys.map(k => caches.delete(k)));
    });
  }
});
