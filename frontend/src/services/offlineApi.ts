/**
 * 离线 API 代理层
 *
 * 在 api.ts 的基础上包一层：
 * - 联网时：正常请求，成功后将响应写入 IndexedDB
 * - 断网时：从 IndexedDB 读取缓存返回
 * - 写操作断网时：排入队列，联网后重放
 */
import {
  authFetch,
  getAuthToken,
  type PaperListItem,
  type ChatHistory,
  type CrossPaperChatHistory,
  type SessionList,
  type CrossPaperSessionList,
  type PdfLang,
} from './api'
import {
  cachePapers,
  getCachedPapers,
  cachePdf,
  getCachedPdf,
  cacheChatHistory,
  getCachedChatHistory,
  cacheCrossPaperChatHistory,
  getCachedCrossPaperChatHistory,
  cacheSessions,
  getCachedSessions,
  cacheCrossPaperSessions,
  getCachedCrossPaperSessions,
  cachePreferences,
  getCachedPreferences,
  enqueuePendingOp,
  drainPendingOps,
  type PendingOperation,
} from './cache'

const API_BASE = (import.meta.env.BASE_URL.replace(/\/$/, '')) + '/api'

export function isOnline(): boolean {
  return navigator.onLine
}

function sortPapersByDownloadTime(papers: PaperListItem[]): PaperListItem[] {
  return [...papers].sort((left, right) => {
    const leftTime = new Date(left.download_time).getTime()
    const rightTime = new Date(right.download_time).getTime()
    return leftTime - rightTime
  })
}

// ============ Network-first with cache fallback ============

async function networkFirstJson<T>(
  url: string,
  cacheGet: () => Promise<T | null>,
  cacheSet: (data: T) => Promise<void>,
): Promise<T> {
  const safeCacheGet = async (): Promise<T | null> => {
    try { return await cacheGet() } catch { return null }
  }

  if (isOnline()) {
    try {
      const response = await authFetch(url)
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const data: T = await response.json()
      cacheSet(data).catch(() => {})
      return data
    } catch (err) {
      const cached = await safeCacheGet()
      if (cached !== null) return cached
      throw err
    }
  }

  const cached = await safeCacheGet()
  if (cached !== null) return cached
  throw new Error('离线且无缓存数据')
}

// ============ Offline-queued writes ============

async function queuedWrite(url: string, method: string, body?: unknown): Promise<Response> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const token = getAuthToken()
  if (token) headers['Authorization'] = `Bearer ${token}`

  if (isOnline()) {
    return authFetch(url, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  }

  const op: PendingOperation = {
    url,
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    createdAt: Date.now(),
  }
  await enqueuePendingOp(op)

  return new Response(JSON.stringify({ queued: true }), {
    status: 202,
    headers: { 'Content-Type': 'application/json' },
  })
}

// ============ Replay pending operations on reconnect ============

let replayInProgress = false

export async function replayPendingOps(): Promise<{ succeeded: number; failed: number }> {
  if (replayInProgress || !isOnline()) return { succeeded: 0, failed: 0 }
  replayInProgress = true

  const ops = await drainPendingOps()
  let succeeded = 0
  let failed = 0

  for (const op of ops) {
    try {
      const resp = await fetch(op.url, {
        method: op.method,
        headers: op.headers,
        body: op.body,
      })
      if (resp.ok) succeeded++
      else failed++
    } catch {
      failed++
    }
  }

  replayInProgress = false
  return { succeeded, failed }
}

// ============ Offline-aware API functions ============

export async function fetchPapersOffline(): Promise<PaperListItem[]> {
  const papers = await networkFirstJson<PaperListItem[]>(
    `${API_BASE}/papers`,
    getCachedPapers,
    cachePapers,
  )
  return sortPapersByDownloadTime(papers)
}

export async function fetchPdfBlobOffline(paperId: string, lang: PdfLang = 'en'): Promise<Blob> {
  let cached: Blob | null = null
  try {
    cached = await getCachedPdf(paperId, lang)
  } catch {
    // IndexedDB 不可用（Safari 私密浏览等），跳过缓存
  }

  if (!isOnline()) {
    if (cached) return cached
    throw new Error('离线且无缓存 PDF')
  }

  try {
    const params = lang !== 'en' ? `?lang=${lang}` : ''
    const response = await authFetch(`${API_BASE}/papers/${paperId}/pdf${params}`)
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const blob = await response.blob()
    cachePdf(paperId, lang, blob).catch(() => {})
    return blob
  } catch (err) {
    if (cached) return cached
    throw err
  }
}

export async function getChatHistoryOffline(paperId: string, sessionId: string): Promise<ChatHistory> {
  return networkFirstJson<ChatHistory>(
    `${API_BASE}/chat/${paperId}/${sessionId}/history`,
    () => getCachedChatHistory(paperId, sessionId),
    (data) => cacheChatHistory(paperId, sessionId, data),
  )
}

export async function getCrossPaperChatHistoryOffline(sessionId: string): Promise<CrossPaperChatHistory> {
  return networkFirstJson<CrossPaperChatHistory>(
    `${API_BASE}/chat/cross-paper/${sessionId}/history`,
    () => getCachedCrossPaperChatHistory(sessionId),
    (data) => cacheCrossPaperChatHistory(sessionId, data),
  )
}

export async function listSessionsOffline(paperId: string): Promise<SessionList> {
  return networkFirstJson<SessionList>(
    `${API_BASE}/chat/${paperId}/sessions`,
    () => getCachedSessions(paperId),
    (data) => cacheSessions(paperId, data),
  )
}

export async function listCrossPaperSessionsOffline(): Promise<CrossPaperSessionList> {
  return networkFirstJson<CrossPaperSessionList>(
    `${API_BASE}/chat/cross-paper/sessions`,
    getCachedCrossPaperSessions,
    cacheCrossPaperSessions,
  )
}

export async function getPreferencesOffline(): Promise<Record<string, unknown>> {
  return networkFirstJson<Record<string, unknown>>(
    `${API_BASE}/preferences`,
    getCachedPreferences,
    cachePreferences,
  )
}

export async function updatePreferencesOffline(partial: Record<string, unknown>): Promise<void> {
  const resp = await queuedWrite(`${API_BASE}/preferences`, 'PUT', partial)
  if (resp.status !== 202) {
    if (!resp.ok) throw new Error('Failed to update preferences')
  }
  const current = await getCachedPreferences()
  await cachePreferences({ ...current, ...partial })
}

export async function updateChatHistoryOffline(
  paperId: string,
  sessionId: string,
  messages: unknown[],
  forks?: Record<string, unknown>,
): Promise<void> {
  const resp = await queuedWrite(
    `${API_BASE}/chat/${paperId}/${sessionId}/history`,
    'PUT',
    { messages, forks },
  )
  if (resp.status !== 202 && !resp.ok) {
    throw new Error('Failed to update chat history')
  }
}

export async function updateCrossPaperChatHistoryOffline(
  sessionId: string,
  messages: unknown[],
  forks?: Record<string, unknown>,
): Promise<void> {
  const resp = await queuedWrite(
    `${API_BASE}/chat/cross-paper/${sessionId}/history`,
    'PUT',
    { messages, forks },
  )
  if (resp.status !== 202 && !resp.ok) {
    throw new Error('Failed to update cross-paper chat history')
  }
}

// ============ Auto-replay on reconnect ============

export function setupOfflineListeners(): void {
  window.addEventListener('online', () => {
    replayPendingOps().catch(() => {})
  })
}
