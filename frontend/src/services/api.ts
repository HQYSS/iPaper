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

// ============ 会话 API ============

export interface SessionMeta {
  id: string
  title: string
  created_at: string
  updated_at: string
}

export interface SessionList {
  sessions: SessionMeta[]
  last_active_session_id: string | null
}

export async function listSessions(paperId: string): Promise<SessionList> {
  const response = await fetch(`${API_BASE}/chat/${paperId}/sessions`)
  if (!response.ok) {
    throw new Error('Failed to list sessions')
  }
  return response.json()
}

export async function createSession(paperId: string, title?: string): Promise<SessionMeta> {
  const response = await fetch(`${API_BASE}/chat/${paperId}/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: title ?? null }),
  })
  if (!response.ok) {
    throw new Error('Failed to create session')
  }
  return response.json()
}

export async function deleteSession(paperId: string, sessionId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/chat/${paperId}/sessions/${sessionId}`, {
    method: 'DELETE',
  })
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || 'Failed to delete session')
  }
}

// ============ 对话 API ============

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  quotes?: QuoteInput[]
  reasoning?: string
}

export interface ChatDraft {
  input: string
  quotes?: QuoteInput[]
}

export interface ForkData {
  alternatives: ChatMessage[][]
  active: number
}

export interface ChatHistory {
  paper_id: string
  session_id: string
  messages: ChatMessage[]
  forks?: Record<string, ForkData>
  draft?: ChatDraft
}

export async function getChatHistory(paperId: string, sessionId: string): Promise<ChatHistory> {
  const response = await fetch(`${API_BASE}/chat/${paperId}/${sessionId}/history`)
  if (!response.ok) {
    throw new Error('Failed to get chat history')
  }
  return response.json()
}

export async function updateChatHistory(
  paperId: string,
  sessionId: string,
  messages: ChatMessage[],
  forks?: Record<string, ForkData>
): Promise<void> {
  const response = await fetch(`${API_BASE}/chat/${paperId}/${sessionId}/history`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, forks }),
  })
  if (!response.ok) {
    throw new Error('Failed to update chat history')
  }
}

export async function updateChatDraft(
  paperId: string,
  sessionId: string,
  draft: ChatDraft
): Promise<void> {
  const response = await fetch(`${API_BASE}/chat/${paperId}/${sessionId}/history/draft`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ draft }),
  })
  if (!response.ok) {
    throw new Error('Failed to update chat draft')
  }
}

export async function clearChatHistory(paperId: string, sessionId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/chat/${paperId}/${sessionId}/history`, {
    method: 'DELETE',
  })
  if (!response.ok) {
    throw new Error('Failed to clear chat history')
  }
}

export interface QuoteInput {
  text: string
  source: 'pdf' | 'chat'
}

export async function* sendMessage(
  paperId: string,
  sessionId: string,
  message: string,
  quotes?: QuoteInput[],
  signal?: AbortSignal
): AsyncGenerator<{ type: string; content?: string; full_response?: string; message?: string }> {
  const response = await fetch(`${API_BASE}/chat/${paperId}/${sessionId}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      message,
      quotes: quotes && quotes.length > 0 ? quotes : undefined,
    }),
    signal,
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
        try {
          const data = JSON.parse(line.slice(6))
          yield data
        } catch {
          // 跳过格式异常的 SSE 行
        }
      }
    }
  }
}

// ============ 串讲 (Cross-Paper) API ============

export interface CrossPaperSessionMeta {
  id: string
  title: string
  paper_ids: string[]
  created_at: string
  updated_at: string
}

export interface CrossPaperSessionList {
  sessions: CrossPaperSessionMeta[]
  last_active_session_id: string | null
}

export interface CrossPaperChatHistory {
  session_id: string
  paper_ids: string[]
  messages: ChatMessage[]
  forks?: Record<string, ForkData>
  draft?: ChatDraft
}

export async function listCrossPaperSessions(): Promise<CrossPaperSessionList> {
  const response = await fetch(`${API_BASE}/chat/cross-paper/sessions`)
  if (!response.ok) {
    throw new Error('Failed to list cross-paper sessions')
  }
  return response.json()
}

export async function createCrossPaperSession(
  paperIds: string[],
  title?: string
): Promise<CrossPaperSessionMeta> {
  const response = await fetch(`${API_BASE}/chat/cross-paper/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ paper_ids: paperIds, title: title ?? null }),
  })
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || 'Failed to create cross-paper session')
  }
  return response.json()
}

export async function deleteCrossPaperSession(sessionId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/chat/cross-paper/sessions/${sessionId}`, {
    method: 'DELETE',
  })
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || 'Failed to delete cross-paper session')
  }
}

