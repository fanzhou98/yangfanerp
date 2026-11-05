'use strict';
// 应用壳：只缓存首页与“带版本号”的静态资源；接口、打印页、司机页一律走网络，避免读到旧业务数据。
// 版本号来自注册地址 /sw.js?v=<APP_VERSION>，每个发布版本一个缓存桶，激活时清掉旧桶。
const VERSION = new URL(self.location.href).searchParams.get('v') || 'dev';
const CACHE = 'erp-shell-' + VERSION;
const SHELL = ['/', '/bundle.js?v=' + VERSION, '/bundle.css?v=' + VERSION, '/favicon.svg', '/apple-touch-icon.png', '/site.webmanifest'];

self.addEventListener('install', event => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    await Promise.all(SHELL.map(url => cache.add(new Request(url, {cache: 'reload'})).catch(() => {})));
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) if (key !== CACHE && key.startsWith('erp-shell-')) await caches.delete(key);
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  // 业务数据必须实时：接口、打印、司机门户都不接管。
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/print/') || url.pathname.startsWith('/driver/')) return;
  if (request.mode === 'navigate') {
    // 首页网络优先（2.5 秒超时），断网时回落到本版本的应用壳，避免整页白屏。
    event.respondWith((async () => {
      try {
        return await Promise.race([
          fetch(request),
          new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), 2500)),
        ]);
      } catch {
        const cached = await caches.match('/', {cacheName: CACHE});
        return cached || new Response('<!doctype html><meta charset="utf-8"><title>网络不可用</title><p>当前网络不可用，请恢复网络后刷新页面。</p>', {status: 503, headers: {'Content-Type': 'text/html; charset=utf-8'}});
      }
    })());
    return;
  }
  // 版本化静态资源：缓存优先，未命中再取网络。
  if (url.searchParams.get('v') === VERSION && /\.(?:js|css|png|ico|svg|webmanifest)$/.test(url.pathname)) {
    event.respondWith((async () => (await caches.match(request, {cacheName: CACHE})) || fetch(request))());
  }
});
