/**
 * API 服务封装
 */

const API_BASE = (import.meta.env.BASE_URL.replace(/\/$/, '')) + '/api'

// ============ 论文 API ============

export interface Paper {
  arxiv_id: string
  title: string
  title_zh?: string
  summary: string
  authors: string[]
  download_time: string
  has_latex?: boolean
  translation_status?: string
  translation_progress?: number
  pdf_path?: string
}

export interface PaperListItem {
  arxiv_id: string
  title: string
  title_zh?: string
  summary: string
  authors: string[]
  download_time: string
}

export async function fetchPapers(): Promise<PaperListItem[]> {
  const response = await fetch(`${API_BASE}/papers`)
  if (!response.ok) {
    throw new Error('Failed to fetch papers')
  }
  return response.json()
}

export async function addPaper(arxivInput: string): Promise<Paper> {
  const response = await fetch(`${API_BASE}/papers`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ arxiv_input: arxivInput }),
  })
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || 'Failed to add paper')
  }
  return response.json()
}

export async function getPaper(paperId: string): Promise<Paper> {
  const response = await fetch(`${API_BASE}/papers/${paperId}`)
  if (!response.ok) {
    throw new Error('Failed to get paper')
  }
  return response.json()
}

export async function deletePaper(paperId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/papers/${paperId}`, {
    method: 'DELETE',
  })
  if (!response.ok) {
    throw new Error('Failed to delete paper')
  }
}

export type PdfLang = 'en' | 'zh' | 'bilingual'

export function getPdfUrl(paperId: string, lang: PdfLang = 'en'): string {
  const params = lang !== 'en' ? `?lang=${lang}` : ''
  return `${API_BASE}/papers/${paperId}/pdf${params}`
}

export interface TranslationStatus {
  zh: boolean
  bilingual: boolean
}

export async function getTranslations(paperId: string): Promise<TranslationStatus> {
  const response = await fetch(`${API_BASE}/papers/${paperId}/translations`)
  if (!response.ok) return { zh: false, bilingual: false }
  return response.json()
}

// ============ 对话 API ============

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface ChatHistory {
  paper_id: string
  messages: ChatMessage[]
}

export async function getChatHistory(paperId: string): Promise<ChatHistory> {
  const response = await fetch(`${API_BASE}/chat/${paperId}/history`)
  if (!response.ok) {
    throw new Error('Failed to get chat history')
  }
  return response.json()
}

export async function clearChatHistory(paperId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/chat/${paperId}/history`, {
    method: 'DELETE',
  })
  if (!response.ok) {
    throw new Error('Failed to clear chat history')
  }
}

export async function* sendMessage(
  paperId: string,
  message: string,
  selectedText?: string
): AsyncGenerator<{ type: string; content?: string; full_response?: string; message?: string }> {
  const response = await fetch(`${API_BASE}/chat/${paperId}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      message,
      selected_text: selectedText,
    }),
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || 'Failed to send message')
  }

  const reader = response.body?.getReader()
  if (!reader) {
    throw new Error('No response body')
  }

  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = JSON.parse(line.slice(6))
        yield data
      }
    }
  }
}

// ============ 配置 API ============

export interface Config {
  llm: {
    api_base: string
    api_key_configured: boolean
    model: string
    temperature: number
    max_tokens: number
  }
  data_dir: string
}

export async function getConfig(): Promise<Config> {
  const response = await fetch(`${API_BASE}/config`)
  if (!response.ok) {
    throw new Error('Failed to get config')
  }
  return response.json()
}

export async function updateLLMConfig(config: {
  api_key?: string
  model?: string
  temperature?: number
  max_tokens?: number
}): Promise<void> {
  const response = await fetch(`${API_BASE}/config/llm`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(config),
  })
  if (!response.ok) {
    throw new Error('Failed to update config')
  }
}

// ============ 用户画像 API ============

export interface ProfileSignal {
  type: string
  description: string
  evidence?: string
  context?: string
}

export interface ProfileEdit {
  operation: string
  section?: string
  content?: string
  old_text?: string
  new_text?: string
  reason?: string
}

export interface PendingProfileUpdate {
  has_updates: boolean
  timestamp?: string
  paper_title?: string
  summary?: string
  signals?: ProfileSignal[]
  edits?: ProfileEdit[]
}

export async function getPendingProfileUpdates(): Promise<PendingProfileUpdate> {
  const response = await fetch(`${API_BASE}/profile/pending-updates`)
  if (!response.ok) {
    throw new Error('Failed to get pending profile updates')
  }
  return response.json()
}

export async function applyProfileUpdates(): Promise<void> {
  const response = await fetch(`${API_BASE}/profile/apply-updates`, {
    method: 'POST',
  })
  if (!response.ok) {
    throw new Error('Failed to apply profile updates')
  }
}

export async function rejectProfileUpdates(): Promise<void> {
  const response = await fetch(`${API_BASE}/profile/reject-updates`, {
    method: 'POST',
  })
  if (!response.ok) {
    throw new Error('Failed to reject profile updates')
  }
}

export async function triggerProfileAnalysis(paperId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/profile/trigger-analysis`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ paper_id: paperId }),
  })
  if (!response.ok) {
    throw new Error('Failed to trigger profile analysis')
  }
}

