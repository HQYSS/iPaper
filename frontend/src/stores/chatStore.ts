import { create } from 'zustand'
import * as api from '../services/api'

export type QuoteSource = 'pdf' | 'chat'

export interface QuoteItem {
  text: string
  source: QuoteSource
}

interface ChatStore {
  messages: api.ChatMessage[]
  isLoading: boolean
  isStreaming: boolean
  error: string | null
  currentPaperId: string | null
  quotes: QuoteItem[]

  sessions: api.SessionMeta[]
  currentSessionId: string | null

  abortController: AbortController | null
  forks: Record<string, api.ForkData>

  pendingProfileUpdate: api.PendingProfileUpdate | null

  loadSessions: (paperId: string) => Promise<void>
  createSession: (paperId: string) => Promise<void>
  deleteSession: (paperId: string, sessionId: string) => Promise<void>
  switchSession: (paperId: string, sessionId: string) => Promise<void>

  loadHistory: (paperId: string, sessionId: string) => Promise<void>
  sendMessage: (paperId: string, sessionId: string, message: string, quotes?: QuoteItem[]) => Promise<void>
  stopStreaming: () => void
  clearHistory: (paperId: string, sessionId: string) => Promise<void>
  clearError: () => void
  addQuote: (text: string, source: QuoteSource) => void
  removeQuote: (index: number) => void
  clearQuotes: () => void

  editMessage: (paperId: string, sessionId: string, messageIndex: number, newContent: string) => Promise<void>
  switchFork: (paperId: string, sessionId: string, messageIndex: number, forkIndex: number) => Promise<void>

  triggerProfileAnalysis: (paperId: string) => Promise<void>
  isAnalyzingProfile: boolean
  checkPendingProfileUpdates: () => Promise<void>
  applyProfileUpdate: () => Promise<void>
  rejectProfileUpdate: () => Promise<void>
}

const AUTO_EXPLAIN_MESSAGE = '请为我详细讲解这篇论文。'

