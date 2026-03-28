import { openDB, type DBSchema, type IDBPDatabase } from 'idb'
import type { PaperListItem, ChatHistory, CrossPaperChatHistory, SessionList, CrossPaperSessionList } from './api'

const DB_NAME = 'ipaper-offline'
const DB_VERSION = 1
const MAX_CACHE_BYTES = 500 * 1024 * 1024 // 500 MB

interface IPaperDB extends DBSchema {
  papers: {
    key: string // arxiv_id
    value: PaperListItem & { cached_at: number }
  }
  pdfs: {
    key: string // `${paperId}:${lang}`
    value: { blob: Blob; cached_at: number; size: number }
  }
  chats: {
    key: string // `${paperId}:${sessionId}` or `cp:${sessionId}`
    value: { data: ChatHistory | CrossPaperChatHistory; cached_at: number }
  }
  sessions: {
    key: string // `paper:${paperId}` or `cross-paper`
    value: { data: SessionList | CrossPaperSessionList; cached_at: number }
  }
  preferences: {
    key: string // 'current'
    value: { data: Record<string, unknown>; cached_at: number }
  }
  pendingOps: {
    key: number // auto-incremented
    value: PendingOperation
    indexes: { 'by-created': number }
  }
}

export interface PendingOperation {
  url: string
  method: string
  headers: Record<string, string>
  body?: string
  createdAt: number
}

let dbPromise: Promise<IDBPDatabase<IPaperDB>> | null = null

function getDB(): Promise<IDBPDatabase<IPaperDB>> {
  if (!dbPromise) {
    dbPromise = openDB<IPaperDB>(DB_NAME, DB_VERSION, {
      upgrade(db) {
        if (!db.objectStoreNames.contains('papers'))
          db.createObjectStore('papers', { keyPath: 'arxiv_id' })
        if (!db.objectStoreNames.contains('pdfs'))
          db.createObjectStore('pdfs')
        if (!db.objectStoreNames.contains('chats'))
          db.createObjectStore('chats')
        if (!db.objectStoreNames.contains('sessions'))
          db.createObjectStore('sessions')
        if (!db.objectStoreNames.contains('preferences'))
          db.createObjectStore('preferences')
        if (!db.objectStoreNames.contains('pendingOps')) {
          const pendingStore = db.createObjectStore('pendingOps', { autoIncrement: true })
          pendingStore.createIndex('by-created', 'createdAt')
        }
      },
    }).catch((err) => {
      dbPromise = null
      throw err
    })
  }
  return dbPromise
}

// ============ Papers ============

export async function cachePapers(papers: PaperListItem[]): Promise<void> {
  const db = await getDB()
  const tx = db.transaction('papers', 'readwrite')
  const now = Date.now()
  await Promise.all([
    ...papers.map(p => tx.store.put({ ...p, cached_at: now })),
    tx.done,
  ])
}

export async function getCachedPapers(): Promise<PaperListItem[] | null> {
  const db = await getDB()
  const all = await db.getAll('papers')
  if (all.length === 0) return null
  return all.map(({ cached_at: _, ...rest }) => rest as PaperListItem)
}

// ============ PDFs ============

export async function cachePdf(paperId: string, lang: string, blob: Blob): Promise<void> {
  const db = await getDB()
  const key = `${paperId}:${lang}`
  await db.put('pdfs', { blob, cached_at: Date.now(), size: blob.size }, key)
  await evictIfNeeded()
}

export async function getCachedPdf(paperId: string, lang: string): Promise<Blob | null> {
  const db = await getDB()
  const entry = await db.get('pdfs', `${paperId}:${lang}`)
  if (!entry) return null
  await db.put('pdfs', { ...entry, cached_at: Date.now() }, `${paperId}:${lang}`)
  return entry.blob
}

// ============ Chat History ============

export async function cacheChatHistory(paperId: string, sessionId: string, data: ChatHistory): Promise<void> {
  const db = await getDB()
  await db.put('chats', { data, cached_at: Date.now() }, `${paperId}:${sessionId}`)
}