export async function addPapersToCrossPaperSession(
  sessionId: string,
  paperIds: string[]
): Promise<CrossPaperSessionMeta> {
  const response = await fetch(`${API_BASE}/chat/cross-paper/sessions/${sessionId}/papers`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ paper_ids: paperIds }),
  })
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || 'Failed to add papers to cross-paper session')
  }
  return response.json()
}

export async function getCrossPaperChatHistory(sessionId: string): Promise<CrossPaperChatHistory> {
  const response = await fetch(`${API_BASE}/chat/cross-paper/${sessionId}/history`)
  if (!response.ok) {
    throw new Error('Failed to get cross-paper chat history')
  }
  return response.json()
}

export async function updateCrossPaperChatHistory(
  sessionId: string,
  messages: ChatMessage[],
  forks?: Record<string, ForkData>
): Promise<void> {
  const response = await fetch(`${API_BASE}/chat/cross-paper/${sessionId}/history`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, forks }),
  })
  if (!response.ok) {
    throw new Error('Failed to update cross-paper chat history')
  }
}

export async function updateCrossPaperChatDraft(
  sessionId: string,
  draft: ChatDraft
): Promise<void> {
  const response = await fetch(`${API_BASE}/chat/cross-paper/${sessionId}/history/draft`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ draft }),
  })
  if (!response.ok) {
    throw new Error('Failed to update cross-paper chat draft')
  }
}

export async function clearCrossPaperChatHistory(sessionId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/chat/cross-paper/${sessionId}/history`, {
    method: 'DELETE',
  })
  if (!response.ok) {
    throw new Error('Failed to clear cross-paper chat history')
  }
}

export async function* sendCrossPaperMessage(
  sessionId: string,
  message: string,
  quotes?: QuoteInput[],
  signal?: AbortSignal
): AsyncGenerator<{ type: string; content?: string; full_response?: string; message?: string }> {
  const response = await fetch(`${API_BASE}/chat/cross-paper/${sessionId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message,
      quotes: quotes && quotes.length > 0 ? quotes : undefined,
    }),
    signal,
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || 'Failed to send cross-paper message')
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
        try {
          const data = JSON.parse(line.slice(6))
          yield data
        } catch {
          // skip malformed SSE lines
        }
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
  edits?: ProfileEdit[]
  validation?: { valid: boolean; issue: string }
}

export async function getProfile(): Promise<{ content: string }> {
  const response = await fetch(`${API_BASE}/profile/current`)
  if (!response.ok) {
    throw new Error('Failed to get profile')
  }
  return response.json()
}

export async function getChangelog(): Promise<{ content: string }> {
  const response = await fetch(`${API_BASE}/profile/changelog`)
  if (!response.ok) {
    throw new Error('Failed to get changelog')
  }
  return response.json()
}

export async function* sendEvolutionMessage(
  message: string,
  evolutionMessages: { role: string; content: string }[],
  paperId?: string,
  crossPaperSessionId?: string,
  signal?: AbortSignal,
): AsyncGenerator<{
  type: string
  content?: string
  full_response?: string
  message?: string
  edit_plan?: { edits: ProfileEdit[]; changelog_summary: string }
}> {
  const response = await fetch(`${API_BASE}/profile/evolution-chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message,
      paper_id: paperId ?? null,
      cross_paper_session_id: crossPaperSessionId ?? null,
      evolution_messages: evolutionMessages,
    }),
    signal,
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || 'Failed to send evolution message')
  }

  const reader = response.body?.getReader()
  if (!reader) throw new Error('No response body')

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
        try {
          yield JSON.parse(line.slice(6))
        } catch {
          // skip malformed SSE
        }
      }
    }
  }
}

export async function saveEditPlan(
  editPlan: { edits: ProfileEdit[]; changelog_summary: string },
  paperTitle: string,
): Promise<{ validation: { valid: boolean; issue: string } }> {
  const response = await fetch(`${API_BASE}/profile/save-edit-plan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ edit_plan: editPlan, paper_title: paperTitle }),
  })
  if (!response.ok) throw new Error('Failed to save edit plan')
  return response.json()
}

export async function applyProfileUpdates(): Promise<void> {
  const response = await fetch(`${API_BASE}/profile/apply-updates`, {
    method: 'POST',
  })
  if (!response.ok) throw new Error('Failed to apply profile updates')
}

export async function rejectProfileUpdates(): Promise<void> {
  const response = await fetch(`${API_BASE}/profile/reject-updates`, {
    method: 'POST',
  })
  if (!response.ok) throw new Error('Failed to reject profile updates')
}

