const API_BASE = 'http://127.0.0.1:3000/api'
const BACKEND_HEALTH_URL = 'http://127.0.0.1:3000/'
const APP_URL = 'http://localhost:5173/'
const NATIVE_HOST_NAME = 'com.ipaper.native_host'

const IMPORT_CONTEXT_MENU_ID = 'ipaper-import-current'
const IMPORT_LINK_CONTEXT_MENU_ID = 'ipaper-import-link'

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 3000) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await fetch(url, { ...options, signal: controller.signal })
  } finally {
    clearTimeout(timer)
  }
}

async function isBackendReady() {
  try {
    const response = await fetchWithTimeout(BACKEND_HEALTH_URL, { method: 'GET' }, 1200)
    if (!response.ok) return false
    const data = await response.json().catch(() => null)
    return data?.status === 'ok'
  } catch {
    return false
  }
}

function sendNativeMessage(message) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendNativeMessage(NATIVE_HOST_NAME, message, (response) => {
      const error = chrome.runtime.lastError
      if (error) {
        reject(new Error(error.message))
        return
      }
      resolve(response)
    })
  })
}

async function startIpaper() {
  const response = await sendNativeMessage({ action: 'start_ipaper' })
  if (!response?.ok) {
    throw new Error(response?.error || '无法启动 iPaper')
  }
  return response
}

async function openIpaperApp() {
  const response = await sendNativeMessage({ action: 'open_ipaper' })
  if (!response?.ok) {
    throw new Error(response?.error || '无法打开 iPaper')
  }
  return response
}

async function requestOpenPaper(paperId) {
  if (!paperId) return
  const response = await fetchWithTimeout(
    `${API_BASE}/papers/open-request`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paper_id: paperId }),
    },
    5000,
  )
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}))
    throw new Error(payload.detail || `无法请求打开论文：HTTP ${response.status}`)
  }
}

async function openIpaperForPaper(paperId) {
  await ensureBackendReady()
  if (paperId) {
    await requestOpenPaper(paperId)
  }

  try {
    await openIpaperApp()
    return { ok: true, opened: 'app' }
  } catch (error) {
    const fallbackUrl = paperId ? `${APP_URL}?paper=${encodeURIComponent(paperId)}` : APP_URL
    await chrome.tabs.create({ url: fallbackUrl })
    return { ok: true, opened: 'web', warning: error.message || String(error) }
  }
}

async function ensureBackendReady() {
  if (await isBackendReady()) return { started: false }

  try {
    await startIpaper()
  } catch (error) {
    throw new Error(`本地 iPaper 未启动，且无法自动启动：${error.message}`)
  }

  for (let i = 0; i < 30; i += 1) {
    if (await isBackendReady()) return { started: true }
    await delay(1000)
  }

  throw new Error('已尝试启动 iPaper，但本地后端仍未就绪')
}

function stripArxivVersion(arxivId) {
  return arxivId.replace(/v\d+$/i, '')
}

function normalizeArxivPath(pathname) {
  const match = pathname.match(/^\/(?:abs|html|pdf)\/(.+?)\/?$/i)
  if (!match) return null

  let arxivId = decodeURIComponent(match[1])
  arxivId = arxivId.replace(/\.pdf$/i, '')
  arxivId = arxivId.split(/[?#]/)[0]
  arxivId = stripArxivVersion(arxivId)

  if (!arxivId) return null
  return `https://arxiv.org/abs/${arxivId}`
}

function isLikelyPdfUrl(url) {
  try {
    const parsed = new URL(url)
    return /\.pdf$/i.test(parsed.pathname) || parsed.pathname.toLowerCase().includes('/pdf/')
  } catch {
    return false
  }
}

function getImportInput(rawUrl) {
  if (!rawUrl) {
    return { ok: false, error: '当前页面没有可导入的 URL' }
  }

  let parsed
  try {
    parsed = new URL(rawUrl)
  } catch {
    return { ok: false, error: '当前页面 URL 无效' }
  }

  if (parsed.hostname === 'arxiv.org') {
    const arxivInput = normalizeArxivPath(parsed.pathname)
    if (arxivInput) {
      return {
        ok: true,
        input: arxivInput,
        source: 'arxiv',
      }
    }
  }

  if (isLikelyPdfUrl(rawUrl)) {
    return {
      ok: true,
      input: rawUrl,
      source: 'pdf_url',
    }
  }

  return {
    ok: false,
    error: '当前页面不是 arXiv abs/html/pdf 或普通 PDF URL',
  }
}

function isArxivArticlePage(rawUrl) {
  try {
    const parsed = new URL(rawUrl)
    return parsed.hostname === 'arxiv.org' && /^\/(?:abs|html)\//i.test(parsed.pathname)
  } catch {
    return false
  }
}

async function injectArxivButton(tabId, url) {
  if (!tabId || !isArxivArticlePage(url)) return
  try {
    await chrome.scripting.insertCSS({
      target: { tabId },
      files: ['src/content.css'],
    })
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ['src/content.js'],
    })
  } catch {
    // The declarative content script usually handles this. Programmatic injection
    // is a best-effort fallback for Chrome startup/load-extension edge cases.
  }
}

