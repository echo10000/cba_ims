// CBA IMS Service Worker
// SECURITY: This worker caches ONLY static assets (CSS, JS, icons).
// Authenticated HTML responses are NEVER cached to prevent
// private data from appearing in offline mode for other users.

const VERSION = 'cba-ims-v3';
const CACHE_NAME = `${VERSION}-static`;
const OFFLINE_URL = '/static/offline.html';

// Only pre-cache static/public assets
const PRECACHE_ASSETS = [
    OFFLINE_URL,
    'https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css',
    'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.5/font/bootstrap-icons.css',
    'https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js',
];

// Install: pre-cache only static assets
self.addEventListener('install', function(event) {
    event.waitUntil(
        caches.open(CACHE_NAME).then(function(cache) {
            return cache.addAll(PRECACHE_ASSETS);
        }).catch(function(err) {
            console.warn('[SW] Pre-cache failed:', err);
        })
    );
    self.skipWaiting();
});

// Activate: remove ALL old caches
self.addEventListener('activate', function(event) {
    event.waitUntil(
        caches.keys().then(function(cacheNames) {
            return Promise.all(
                cacheNames.filter(function(name) {
                    return name !== CACHE_NAME;
                }).map(function(name) {
                    return caches.delete(name);
                })
            );
        })
    );
    self.clients.claim();
});

// Fetch strategy:
// - Navigation (HTML): NETWORK ONLY, fall back to offline.html on failure
// - /static/ and CDN assets: cache-first
// - Everything else: network only
self.addEventListener('fetch', function(event) {
    // Skip non-GET requests entirely
    if (event.request.method !== 'GET') return;

    const url = new URL(event.request.url);

    // SECURITY: Navigation requests (HTML pages) are NEVER served from cache.
    // This ensures authenticated pages (dashboard, reports, accountability, etc.)
    // are never returned from cache after logout.
    if (event.request.mode === 'navigate') {
        event.respondWith(
            fetch(event.request).catch(function() {
                return caches.match(OFFLINE_URL);
            })
        );
        return;
    }

    // Static assets & CDNs: cache-first with network fallback
    if (url.pathname.startsWith('/static/') ||
        url.hostname === 'cdn.jsdelivr.net' ||
        url.hostname === 'fonts.googleapis.com' ||
        url.hostname === 'fonts.gstatic.com') {
        event.respondWith(
            caches.match(event.request).then(function(cached) {
                if (cached) return cached;
                return fetch(event.request).then(function(response) {
                    // Only cache successful standard responses
                    if (response && response.status === 200 && response.type === 'basic') {
                        const toCache = response.clone();
                        caches.open(CACHE_NAME).then(function(cache) {
                            cache.put(event.request, toCache);
                        });
                    }
                    return response;
                }).catch(function() {
                    // If static asset fetch fails and not in cache, let it fail gracefully
                    return new Response('', { status: 408, statusText: 'Request timed out' });
                });
            })
        );
        return;
    }

    // All other requests: straight network
    event.respondWith(fetch(event.request));
});
