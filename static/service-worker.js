// ═══════════════════════════════════════════════════════════════════
// 📱 Service Worker for Garage Manager System - PWA Support
// ═══════════════════════════════════════════════════════════════════

const CACHE_NAME = 'garage-manager-v1.1.0';
const STATIC_CACHE = 'garage-static-v2';
const DYNAMIC_CACHE = 'garage-dynamic-v2';

// الملفات المهمة للتخزين المسبق
const STATIC_FILES = [
  '/',
  '/static/css/style.css',
  '/static/css/mobile.css',
  '/static/js/ux-enhancements.js',
  '/static/branding/platform/logos/primary.png',
  '/static/branding/platform/favicons/favicon.png',
  '/static/adminlte/css/adminlte.min.css',
  '/static/adminlte/plugins/fontawesome-free/css/all.min.css',
  'https://fonts.googleapis.com/css2?family=Tajawal:wght@300;400;500;600;700;800&display=swap'
];

// تثبيت Service Worker
self.addEventListener('install', (event) => {
  // Installing...
  
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then((cache) => {
        // Caching static files
        return cache.addAll(STATIC_FILES.map(url => new Request(url, {
          cache: 'reload'
        })));
      })
      .then(() => {
        // Installed successfully
        return self.skipWaiting();
      })
      .catch((error) => {
        // Installation failed
      })
  );
});

// تفعيل Service Worker
self.addEventListener('activate', (event) => {
  // Activating...
  
  event.waitUntil(
    caches.keys()
      .then((keys) => {
        return Promise.all(
          keys
            .filter((key) => key !== STATIC_CACHE && key !== DYNAMIC_CACHE)
            .map((key) => {
              // Removing old cache
              return caches.delete(key);
            })
        );
      })
      .then(() => {
        // Activated
        return self.clients.claim();
      })
  );
});

// اعتراض الطلبات
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);
  
  // تجاهل الطلبات غير HTTP/HTTPS
  if (!url.protocol.startsWith('http')) {
    return;
  }
  
  // تجاهل طلبات API للحصول على بيانات حديثة دائماً
  if (url.pathname.startsWith('/api/')) {
    return;
  }
  
  // استراتيجية Network First للصفحات الديناميكية
  if (request.method === 'GET') {
    event.respondWith(
      networkFirst(request)
    );
  }
});

// Network First Strategy - محاولة الشبكة أولاً ثم Cache
async function networkFirst(request) {
  try {
    const networkResponse = await fetch(request);
    
    // تخزين الاستجابة الناجحة
    if (networkResponse && networkResponse.status === 200) {
      const cache = await caches.open(DYNAMIC_CACHE);
      cache.put(request, networkResponse.clone());
    }
    
    return networkResponse;
  } catch (error) {
    // إذا فشلت الشبكة، حاول من Cache
    const cachedResponse = await caches.match(request);
    
    if (cachedResponse) {
      // Serving from cache
      return cachedResponse;
    }
    
    // إذا لم يكن في Cache، أرجع صفحة offline
    if (request.destination === 'document') {
      return caches.match('/offline.html') || new Response(
        '<html><body style="font-family: Arial; text-align: center; padding: 50px;">' +
        '<h1>🔌 لا يوجد اتصال بالإنترنت</h1>' +
        '<p>يرجى التحقق من اتصالك بالإنترنت والمحاولة مرة أخرى</p>' +
        '</body></html>',
        {
          headers: { 'Content-Type': 'text/html; charset=utf-8' }
        }
      );
    }
    
    throw error;
  }
}

// معالجة رسائل من التطبيق
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
  
  if (event.data && event.data.type === 'CLEAR_CACHE') {
    event.waitUntil(
      caches.keys().then((keys) => {
        return Promise.all(
          keys.map((key) => caches.delete(key))
        );
      })
    );
  }
});

// مزامنة الخلفية (Background Sync)
self.addEventListener('sync', (event) => {
  if (event.tag === 'sync-data') {
    event.waitUntil(syncData());
  }
});

async function syncData() {
  // Background sync started
  // يمكن إضافة منطق المزامنة هنا
}

// إشعارات Push
self.addEventListener('push', (event) => {
  const data = event.data ? event.data.json() : {};
  const title = data.title || 'إشعار جديد';
  const options = {
    body: data.body || 'لديك تحديث جديد',
    icon: '/static/branding/platform/logos/primary.png',
    badge: '/static/branding/platform/favicons/favicon.png',
    vibrate: [200, 100, 200],
    dir: 'rtl',
    lang: 'ar',
    requireInteraction: true
  };
  
  event.waitUntil(
    self.registration.showNotification(title, options)
  );
});

// النقر على الإشعار
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  
  event.waitUntil(
    clients.openWindow(event.notification.data?.url || '/')
  );
});

// Service Worker loaded
