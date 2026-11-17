{% load static %}
const CACHE_NAME = 'routefinder-v5';
const ASSETS = [
  '/',
  '{% static "RouteFinderWeb/style.css" %}',
  '{% static "icon.png" %}',
  '/manifest.json'
];

// Install Event - Pre-cache critical assets
self.addEventListener('install', (e) => {
    e.waitUntil(
      caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS))
    );
});

// Activate Event - Clean up old caches
self.addEventListener('activate', (e) => {
    e.waitUntil(
        caches.keys().then((keys) => {
            return Promise.all(keys.map((key) => {
                if (key !== CACHE_NAME) return caches.delete(key);
            }));
        })
    );
});

// Fetch Event - Network First, then Cache Fallback
self.addEventListener('fetch', (e) => {
    e.respondWith(
        fetch(e.request).catch(() => {
            return caches.match(e.request);
        })
    );
});
