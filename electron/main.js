const { app, BrowserWindow, shell } = require('electron')
const path = require('path')
const os = require('os')
const fs = require('fs')
const { spawn } = require('child_process')

// 开发模式检测
const isDev = process.argv.includes('--dev') || process.env.NODE_ENV === 'development'
const LOCAL_API_BASE = 'http://127.0.0.1:3000/api'
const DEFAULT_SYNC_API_BASE = 'https://www.moshang.xyz/ipaper/api'
const LOCAL_CHANGE_POLL_MS = 3000
const REMOTE_SYNC_POLL_MS = 15000
const LOCAL_PUSH_DEBOUNCE_MS = 2000

let mainWindow
let backendProcess
const syncState = {
  inFlight: false,
  rerunRequested: false,
  debounceTimer: null,
  localPollTimer: null,
  remotePollTimer: null,
  lastLocalFingerprint: '',
  lastRemoteFingerprint: '',
}

// 启动 Python 后端
function startBackend() {
  const backendPath = path.join(__dirname, '..', 'backend')

  // 开发模式下使用 python 直接运行
  if (isDev) {
    backendProcess = spawn('python', ['main.py'], {
      cwd: backendPath,
      stdio: 'inherit'
    })
  } else {
    // 生产模式下使用打包后的可执行文件
    const backendExe = process.platform === 'win32' ? 'ipaper-backend.exe' : 'ipaper-backend'
    const backendExePath = path.join(process.resourcesPath, 'backend', backendExe)

    backendProcess = spawn(backendExePath, [], {
      cwd: path.dirname(backendExePath),
      stdio: 'inherit'
    })
  }

  backendProcess.on('error', (err) => {
    console.error('Failed to start backend:', err)
  })

  backendProcess.on('exit', (code) => {
    console.log(`Backend process exited with code ${code}`)
  })
}

// 等待后端启动
async function waitForBackend(maxRetries = 30) {
  const http = require('http')

  for (let i = 0; i < maxRetries; i++) {
    try {
      await new Promise((resolve, reject) => {
        const req = http.get('http://127.0.0.1:3000/', (res) => {
          resolve(res)
        })
        req.on('error', reject)
        req.setTimeout(1000, () => {
          req.destroy()
          reject(new Error('Timeout'))
        })
      })
      console.log('Backend is ready')
      return true
    } catch (e) {
      console.log(`Waiting for backend... (${i + 1}/${maxRetries})`)
      await new Promise(r => setTimeout(r, 1000))
    }
  }

  throw new Error('Backend failed to start')
}

function readSyncConfig() {
  const configPath = path.join(os.homedir(), '.ipaper', 'config.json')
  if (!fs.existsSync(configPath)) {
    return { syncUrl: DEFAULT_SYNC_API_BASE, syncToken: '' }
  }

  try {
    const data = JSON.parse(fs.readFileSync(configPath, 'utf-8'))
    return {
      syncUrl: typeof data.sync_url === 'string' && data.sync_url.trim()
        ? data.sync_url.trim()
        : DEFAULT_SYNC_API_BASE,
      syncToken: typeof data.sync_token === 'string' ? data.sync_token.trim() : '',
    }
  } catch (error) {
    console.error('Failed to read sync config:', error)
    return { syncUrl: DEFAULT_SYNC_API_BASE, syncToken: '' }
  }
}

function normalizeSyncBase(syncUrl) {
  const trimmed = syncUrl.replace(/\/+$/, '')
  if (!trimmed) return ''
  if (trimmed.endsWith('/sync')) return trimmed
  if (trimmed.endsWith('/api')) return `${trimmed}/sync`
  return `${trimmed}/api/sync`
}

function getAuthHeaders(token, headers = {}) {
  if (!token) return headers
  return { ...headers, Authorization: `Bearer ${token}` }
}

function parseTimestamp(value) {
  if (!value) return 0
  const timestamp = Date.parse(value)
  return Number.isFinite(timestamp) ? timestamp : 0
}

function manifestFingerprint(manifest) {
  const papers = [...(manifest.papers || [])]
    .map((paper) => ({
      arxiv_id: paper.arxiv_id || '',
      updated_at: paper.updated_at || '',
    }))
    .sort((a, b) => a.arxiv_id.localeCompare(b.arxiv_id))
  const deletedPapers = [...(manifest.deleted_papers || [])]
    .map((paper) => ({
      arxiv_id: paper.arxiv_id || '',
      deleted_at: paper.deleted_at || '',
    }))
    .sort((a, b) => a.arxiv_id.localeCompare(b.arxiv_id))
  return JSON.stringify({
    papers,
    deleted_papers: deletedPapers,
    preferences_updated_at: manifest.preferences_updated_at || '',
    profile_updated_at: manifest.profile_updated_at || '',
  })
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options)
  if (!response.ok) {
    throw new Error(`${options.method || 'GET'} ${url} failed: ${response.status}`)
  }
  return response.json()
}

async function fetchBuffer(url, options = {}) {
  const response = await fetch(url, options)
  if (!response.ok) {
    throw new Error(`${options.method || 'GET'} ${url} failed: ${response.status}`)
  }
  return Buffer.from(await response.arrayBuffer())
}

