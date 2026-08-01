import { afterEach, describe, expect, it, vi } from 'vitest'
import { drainPendingOps, getCachedPreferences } from './cache'
import { replayPendingOps, updatePreferencesOffline } from './offlineApi'

function setOnline(value: boolean): void {
  Object.defineProperty(navigator, 'onLine', {
    configurable: true,
    value,
  })
}

describe('offline API writes', () => {
  afterEach(async () => {
    vi.restoreAllMocks()
    setOnline(true)
    await drainPendingOps()
  })

  it('queues an offline write and updates the IndexedDB cache', async () => {
    setOnline(false)

    await updatePreferencesOffline({ theme: 'dark', fontSize: 16 })

    expect(await getCachedPreferences()).toEqual({ theme: 'dark', fontSize: 16 })
    const queued = await drainPendingOps()
    expect(queued).toHaveLength(1)
    expect(queued[0]).toMatchObject({
      method: 'PUT',
      body: JSON.stringify({ theme: 'dark', fontSize: 16 }),
    })
    expect(queued[0].url).toMatch(/\/api\/preferences$/)
  })

  it('requeues failed replay operations with retry metadata', async () => {
    setOnline(false)
    await updatePreferencesOffline({ theme: 'dark' })
    setOnline(true)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 503 })))

    const result = await replayPendingOps()

    expect(result).toEqual({ succeeded: 0, failed: 1 })
    const queued = await drainPendingOps()
    expect(queued).toHaveLength(1)
    expect(queued[0]).toMatchObject({
      retryCount: 1,
      lastError: 'HTTP 503',
    })
  })

  it('stops at the first retryable failure and preserves operation order', async () => {
    setOnline(false)
    await updatePreferencesOffline({ revision: 1 })
    await updatePreferencesOffline({ revision: 2 })
    setOnline(true)
    const fetchMock = vi.fn().mockResolvedValue(new Response('', { status: 503 }))
    vi.stubGlobal('fetch', fetchMock)

    expect(await replayPendingOps()).toEqual({ succeeded: 0, failed: 1 })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const queued = await drainPendingOps()
    expect(queued).toHaveLength(2)
    expect(queued[0].body).toBe(JSON.stringify({ revision: 1 }))
    expect(queued[1].body).toBe(JSON.stringify({ revision: 2 }))
  })
})
