const summaryEl = document.getElementById('summary')
const statusEl = document.getElementById('status')
const importButton = document.getElementById('importButton')
const openButton = document.getElementById('openButton')

let activeTabUrl = ''
let lastImportedPaperId = null

function sendMessage(message) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(message, resolve)
  })
}

function setStatus(text, tone = 'muted') {
  statusEl.textContent = text
  statusEl.dataset.tone = tone
}

function setBusy(busy) {
  importButton.disabled = busy
  importButton.textContent = busy ? '导入中...' : '导入当前页面'
}

async function getActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
  return tab
}

async function refreshImportInfo() {
  const tab = await getActiveTab()
  activeTabUrl = tab?.url || ''

  const info = await sendMessage({
    type: 'ipaper:get-import-info',
    url: activeTabUrl,
  })

  if (!info?.ok) {
    summaryEl.textContent = info?.error || '当前页面不可导入'
    importButton.disabled = true
    return
  }

  summaryEl.textContent = info.source === 'arxiv'
    ? '检测到 arXiv 论文，将按 arXiv ID 导入并支持后续中文翻译。'
    : '检测到 PDF URL，将按普通 PDF 导入。'
  importButton.disabled = false
}

importButton.addEventListener('click', async () => {
  setBusy(true)
  setStatus('正在连接本地 iPaper...')

  const result = await sendMessage({
    type: 'ipaper:import-url',
    url: activeTabUrl,
  })

  setBusy(false)

  if (!result?.ok) {
    setStatus(result?.error || '导入失败', 'error')
    return
  }

  const paperId = result.paper?.arxiv_id || '论文'
  lastImportedPaperId = result.paper?.arxiv_id || null
  setStatus(`已导入：${paperId}`, 'success')
})

openButton.addEventListener('click', () => {
  sendMessage({ type: 'ipaper:open-app', paperId: lastImportedPaperId })
})

refreshImportInfo().catch((error) => {
  summaryEl.textContent = '读取当前页面失败'
  setStatus(error.message || String(error), 'error')
})
