const API_BASE = (import.meta.env.BASE_URL.replace(/\/$/, '')) + '/api'

const TOKEN_STORAGE_KEY = 'ipaper.auth.token'

export function getAuthToken(): string | null {
  return localStorage.getItem(TOKEN_STORAGE_KEY)
}

export function setAuthToken(token: string): void {
  localStorage.setItem(TOKEN_STORAGE_KEY, token)
}

export function clearAuthToken(): void {
  localStorage.removeItem(TOKEN_STORAGE_KEY)
}

export async function authFetch(url: string, options?: RequestInit): Promise<Response> {
  const token = getAuthToken()
  const headers = new Headers(options?.headers)
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  const response = await fetch(url, { ...options, headers })

  if (response.status === 401) {
    clearAuthToken()
    window.dispatchEvent(new CustomEvent('ipaper:auth-expired'))
  }

  return response
}

// ============ 认证 API ============

export interface AuthUser {
  id: string
  username: string
  is_admin?: boolean
}

export interface SyncDevice {
  device_id: string
  device_name: string
  created_at: string
  last_used_at?: string | null
  revoked_at?: string | null
}

export interface SyncDeviceTokenResponse extends SyncDevice {
  token: string
}

export interface AuthResponse {
  access_token: string
  token_type: string
  user: AuthUser
}

export async function loginApi(username: string, password: string): Promise<AuthResponse> {
  const response = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    throw new Error(error.detail || '登录失败')
  }
  return response.json()
}

