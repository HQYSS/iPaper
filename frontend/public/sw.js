const CACHE_NAME = 'ipaper-static-v3'

const STATIC_EXTENSIONS = [
  '.js',
  '.css',
  '.woff2',
  '.woff',
  '.ttf',
  '.png',
  '.svg',
  '.ico',
  '.webmanifest',
]

self.addEventListener('install', (event) => {
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => k.startsWith('ipaper-static-') && k !== CACHE_NAME)
          .map((k) => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  )
})

function isStaticAsset(url) {
  const pathname = new URL(url).pathname
  return STATIC_EXTENSIONS.some((ext) => pathname.endsWith(ext))
}

function isHtmlNavigation(request) {
  return request.mode === 'navigate' || request.headers.get('accept')?.includes('text/html')
}

function isApiRequest(url) {
  return new URL(url).pathname.includes('/api/')
}

self.addEventListener('fetch', (event) => {
  const { request } = event

  if (isApiRequest(request.url)) return

  if (isHtmlNavigation(request)) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const clone = response.clone()
          caches.open(CACHE_NAME).then((cache) => cache.put(request, clone))
          return response
        })
        .catch(() => caches.match(request))
    )
    return
  }

  if (isStaticAsset(request.url)) {
    event.respondWith(
      caches.match(request).then((cached) => {
        if (cached) return cached
        return fetch(request).then((response) => {
          if (response.ok) {
            const clone = response.clone()
            caches.open(CACHE_NAME).then((cache) => cache.put(request, clone))
          }
          return response
        })
      })
    )
    return
  }
})
