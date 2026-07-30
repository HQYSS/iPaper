import { afterEach, describe, expect, it } from 'vitest'
import { drainPendingOps, getCachedPreferences } from './cache'
import { updatePreferencesOffline } from './offlineApi'

function setOnline(value: boolean): void {
  Object.defineProperty(navigator, 'onLine', {
    configurable: true,
    value,
  })
}

describe('offline API writes', () => {
  afterEach(async () => {
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
})