async function putJson(url, body, token) {
  const response = await fetch(url, {
    method: 'PUT',
    headers: getAuthHeaders(token, { 'Content-Type': 'application/json' }),
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    throw new Error(`PUT ${url} failed: ${response.status}`)
  }
}

async function putBundle(url, paperId, bundle, token) {
  const form = new FormData()
  form.set('file', new Blob([bundle], { type: 'application/zip' }), `${paperId}.zip`)

  const response = await fetch(url, {
    method: 'PUT',
    headers: getAuthHeaders(token),
    body: form,
  })
  if (!response.ok) {
    throw new Error(`PUT ${url} failed: ${response.status}`)
  }
}

async function deletePaper(url, token) {
  const response = await fetch(url, {
    method: 'DELETE',
    headers: getAuthHeaders(token),
  })
  if (!response.ok) {
    throw new Error(`DELETE ${url} failed: ${response.status}`)
  }
}

async function syncPaperBundles(syncBase, syncToken, localManifest, remoteManifest) {
  const localPapers = new Map((localManifest.papers || []).map((paper) => [paper.arxiv_id, paper]))
  const remotePapers = new Map((remoteManifest.papers || []).map((paper) => [paper.arxiv_id, paper]))
  const localDeleted = new Map((localManifest.deleted_papers || []).map((paper) => [paper.arxiv_id, paper]))
  const remoteDeleted = new Map((remoteManifest.deleted_papers || []).map((paper) => [paper.arxiv_id, paper]))
  const paperIds = new Set([
    ...localPapers.keys(),
    ...remotePapers.keys(),
    ...localDeleted.keys(),
    ...remoteDeleted.keys(),
  ])

  for (const paperId of paperIds) {
    const localUpdatedAt = parseTimestamp(localPapers.get(paperId)?.updated_at)
    const remoteUpdatedAt = parseTimestamp(remotePapers.get(paperId)?.updated_at)
    const localDeletedAt = parseTimestamp(localDeleted.get(paperId)?.deleted_at)
    const remoteDeletedAt = parseTimestamp(remoteDeleted.get(paperId)?.deleted_at)
    const localDeleteWins = localDeletedAt > localUpdatedAt
    const remoteDeleteWins = remoteDeletedAt > remoteUpdatedAt

    if (remoteDeleteWins || localDeleteWins) {
      if (remoteDeletedAt > localDeletedAt && remoteDeletedAt > localUpdatedAt) {
        await deletePaper(`${LOCAL_API_BASE}/sync/papers/${paperId}`)
        console.log(`Applied remote deletion locally: ${paperId}`)
        continue
      }
      if (localDeletedAt > remoteDeletedAt && localDeletedAt > remoteUpdatedAt) {
        await deletePaper(`${syncBase}/papers/${paperId}`, syncToken)
        console.log(`Applied local deletion to cloud: ${paperId}`)
        continue
      }
      if (remoteDeletedAt > 0 && remoteDeletedAt === localDeletedAt) {
        continue
      }
    }

    if (remoteUpdatedAt > localUpdatedAt) {
      const bundle = await fetchBuffer(`${syncBase}/papers/${paperId}/bundle`, {
        headers: getAuthHeaders(syncToken),
      })
      await putBundle(`${LOCAL_API_BASE}/sync/papers/${paperId}/bundle`, paperId, bundle)
      console.log(`Synced paper from cloud: ${paperId}`)
      continue
    }

    if (localUpdatedAt > remoteUpdatedAt) {
      const bundle = await fetchBuffer(`${LOCAL_API_BASE}/sync/papers/${paperId}/bundle`)
      await putBundle(`${syncBase}/papers/${paperId}/bundle`, paperId, bundle, syncToken)
      console.log(`Synced paper to cloud: ${paperId}`)
    }
  }
}

async function syncDocument(name, localUpdatedAt, remoteUpdatedAt, localGetUrl, localPutUrl, remoteGetUrl, remotePutUrl, syncToken) {
  const localTs = parseTimestamp(localUpdatedAt)
  const remoteTs = parseTimestamp(remoteUpdatedAt)

  if (remoteTs > localTs) {
    const remoteData = await fetchJson(remoteGetUrl, { headers: getAuthHeaders(syncToken) })
    await putJson(localPutUrl, remoteData)
    console.log(`Synced ${name} from cloud`)
    return
  }

  if (localTs > remoteTs) {
    const localData = await fetchJson(localGetUrl)
    await putJson(remotePutUrl, localData, syncToken)
    console.log(`Synced ${name} to cloud`)
  }
}

async function fetchSyncManifests(syncBase, syncToken) {
  return Promise.all([
    fetchJson(`${LOCAL_API_BASE}/sync/manifest`),
    fetchJson(`${syncBase}/manifest`, { headers: getAuthHeaders(syncToken) }),
  ])
}

async function syncOnce(reason = 'manual') {
  const { syncUrl, syncToken } = readSyncConfig()
  const syncBase = normalizeSyncBase(syncUrl)

  if (!syncToken) {
    syncState.lastRemoteFingerprint = ''
    console.log(`Sync skipped (${reason}): sync token is not configured`)
    return
  }

  const [localManifest, remoteManifest] = await fetchSyncManifests(syncBase, syncToken)

  await syncPaperBundles(syncBase, syncToken, localManifest, remoteManifest)
  await syncDocument(
    'preferences',
    localManifest.preferences_updated_at,
    remoteManifest.preferences_updated_at,
    `${LOCAL_API_BASE}/sync/preferences`,
    `${LOCAL_API_BASE}/sync/preferences`,
    `${syncBase}/preferences`,
    `${syncBase}/preferences`,
    syncToken,
  )
  await syncDocument(
    'profile',
    localManifest.profile_updated_at,
    remoteManifest.profile_updated_at,
    `${LOCAL_API_BASE}/sync/profile`,
    `${LOCAL_API_BASE}/sync/profile`,
    `${syncBase}/profile`,
    `${syncBase}/profile`,
    syncToken,
  )

  const [finalLocalManifest, finalRemoteManifest] = await fetchSyncManifests(syncBase, syncToken)
  syncState.lastLocalFingerprint = manifestFingerprint(finalLocalManifest)
  syncState.lastRemoteFingerprint = manifestFingerprint(finalRemoteManifest)
  console.log(`Sync completed: ${reason}`)
}

function scheduleSync(reason, debounceMs = 0) {
  if (syncState.inFlight) {
    syncState.rerunRequested = true
    return
  }

  if (syncState.debounceTimer) {
    clearTimeout(syncState.debounceTimer)
  }

  syncState.debounceTimer = setTimeout(async () => {
    syncState.debounceTimer = null
    if (syncState.inFlight) {
      syncState.rerunRequested = true
      return
    }
    syncState.inFlight = true
    try {
      await syncOnce(reason)
    } catch (error) {
      console.error(`Sync failed (${reason}):`, error)
    } finally {
      syncState.inFlight = false
      if (syncState.rerunRequested) {
        syncState.rerunRequested = false
        scheduleSync('rerun', 500)
      }
    }
  }, debounceMs)
}

async function watchLocalChanges() {
  const { syncUrl, syncToken } = readSyncConfig()
  const syncBase = normalizeSyncBase(syncUrl)
  if (!syncBase || !syncToken) {
    syncState.lastLocalFingerprint = ''
    return
  }

  try {
    const localManifest = await fetchJson(`${LOCAL_API_BASE}/sync/manifest`)
    const fingerprint = manifestFingerprint(localManifest)
    if (!syncState.lastLocalFingerprint) {
      syncState.lastLocalFingerprint = fingerprint
      return
    }
    if (fingerprint !== syncState.lastLocalFingerprint) {
      syncState.lastLocalFingerprint = fingerprint
      scheduleSync('local-change', LOCAL_PUSH_DEBOUNCE_MS)
    }
  } catch (error) {
    console.error('Failed to watch local manifest:', error)
  }
}

function startSyncLoops() {
  if (syncState.localPollTimer || syncState.remotePollTimer) {
    return
  }

  syncState.localPollTimer = setInterval(() => {
    watchLocalChanges().catch((error) => {
      console.error('Local sync watcher failed:', error)
    })
  }, LOCAL_CHANGE_POLL_MS)

  syncState.remotePollTimer = setInterval(() => {
    scheduleSync('remote-poll')
  }, REMOTE_SYNC_POLL_MS)
}

function stopSyncLoops() {
  if (syncState.debounceTimer) {
    clearTimeout(syncState.debounceTimer)
    syncState.debounceTimer = null
  }
  if (syncState.localPollTimer) {
    clearInterval(syncState.localPollTimer)
    syncState.localPollTimer = null
  }
  if (syncState.remotePollTimer) {
    clearInterval(syncState.remotePollTimer)
    syncState.remotePollTimer = null
  }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1000,
    minHeight: 600,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js')
    },
    titleBarStyle: 'hiddenInset',
    trafficLightPosition: { x: 15, y: 15 }
  })

  // 开发模式加载 Vite 开发服务器
  if (isDev) {
    mainWindow.loadURL('http://localhost:5173')
  } else {
    // 生产模式加载打包后的文件
    mainWindow.loadFile(path.join(__dirname, '..', 'frontend', 'dist', 'index.html'))
  }

  // 外部链接使用系统浏览器打开
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })

  mainWindow.on('closed', () => {
    mainWindow = null
  })

  mainWindow.on('focus', () => {
    scheduleSync('window-focus')
  })
}

app.whenReady().then(async () => {
  // 启动后端
  startBackend()

  try {
    // 等待后端就绪
    await waitForBackend()

    try {
      await syncOnce('startup')
    } catch (error) {
      console.error('Startup sync failed:', error)
    }

    // 创建窗口
    createWindow()
    startSyncLoops()
  } catch (err) {
    console.error('Failed to start:', err)
    app.quit()
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow()
    }
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('before-quit', () => {
  stopSyncLoops()
  // 关闭后端进程
  if (backendProcess) {
    backendProcess.kill()
  }
})