export const useChatStore = create<ChatStore>((set, get) => ({
  messages: [],
  isLoading: false,
  isStreaming: false,
  error: null,
  currentPaperId: null,
  quotes: [],
  sessions: [],
  currentSessionId: null,
  abortController: null,
  forks: {},
  pendingProfileUpdate: null,
  isAnalyzingProfile: false,

  loadSessions: async (paperId: string) => {
    if (get().currentPaperId !== paperId) {
      set({ messages: [], currentPaperId: paperId, currentSessionId: null, sessions: [], forks: {} })
    }

    try {
      const sessionList = await api.listSessions(paperId)
      const sessions = sessionList.sessions

      if (sessions.length === 0) {
        const newSession = await api.createSession(paperId, '自动讲解')
        set({ sessions: [newSession], currentSessionId: newSession.id })
        setTimeout(() => {
          const store = get()
          if (store.currentPaperId === paperId && store.currentSessionId === newSession.id && store.messages.length === 0 && !store.isStreaming) {
            store.sendMessage(paperId, newSession.id, AUTO_EXPLAIN_MESSAGE)
          }
        }, 300)
        return
      }

      const activeId = sessionList.last_active_session_id || sessions[0].id
      set({ sessions, currentSessionId: activeId })

      const store = get()
      store.loadHistory(paperId, activeId)
    } catch (error) {
      set({ error: (error as Error).message })
    }
  },

  createSession: async (paperId: string) => {
    try {
      const newSession = await api.createSession(paperId)
      set((state) => ({
        sessions: [...state.sessions, newSession],
        currentSessionId: newSession.id,
        messages: [],
        forks: {},
      }))
    } catch (error) {
      set({ error: (error as Error).message })
    }
  },

  deleteSession: async (paperId: string, sessionId: string) => {
    try {
      await api.deleteSession(paperId, sessionId)
      const { currentSessionId } = get()
      set((state) => {
        const remaining = state.sessions.filter((s) => s.id !== sessionId)
        const needSwitch = currentSessionId === sessionId
        return {
          sessions: remaining,
          currentSessionId: needSwitch ? (remaining[0]?.id ?? null) : currentSessionId,
          messages: needSwitch ? [] : state.messages,
          forks: needSwitch ? {} : state.forks,
        }
      })
      const store = get()
      if (store.currentSessionId && currentSessionId === sessionId) {
        store.loadHistory(paperId, store.currentSessionId)
      }
    } catch (error) {
      set({ error: (error as Error).message })
    }
  },

  switchSession: async (paperId: string, sessionId: string) => {
    const { currentSessionId } = get()
    if (currentSessionId === sessionId) return
    set({ currentSessionId: sessionId, messages: [], forks: {} })
    get().loadHistory(paperId, sessionId)
  },

  loadHistory: async (paperId: string, sessionId: string) => {
    set({ isLoading: true, error: null })
    try {
      const history = await api.getChatHistory(paperId, sessionId)
      set({ messages: history.messages, forks: history.forks || {}, isLoading: false })
    } catch (error) {
      set({ error: (error as Error).message, isLoading: false })
    }
  },

  sendMessage: async (paperId: string, sessionId: string, message: string, quotes?: QuoteItem[]) => {
    const { messages } = get()
    const controller = new AbortController()

    const userMessage: api.ChatMessage = { role: 'user', content: message }
    set({ messages: [...messages, userMessage], isStreaming: true, error: null, abortController: controller })

    const assistantMessage: api.ChatMessage = { role: 'assistant', content: '' }
    set({ messages: [...messages, userMessage, assistantMessage] })

    const isStillActive = () =>
      get().currentPaperId === paperId && get().currentSessionId === sessionId

    try {
      for await (const data of api.sendMessage(paperId, sessionId, message, quotes, controller.signal)) {
        if (!isStillActive()) continue

        if (data.type === 'chunk' && data.content) {
          set((state) => {
            const newMessages = [...state.messages]
            const lastMessage = newMessages[newMessages.length - 1]
            if (lastMessage.role === 'assistant') {
              lastMessage.content += data.content
            }
            return { messages: newMessages }
          })
        } else if (data.type === 'done') {
          set({ isStreaming: false, abortController: null })
        } else if (data.type === 'error') {
          set((state) => ({
            error: data.message || 'Unknown error',
            isStreaming: false,
            abortController: null,
            messages: state.messages.filter((_, i) => i !== state.messages.length - 1),
          }))
        }
      }
    } catch (error) {
      if ((error as Error).name === 'AbortError') {
        // Stopped by user — keep partial content if any, remove empty assistant message
        set((state) => {
          const msgs = [...state.messages]
          const last = msgs[msgs.length - 1]
          if (last?.role === 'assistant' && !last.content) {
            msgs.pop()
          }
          return { messages: msgs, isStreaming: false, abortController: null }
        })
        return
      }
      if (!isStillActive()) return
      set({ error: (error as Error).message, isStreaming: false, abortController: null })
      set((state) => ({
        messages: state.messages.filter((_, i) => i !== state.messages.length - 1),
      }))
    }
  },

  stopStreaming: () => {
    const { abortController } = get()
    if (abortController) {
      abortController.abort()
    }
  },

  clearHistory: async (paperId: string, sessionId: string) => {
    set({ isLoading: true, error: null })
    try {
      await api.clearChatHistory(paperId, sessionId)
      set({ messages: [], forks: {}, isLoading: false })
    } catch (error) {
      set({ error: (error as Error).message, isLoading: false })
    }
  },

  clearError: () => {
    set({ error: null })
  },

  addQuote: (text: string, source: QuoteSource) => {
    set((state) => ({ quotes: [...state.quotes, { text, source }] }))
  },

  removeQuote: (index: number) => {
    set((state) => ({ quotes: state.quotes.filter((_, i) => i !== index) }))
  },

  clearQuotes: () => {
    set({ quotes: [] })
  },

  editMessage: async (paperId: string, sessionId: string, messageIndex: number, newContent: string) => {
    const { messages, forks } = get()
    const oldMessage = messages[messageIndex]
    if (!oldMessage || oldMessage.role !== 'user') return

    const tailFromIndex = messages.slice(messageIndex)
    const newForks = { ...forks }
    const key = String(messageIndex)

    if (newForks[key]) {
      // Already has forks at this index — save current tail as another alternative
      const currentActive = newForks[key].active
      newForks[key] = {
        alternatives: [...newForks[key].alternatives],
        active: currentActive,
      }
      // Update the currently active alternative with the latest tail
      newForks[key].alternatives[currentActive] = tailFromIndex
      // Add the new branch
      newForks[key].alternatives.push([{ role: 'user', content: newContent }])
      newForks[key].active = newForks[key].alternatives.length - 1
    } else {
      // First fork at this index
      newForks[key] = {
        alternatives: [
          tailFromIndex,
          [{ role: 'user', content: newContent }],
        ],
        active: 1,
      }
    }

    // Truncate messages at the fork point and set new user message
    const newMessages = [...messages.slice(0, messageIndex), { role: 'user' as const, content: newContent }]
    set({ messages: newMessages, forks: newForks })

    // Save truncated state, then send the edited message
    try {
      await api.updateChatHistory(paperId, sessionId, newMessages, newForks)
    } catch {
      // Best effort save
    }

    get().sendMessage(paperId, sessionId, newContent)
  },

  switchFork: async (paperId: string, sessionId: string, messageIndex: number, forkIndex: number) => {
    const { messages, forks } = get()
    const key = String(messageIndex)
    const fork = forks[key]
    if (!fork || forkIndex < 0 || forkIndex >= fork.alternatives.length) return

    // Save current tail into the currently active alternative
    const currentTail = messages.slice(messageIndex)
    const newForks = { ...forks }
    newForks[key] = {
      alternatives: [...fork.alternatives],
      active: forkIndex,
    }
    newForks[key].alternatives[fork.active] = currentTail

    // Replace messages: keep everything before the fork point, append the target branch
    const targetBranch = newForks[key].alternatives[forkIndex]
    const newMessages = [...messages.slice(0, messageIndex), ...targetBranch]
    set({ messages: newMessages, forks: newForks })

    try {
      await api.updateChatHistory(paperId, sessionId, newMessages, newForks)
    } catch {
      // Best effort save
    }
  },

  triggerProfileAnalysis: async (paperId: string) => {
    set({ isAnalyzingProfile: true })
    try {
      await api.triggerProfileAnalysis(paperId)
      await new Promise((r) => setTimeout(r, 3000))
      const pending = await api.getPendingProfileUpdates()
      set({
        pendingProfileUpdate: pending.has_updates ? pending : null,
        isAnalyzingProfile: false,
      })
    } catch {
      set({ isAnalyzingProfile: false })
    }
  },

  checkPendingProfileUpdates: async () => {
    try {
      const pending = await api.getPendingProfileUpdates()
      set({ pendingProfileUpdate: pending.has_updates ? pending : null })
    } catch {
      // 静默失败
    }
  },

  applyProfileUpdate: async () => {
    try {
      await api.applyProfileUpdates()
      set({ pendingProfileUpdate: null })
    } catch (error) {
      set({ error: (error as Error).message })
    }
  },

  rejectProfileUpdate: async () => {
    try {
      await api.rejectProfileUpdates()
      set({ pendingProfileUpdate: null })
    } catch (error) {
      set({ error: (error as Error).message })
    }
  },
}))