export async function getCachedChatHistory(paperId: string, sessionId: string): Promise<ChatHistory | null> {
  const db = await getDB()
  const entry = await db.get('chats', `${paperId}:${sessionId}`)
  return entry?.data as ChatHistory | null ?? null
}

export async function cacheCrossPaperChatHistory(sessionId: string, data: CrossPaperChatHistory): Promise<void> {
  const db = await getDB()
  await db.put('chats', { data, cached_at: Date.now() }, `cp:${sessionId}`)
}

export async function getCachedCrossPaperChatHistory(sessionId: string): Promise<CrossPaperChatHistory | null> {
  const db = await getDB()
  const entry = await db.get('chats', `cp:${sessionId}`)
  return entry?.data as CrossPaperChatHistory | null ?? null
}

// ============ Sessions ============

export async function cacheSessions(paperId: string, data: SessionList): Promise<void> {
  const db = await getDB()
  await db.put('sessions', { data, cached_at: Date.now() }, `paper:${paperId}`)
}

export async function getCachedSessions(paperId: string): Promise<SessionList | null> {
  const db = await getDB()
  const entry = await db.get('sessions', `paper:${paperId}`)
  return entry?.data as SessionList | null ?? null
}

export async function cacheCrossPaperSessions(data: CrossPaperSessionList): Promise<void> {
  const db = await getDB()
  await db.put('sessions', { data, cached_at: Date.now() }, 'cross-paper')
}

export async function getCachedCrossPaperSessions(): Promise<CrossPaperSessionList | null> {
  const db = await getDB()
  const entry = await db.get('sessions', 'cross-paper')
  return entry?.data as CrossPaperSessionList | null ?? null
}

// ============ Preferences ============

export async function cachePreferences(data: Record<string, unknown>): Promise<void> {
  const db = await getDB()
  await db.put('preferences', { data, cached_at: Date.now() }, 'current')
}

export async function getCachedPreferences(): Promise<Record<string, unknown> | null> {
  const db = await getDB()
  const entry = await db.get('preferences', 'current')
  return entry?.data ?? null
}

// ============ Pending Operations (Offline Write Queue) ============

export async function enqueuePendingOp(op: PendingOperation): Promise<void> {
  const db = await getDB()
  await db.add('pendingOps', op)
}

export async function drainPendingOps(): Promise<PendingOperation[]> {
  const db = await getDB()
  const tx = db.transaction('pendingOps', 'readwrite')
  const all = await tx.store.index('by-created').getAll()
  await tx.store.clear()
  await tx.done
  return all
}

export async function getPendingOpsCount(): Promise<number> {
  const db = await getDB()
  return db.count('pendingOps')
}

// ============ LRU Eviction ============

async function evictIfNeeded(): Promise<void> {
  const db = await getDB()
  const allPdfs = await db.getAll('pdfs')
  const allKeys = await db.getAllKeys('pdfs')

  const entries = allPdfs.map((v, i) => ({ key: allKeys[i], ...v }))
  const totalSize = entries.reduce((sum, e) => sum + e.size, 0)

  if (totalSize <= MAX_CACHE_BYTES) return

  entries.sort((a, b) => a.cached_at - b.cached_at)

  let freed = 0
  const target = totalSize - MAX_CACHE_BYTES
  const tx = db.transaction('pdfs', 'readwrite')

  for (const entry of entries) {
    if (freed >= target) break
    await tx.store.delete(entry.key)
    freed += entry.size
  }

  await tx.done
}

// ============ Clear All Cache ============

export async function clearAllCache(): Promise<void> {
  const db = await getDB()
  const tx = db.transaction(['papers', 'pdfs', 'chats', 'sessions', 'preferences'], 'readwrite')
  await Promise.all([
    tx.objectStore('papers').clear(),
    tx.objectStore('pdfs').clear(),
    tx.objectStore('chats').clear(),
    tx.objectStore('sessions').clear(),
    tx.objectStore('preferences').clear(),
    tx.done,
  ])
}
