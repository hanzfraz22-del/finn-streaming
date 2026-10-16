// Finn Streaming - Service Worker PWA Engine v4
const CACHE_NAME = 'finn-streaming-v4';

self.addEventListener('install', (event) => {
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((keys) => {
            return Promise.all(
                keys.map((key) => caches.delete(key))
            );
        })
    );
    self.clients.claim();
});

self.addEventListener('fetch', (event) => {
    if (event.request.method !== 'GET') return;
    const url = new URL(event.request.url);

    // HTML und APIs niemals veraltet cachen
    if (
        url.pathname === '/' ||
        url.pathname.startsWith('/api/') ||
        url.pathname.endsWith('.m3u8') ||
        url.pathname.endsWith('.ts')
    ) {
        return;
    }
});
