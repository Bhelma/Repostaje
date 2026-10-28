// Primero red (saltándose la caché del navegador); si no hay conexión, la última copia guardada.
// Así cada cambio que subes a GitHub aparece al abrir la app, y sigue abriendo sin cobertura.
const CACHE = 'repostaje-v4';
self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(
  caches.keys()
    .then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim())
));
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;
  e.respondWith(
    fetch(url.href, { cache: 'no-cache' }).then(r => {
      if (r.ok) { const copia = r.clone(); caches.open(CACHE).then(c => c.put(e.request, copia)); }
      return r;
    }).catch(() => caches.match(e.request, { ignoreSearch: true }))
  );
});

// Notificaciones que manda el proceso de GitHub (aceite, neumáticos, vigilancia...)
// Cada tipo lleva su icono: escudo rojo = vigilancia activa, triángulo naranja = el coche se ha movido.
const TIPOS = {
  info: { icon: 'icons/icon-192.png', badge: 'icons/badge-96.png' },
  vigilancia: { icon: 'icons/vigilancia-192.png', badge: 'icons/badge-escudo-96.png', requireInteraction: true, silent: true },
  vigilancia_off: { icon: 'icons/vigilar-off-192.png', badge: 'icons/badge-escudo-96.png', silent: true, cerrarTras: 6000 },
  alerta: { icon: 'icons/alerta-192.png', badge: 'icons/badge-alerta-96.png', requireInteraction: true, vibrate: [500, 200, 500, 200, 900] }
};
self.addEventListener('push', e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (err) { d = { body: e.data ? e.data.text() : '' }; }
  const t = TIPOS[d.tipo] || TIPOS.info, tag = d.tag || undefined;
  e.waitUntil((async () => {
    await self.registration.showNotification(d.title || 'Mi Giulia', {
      body: d.body || '', tag, renotify: !!tag && !t.silent,
      icon: t.icon, badge: t.badge, requireInteraction: !!t.requireInteraction, silent: !!t.silent,
      vibrate: t.vibrate, data: { url: d.url || './#giulia' }
    });
    // «Vigilancia desactivada» sustituye a la de «activa» y se quita sola a los pocos segundos
    if (t.cerrarTras && tag) {
      await new Promise(r => setTimeout(r, t.cerrarTras));
      (await self.registration.getNotifications({ tag })).forEach(n => n.close());
    }
  })());
});
self.addEventListener('notificationclick', e => {
  e.notification.close();
  const url = new URL((e.notification.data && e.notification.data.url) || './', self.registration.scope).href;
  e.waitUntil(clients.matchAll({ type: 'window', includeUncontrolled: true }).then(ws => {
    for (const w of ws) {
      if (w.url.startsWith(self.registration.scope) && 'focus' in w) {
        return w.focus().then(f => (f && f.navigate ? f.navigate(url).catch(() => f) : f));
      }
    }
    return clients.openWindow(url);
  }));
});
