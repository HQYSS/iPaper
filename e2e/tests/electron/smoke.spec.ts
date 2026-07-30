import { _electron as electron, expect, test } from '@playwright/test'
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
const testDir = path.dirname(fileURLToPath(import.meta.url))
const projectRoot = path.resolve(testDir, '..', '..', '..')
const electronDir = path.join(projectRoot, 'electron')
const bootstrapPath = path.join(projectRoot, 'e2e', 'electron', 'bootstrap.cjs')
const preloadPath = path.join(electronDir, 'preload.js')

test('preload 暴露 electronAPI.isElectron', async () => {
  const electronModule = require.resolve('electron', { paths: [electronDir] })
  const executablePath = require(electronModule) as string
  const app = await electron.launch({
    executablePath,
    args: [bootstrapPath, preloadPath],
  })

  try {
    const window = await app.firstWindow()
    await expect(window.getByText('iPaper Electron E2E')).toBeVisible()
    await expect.poll(() =>
      window.evaluate(() => window.electronAPI?.isElectron),
    ).toBe(true)

    const api = await window.evaluate(() => window.electronAPI)
    expect(api?.platform).toBeTruthy()
    expect(api?.versions.electron).toBeTruthy()
  } finally {
    await app.close()
  }
})