function cleanMetadataText(value) {
  if (!value || typeof value !== 'string') return ''
  return value.replace(/\s+/g, ' ').trim()
}

function normalizePageMetadata(metadata, sourceUrl) {
  if (!metadata || typeof metadata !== 'object') {
    return { source_url: sourceUrl }
  }

  const authors = Array.isArray(metadata.authors)
    ? metadata.authors.map(cleanMetadataText).filter(Boolean).slice(0, 50)
    : []

  return {
    title: cleanMetadataText(metadata.title) || undefined,
    summary: cleanMetadataText(metadata.summary) || undefined,
    authors: authors.length ? authors : undefined,
    source_url: cleanMetadataText(metadata.sourceUrl) || sourceUrl,
  }
}

async function importToIpaper(rawUrl, pageMetadata) {
  const normalized = getImportInput(rawUrl)
  if (!normalized.ok) return normalized

  await ensureBackendReady()
  const body = { arxiv_input: normalized.input }
  if (normalized.source === 'arxiv') {
    Object.assign(body, normalizePageMetadata(pageMetadata, rawUrl))
  }

  const response = await fetchWithTimeout(
    `${API_BASE}/papers`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
    60000,
  )

  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(payload.detail || `导入失败：HTTP ${response.status}`)
  }

  return {
    ok: true,
    paper: payload,
    input: normalized.input,
    source: normalized.source,
    appUrl: APP_URL,
  }
}

function setBadge(text, color = '#2563eb') {
  chrome.action.setBadgeText({ text })
  chrome.action.setBadgeBackgroundColor({ color })
}

async function importFromContext(rawUrl) {
  try {
    setBadge('...')
    const result = await importToIpaper(rawUrl)
    await openIpaperForPaper(result.paper?.arxiv_id)
    setBadge('OK', '#16a34a')
  } catch {
    setBadge('ERR', '#dc2626')
  }
  setTimeout(() => chrome.action.setBadgeText({ text: '' }), 4000)
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: IMPORT_CONTEXT_MENU_ID,
    title: '导入当前页面到 iPaper',
    contexts: ['page'],
  })
  chrome.contextMenus.create({
    id: IMPORT_LINK_CONTEXT_MENU_ID,
    title: '导入这个链接到 iPaper',
    contexts: ['link'],
  })
})

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === IMPORT_LINK_CONTEXT_MENU_ID) {
    importFromContext(info.linkUrl)
    return
  }
  if (info.menuItemId === IMPORT_CONTEXT_MENU_ID) {
    importFromContext(tab?.url)
  }
})

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === 'complete') {
    injectArxivButton(tabId, tab.url)
  }
})

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  ;(async () => {
    if (message?.type === 'ipaper:get-import-info') {
      sendResponse(getImportInput(message.url || sender.tab?.url))
      return
    }

    if (message?.type === 'ipaper:import-url') {
      const result = await importToIpaper(message.url || sender.tab?.url, message.metadata)
      sendResponse(result)
      return
    }

    if (message?.type === 'ipaper:open-app') {
      const result = await openIpaperForPaper(message.paperId)
      sendResponse(result)
      return
    }

    sendResponse({ ok: false, error: '未知消息类型' })
  })().catch((error) => {
    sendResponse({ ok: false, error: error.message || String(error) })
  })
  return true
})
