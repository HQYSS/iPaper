const BUTTON_ID = 'ipaper-import-button'
const STATUS_ID = 'ipaper-import-status'
let lastImportedPaperId = null

function sendMessage(message) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(message, resolve)
  })
}

function getMountTarget() {
  return (
    document.querySelector('h1.title') ||
    document.querySelector('.ltx_title_document') ||
    document.querySelector('main') ||
    document.body
  )
}

function setStatus(text, tone = 'muted') {
  const status = document.getElementById(STATUS_ID)
  if (!status) return
  status.textContent = text
  status.dataset.tone = tone
}

function setButtonBusy(button, busy) {
  button.disabled = busy
  button.textContent = busy ? '导入中...' : '导入 iPaper'
}

async function handleImport(button) {
  setButtonBusy(button, true)
  setStatus('正在连接本地 iPaper...', 'muted')

  const result = await sendMessage({
    type: 'ipaper:import-url',
    url: window.location.href,
  })

  setButtonBusy(button, false)

  if (!result?.ok) {
    setStatus(result?.error || '导入失败', 'error')
    return
  }

  const paperId = result.paper?.arxiv_id || '论文'
  lastImportedPaperId = result.paper?.arxiv_id || null
  setStatus(`已导入：${paperId}`, 'success')
}

function createImportWidget() {
  const wrapper = document.createElement('span')
  wrapper.className = 'ipaper-import-widget'

  const button = document.createElement('button')
  button.id = BUTTON_ID
  button.type = 'button'
  button.textContent = '导入 iPaper'
  button.className = 'ipaper-import-button'
  button.addEventListener('click', () => handleImport(button))

  const openLink = document.createElement('button')
  openLink.type = 'button'
  openLink.textContent = '打开 iPaper'
  openLink.className = 'ipaper-open-button'
  openLink.addEventListener('click', () => {
    sendMessage({ type: 'ipaper:open-app', paperId: lastImportedPaperId })
  })

  const status = document.createElement('span')
  status.id = STATUS_ID
  status.className = 'ipaper-import-status'
  status.dataset.tone = 'muted'

  wrapper.append(button, openLink, status)
  return wrapper
}

async function injectImportButton() {
  if (document.getElementById(BUTTON_ID)) return

  const info = await sendMessage({
    type: 'ipaper:get-import-info',
    url: window.location.href,
  })
  if (!info?.ok) return

  const target = getMountTarget()
  if (!target) return

  const widget = createImportWidget()
  if (target === document.body) {
    document.body.prepend(widget)
    return
  }

  target.insertAdjacentElement('afterend', widget)
}

injectImportButton()
