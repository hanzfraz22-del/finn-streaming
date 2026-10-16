// Finn Streaming - Service Worker PWA Cache Engine
const CACHE_NAME = 'finn-streaming-v1';
const ASSETS_TO_CACHE = [
    '/',
    '/manifest.json'
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return cache.addAll(ASSETS_TO_CACHE);
        })
    );
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((keys) => {
            return Promise.all(
                keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
            );
        })
    );
    self.clients.claim();
});

self.addEventListener('fetch', (event) => {
    if (event.request.method !== 'GET') return;
    const url = new URL(event.request.url);

    // Ignoriere Streaming-Fragmente, Scraper APIs und Hoster
    if (
        url.pathname.startsWith('/api/') ||
        url.pathname.endsWith('.m3u8') ||
        url.pathname.endsWith('.ts') ||
        url.hostname.includes('voe') ||
        url.hostname.includes('vidsrc') ||
        url.hostname.includes('vidlink')
    ) {
        return;
    }

    event.respondWith(
        fetch(event.request)
            .then((response) => {
                if (response && response.status === 200 && response.type === 'basic') {
                    const responseClone = response.clone();
                    caches.open(CACHE_NAME).then((cache) => {
                        cache.put(event.request, responseClone);
                    });
                }
                return response;
            })
            .catch(() => {
                return caches.match(event.request).then((cachedResponse) => {
                    return cachedResponse || caches.match('/');
                });
            })
    );
});