export async function registerApi(username: string, password: string, inviteCode: string): Promise<AuthResponse> {
  const response = await fetch(`${API_BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password, invite_code: inviteCode }),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    throw new Error(error.detail || '注册失败')
  }
  return response.json()
}

export async function getMe(): Promise<AuthUser> {
  const response = await authFetch(`${API_BASE}/auth/me`)
  if (!response.ok) {
    throw new Error('Not authenticated')
  }
  return response.json()
}

// ============ 偏好设置 API ============

export async function getPreferences(): Promise<Record<string, unknown>> {
  const response = await authFetch(`${API_BASE}/preferences`)
  if (!response.ok) {
    throw new Error('Failed to get preferences')
  }
  return response.json()
}

export async function updatePreferencesApi(partial: Record<string, unknown>): Promise<void> {
  const response = await authFetch(`${API_BASE}/preferences`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(partial),
  })
  if (!response.ok) {
    throw new Error('Failed to update preferences')
  }
}

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
  const response = await authFetch(`${API_BASE}/papers`)
  if (!response.ok) {
    throw new Error('Failed to fetch papers')
  }
  return response.json()
}

export async function addPaper(arxivInput: string): Promise<Paper> {
  const response = await authFetch(`${API_BASE}/papers`, {
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
  const response = await authFetch(`${API_BASE}/papers/${paperId}`)
  if (!response.ok) {
    throw new Error('Failed to get paper')
  }
  return response.json()
}

export async function deletePaper(paperId: string): Promise<void> {
  const response = await authFetch(`${API_BASE}/papers/${paperId}`, {
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
  const response = await authFetch(`${API_BASE}/papers/${paperId}/translations`)
  if (!response.ok) return { zh: false, bilingual: false }
  return response.json()
}

// ============ 翻译 API ============

export interface TranslateStatus {
  status: 'none' | 'pending' | 'polling' | 'finished' | 'failed' | 'error' | 'needs_login'
  info: string
  error: string
}

export async function triggerTranslation(paperId: string): Promise<TranslateStatus> {
  const response = await authFetch(`${API_BASE}/papers/${paperId}/translate`, {
    method: 'POST',
  })
  if (!response.ok) {
    throw new Error('Failed to trigger translation')
  }
  return response.json()
}

export async function getTranslateStatus(paperId: string): Promise<TranslateStatus> {
  const response = await authFetch(`${API_BASE}/papers/${paperId}/translate/status`)
  if (!response.ok) {
    throw new Error('Failed to get translation status')
  }
  return response.json()
}

export async function updateHjfyCookie(cookie: string): Promise<void> {
  const response = await authFetch(`${API_BASE}/config/hjfy`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ cookie }),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    throw new Error(error.detail || 'Failed to update hjfy cookie')
  }
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
  const response = await authFetch(`${API_BASE}/chat/${paperId}/sessions`)
  if (!response.ok) {
    throw new Error('Failed to list sessions')
  }
  return response.json()
}

export async function createSession(paperId: string, title?: string): Promise<SessionMeta> {
  const response = await authFetch(`${API_BASE}/chat/${paperId}/sessions`, {
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
  const response = await authFetch(`${API_BASE}/chat/${paperId}/sessions/${sessionId}`, {
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
  page_selections?: PaperPageSelectionInput[]
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
  const response = await authFetch(`${API_BASE}/chat/${paperId}/${sessionId}/history`)
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
  const response = await authFetch(`${API_BASE}/chat/${paperId}/${sessionId}/history`, {
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
  const response = await authFetch(`${API_BASE}/chat/${paperId}/${sessionId}/history/draft`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ draft }),
  })
  if (!response.ok) {
    throw new Error('Failed to update chat draft')
  }
}

export async function clearChatHistory(paperId: string, sessionId: string): Promise<void> {
  const response = await authFetch(`${API_BASE}/chat/${paperId}/${sessionId}/history`, {
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

export interface PageRangeInput {
  start: number
  end: number
}

export interface PaperPageSelectionInput {
  paper_id: string
  ranges: PageRangeInput[]
}

export interface PageSelectionRequirement {
  paper_id: string
  title: string
  total_pages: number
  selected_ranges?: PageRangeInput[]
}

export class PageSelectionRequiredError extends Error {
  requirements: PageSelectionRequirement[]

  constructor(message: string, requirements: PageSelectionRequirement[]) {
    super(message)
    this.name = 'PageSelectionRequiredError'
    this.requirements = requirements
  }
}

export async function* sendMessage(
  paperId: string,
  sessionId: string,
  message: string,
  quotes?: QuoteInput[],
  pageSelections?: PaperPageSelectionInput[],
  signal?: AbortSignal
): AsyncGenerator<{ type: string; content?: string; full_response?: string; message?: string }> {
  const response = await authFetch(`${API_BASE}/chat/${paperId}/${sessionId}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      message,
      quotes: quotes && quotes.length > 0 ? quotes : undefined,
      page_selections: pageSelections && pageSelections.length > 0 ? pageSelections : undefined,
    }),
    signal,
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    if (response.status === 409 && error?.detail?.code === 'page_selection_required') {
      throw new PageSelectionRequiredError(
        error.detail.message || '需要选择保留页码',
        error.detail.requirements || []
      )
    }
    throw new Error(error.detail || 'Failed to send message')
  }

  const reader = response.body?.getReader()
  if (!reader) {
    throw new Error('No response body')
  }

  yield { type: 'open' }

  const decoder = new TextDecoder()
  let buffer = ''
  const flushBuffer = function* (rawBuffer: string) {
    for (const rawLine of rawBuffer.split('\n')) {
      const line = rawLine.trim()
      if (!line.startsWith('data: ')) continue
      try {
        yield JSON.parse(line.slice(6))
      } catch {
        // 跳过格式异常的 SSE 行
      }
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''

    for (const data of flushBuffer(lines.join('\n'))) {
      yield data
    }
  }

  buffer += decoder.decode()
  for (const data of flushBuffer(buffer)) {
    yield data
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
  const response = await authFetch(`${API_BASE}/chat/cross-paper/sessions`)
  if (!response.ok) {
    throw new Error('Failed to list cross-paper sessions')
  }
  return response.json()
}

export async function createCrossPaperSession(
  paperIds: string[],
  title?: string
): Promise<CrossPaperSessionMeta> {
  const response = await authFetch(`${API_BASE}/chat/cross-paper/sessions`, {
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
  const response = await authFetch(`${API_BASE}/chat/cross-paper/sessions/${sessionId}`, {
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
  const response = await authFetch(`${API_BASE}/chat/cross-paper/sessions/${sessionId}/papers`, {
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
  const response = await authFetch(`${API_BASE}/chat/cross-paper/${sessionId}/history`)
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
  const response = await authFetch(`${API_BASE}/chat/cross-paper/${sessionId}/history`, {
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
  const response = await authFetch(`${API_BASE}/chat/cross-paper/${sessionId}/history/draft`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ draft }),
  })
  if (!response.ok) {
    throw new Error('Failed to update cross-paper chat draft')
  }
}

export async function clearCrossPaperChatHistory(sessionId: string): Promise<void> {
  const response = await authFetch(`${API_BASE}/chat/cross-paper/${sessionId}/history`, {
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
  pageSelections?: PaperPageSelectionInput[],
  signal?: AbortSignal
): AsyncGenerator<{ type: string; content?: string; full_response?: string; message?: string }> {
  const response = await authFetch(`${API_BASE}/chat/cross-paper/${sessionId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message,
      quotes: quotes && quotes.length > 0 ? quotes : undefined,
      page_selections: pageSelections && pageSelections.length > 0 ? pageSelections : undefined,
    }),
    signal,
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    if (response.status === 409 && error?.detail?.code === 'page_selection_required') {
      throw new PageSelectionRequiredError(
        error.detail.message || '需要选择保留页码',
        error.detail.requirements || []
      )
    }
    throw new Error(error.detail || 'Failed to send cross-paper message')
  }

  const reader = response.body?.getReader()
  if (!reader) {
    throw new Error('No response body')
  }

  yield { type: 'open' }

  const decoder = new TextDecoder()
  let buffer = ''
  const flushBuffer = function* (rawBuffer: string) {
    for (const rawLine of rawBuffer.split('\n')) {
      const line = rawLine.trim()
      if (!line.startsWith('data: ')) continue
      try {
        yield JSON.parse(line.slice(6))
      } catch {
        // skip malformed SSE lines
      }
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''

    for (const data of flushBuffer(lines.join('\n'))) {
      yield data
    }
  }

  buffer += decoder.decode()
  for (const data of flushBuffer(buffer)) {
    yield data
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
  hjfy_cookie_configured: boolean
  sync: {
    role: 'server' | 'client' | 'off'
    url: string
    token_configured: boolean
  }
}

export async function getConfig(): Promise<Config> {
  const response = await authFetch(`${API_BASE}/config`)
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
  const response = await authFetch(`${API_BASE}/config/llm`, {
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

export async function updateSyncConfig(config: {
  sync_url?: string
  sync_token?: string
  clear_sync_token?: boolean
}): Promise<void> {
  const response = await authFetch(`${API_BASE}/config/sync`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(config),
  })
  if (!response.ok) {
    throw new Error('Failed to update sync config')
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
  const response = await authFetch(`${API_BASE}/profile/current`)
  if (!response.ok) {
    throw new Error('Failed to get profile')
  }
  return response.json()
}

export async function getChangelog(): Promise<{ content: string }> {
  const response = await authFetch(`${API_BASE}/profile/changelog`)
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
  const response = await authFetch(`${API_BASE}/profile/evolution-chat`, {
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
  const response = await authFetch(`${API_BASE}/profile/save-edit-plan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ edit_plan: editPlan, paper_title: paperTitle }),
  })
  if (!response.ok) throw new Error('Failed to save edit plan')
  return response.json()
}

export async function applyProfileUpdates(): Promise<void> {
  const response = await authFetch(`${API_BASE}/profile/apply-updates`, {
    method: 'POST',
  })
  if (!response.ok) throw new Error('Failed to apply profile updates')
}

export async function rejectProfileUpdates(): Promise<void> {
  const response = await authFetch(`${API_BASE}/profile/reject-updates`, {
    method: 'POST',
  })
  if (!response.ok) throw new Error('Failed to reject profile updates')
}

// ============ 管理员 API ============

export async function listUsers(): Promise<AuthUser[]> {
  const response = await authFetch(`${API_BASE}/auth/admin/users`)
  if (!response.ok) throw new Error('Failed to list users')
  return response.json()
}

export async function deleteUser(userId: string): Promise<void> {
  const response = await authFetch(`${API_BASE}/auth/admin/users/${userId}`, { method: 'DELETE' })
  if (!response.ok) {
    const err = await response.json().catch(() => ({}))
    throw new Error(err.detail || 'Failed to delete user')
  }
}

export async function getInviteCode(): Promise<string> {
  const response = await authFetch(`${API_BASE}/auth/admin/invite-code`)
  if (!response.ok) throw new Error('Failed to get invite code')
  const data = await response.json()
  return data.invite_code
}

export async function updateInviteCode(code: string): Promise<void> {
  const response = await authFetch(`${API_BASE}/auth/admin/invite-code`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ invite_code: code }),
  })
  if (!response.ok) throw new Error('Failed to update invite code')
}

export async function listSyncDevices(): Promise<SyncDevice[]> {
  const response = await authFetch(`${API_BASE}/auth/admin/sync-devices`)
  if (!response.ok) throw new Error('Failed to list sync devices')
  return response.json()
}

export async function createSyncDevice(deviceName: string): Promise<SyncDeviceTokenResponse> {
  const response = await authFetch(`${API_BASE}/auth/admin/sync-devices`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ device_name: deviceName }),
  })
  if (!response.ok) {
    throw new Error('Failed to create sync device')
  }
  return response.json()
}

export async function revokeSyncDevice(deviceId: string): Promise<void> {
  const response = await authFetch(`${API_BASE}/auth/admin/sync-devices/${deviceId}`, {
    method: 'DELETE',
  })
  if (!response.ok) {
    throw new Error('Failed to revoke sync device')
  }
}

export async function changePassword(newPassword: string): Promise<void> {
  const response = await authFetch(`${API_BASE}/auth/change-password`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ new_password: newPassword }),
  })
  if (!response.ok) throw new Error('Failed to change password')
}

// ============ 离线代理 re-exports ============
// 消费侧可直接 import { fetchPapersOffline } from './api' 使用离线增强版
export {
  fetchPapersOffline,
  fetchPdfBlobOffline,
  getChatHistoryOffline,
  getCrossPaperChatHistoryOffline,
  listSessionsOffline,
  listCrossPaperSessionsOffline,
  getPreferencesOffline,
  updatePreferencesOffline,
  updateChatHistoryOffline,
  updateCrossPaperChatHistoryOffline,
  replayPendingOps,
  setupOfflineListeners,
  isOnline,
} from './offlineApi'

