import { create } from 'zustand'
import * as api from '../services/api'
import {
  listSessionsOffline,
  getChatHistoryOffline,
  getCrossPaperChatHistoryOffline,
  listCrossPaperSessionsOffline,
  updateChatHistoryOffline,
  updateCrossPaperChatHistoryOffline,
} from '../services/offlineApi'

export type QuoteSource = 'pdf' | 'chat'

export interface QuoteItem {
  text: string
  source: QuoteSource
}

export interface PendingPageSelectionRequest {
  mode: 'single' | 'cross'
  sessionId: string
  paperId?: string
  message: string
  quotes?: QuoteItem[]
  requirements: api.PageSelectionRequirement[]
  errorMessage: string
}

interface ChatStore {
  messages: api.ChatMessage[]
  isLoading: boolean
  isStreaming: boolean
  error: string | null
  currentPaperId: string | null
  draftInput: string
  quotes: QuoteItem[]
  focusInputNonce: number
  pendingPageSelection: PendingPageSelectionRequest | null
  pageSelectionsByConversation: Record<string, api.PaperPageSelectionInput[]>

  sessions: api.SessionMeta[]
  currentSessionId: string | null

  abortController: AbortController | null
  forks: Record<string, api.ForkData>

  // 串讲模式标记
  isCrossPaperMode: boolean
  crossPaperIds: string[]

  loadSessions: (paperId: string) => Promise<void>
  createSession: (paperId: string) => Promise<void>
  deleteSession: (paperId: string, sessionId: string) => Promise<void>
  switchSession: (paperId: string, sessionId: string) => Promise<void>

  loadHistory: (paperId: string, sessionId: string) => Promise<void>
  sendMessage: (
    paperId: string,
    sessionId: string,
    message: string,
    quotes?: QuoteItem[],
    pageSelections?: api.PaperPageSelectionInput[]
  ) => Promise<void>
  stopStreaming: () => void
  clearHistory: (paperId: string, sessionId: string) => Promise<void>
  clearError: () => void
  setDraftInput: (input: string) => void
  addQuote: (text: string, source: QuoteSource) => void
  removeQuote: (index: number) => void
  clearQuotes: () => void
  saveDraft: (paperId: string, sessionId: string, input: string, quotes: QuoteItem[]) => Promise<void>

  editMessage: (paperId: string, sessionId: string, messageIndex: number, newContent: string) => Promise<void>
  switchFork: (paperId: string, sessionId: string, messageIndex: number, forkIndex: number) => Promise<void>

  // 串讲
  initCrossPaperSession: (session: api.CrossPaperSessionMeta) => Promise<void>
  loadCrossPaperSessions: () => Promise<void>
  loadCrossPaperSession: (sessionId: string) => Promise<void>
  deleteCrossPaperSession: (sessionId: string) => Promise<void>
  switchCrossPaperSession: (sessionId: string) => Promise<void>
  sendCrossPaperMessage: (
    sessionId: string,
    message: string,
    quotes?: QuoteItem[],
    pageSelections?: api.PaperPageSelectionInput[]
  ) => Promise<void>
  clearCrossPaperHistory: (sessionId: string) => Promise<void>
  editCrossPaperMessage: (sessionId: string, messageIndex: number, newContent: string) => Promise<void>
  switchCrossPaperFork: (sessionId: string, messageIndex: number, forkIndex: number) => Promise<void>
  saveCrossPaperDraft: (sessionId: string, input: string, quotes: QuoteItem[]) => Promise<void>
  addPaperToCrossChat: (sessionId: string, paperIds: string[], userMessage: string) => Promise<void>
  submitPageSelections: (pageSelections: api.PaperPageSelectionInput[]) => Promise<void>
  dismissPageSelection: () => void
  exitCrossPaperChat: () => void
}

const AUTO_EXPLAIN_MESSAGE = '请为我详细讲解这篇论文。'
const STREAM_HISTORY_PERSIST_DELAY_MS = 300
const buildDraft = (
  input: string,
  quotes: QuoteItem[],
  pageSelections?: api.PaperPageSelectionInput[]
): api.ChatDraft => ({
  input,
  quotes: quotes.length > 0 ? [...quotes] : undefined,
  page_selections: pageSelections && pageSelections.length > 0 ? pageSelections : undefined,
})
const getConversationSelectionKey = (
  paperId: string | undefined,
  sessionId: string,
  isCrossMode: boolean
) => (isCrossMode ? `cross:${sessionId}` : `paper:${paperId}:${sessionId}`)

function cloneChatMessage(message: api.ChatMessage): api.ChatMessage {
  return {
    ...message,
    quotes: message.quotes ? message.quotes.map((quote) => ({ ...quote })) : undefined,
  }
}

function cloneChatMessages(messages: api.ChatMessage[]): api.ChatMessage[] {
  return messages.map(cloneChatMessage)
}

function cloneForkData(forks: Record<string, api.ForkData>): Record<string, api.ForkData> | undefined {
  const entries = Object.entries(forks)
  if (entries.length === 0) return undefined
  return Object.fromEntries(
    entries.map(([key, fork]) => [
      key,
      {
        active: fork.active,
        alternatives: fork.alternatives.map((branch) => cloneChatMessages(branch)),
      },
    ])
  )
}

function removeTrailingEmptyAssistant(messages: api.ChatMessage[]): api.ChatMessage[] {
  const nextMessages = cloneChatMessages(messages)
  const lastMessage = nextMessages[nextMessages.length - 1]
  if (lastMessage?.role === 'assistant' && !lastMessage.content) {
    nextMessages.pop()
  }
  return nextMessages
}

function createHistoryPersistController(persist: () => Promise<void>) {
  let timer: number | null = null

  const runPersist = async () => {
    try {
      await persist()
    } catch {
      // 历史快照同步失败不打断当前流式会话
    }
  }

  return {
    schedule() {
      if (timer !== null) {
        window.clearTimeout(timer)
      }
      timer = window.setTimeout(() => {
        timer = null
        void runPersist()
      }, STREAM_HISTORY_PERSIST_DELAY_MS)
    },
    async flush() {
      if (timer !== null) {
        window.clearTimeout(timer)
        timer = null
      }
      await runPersist()
    },
    cancel() {
      if (timer !== null) {
        window.clearTimeout(timer)
        timer = null
      }
    },
  }
}

export const useChatStore = create<ChatStore>((set, get) => ({
  messages: [],
  isLoading: false,
  isStreaming: false,
  error: null,
  currentPaperId: null,
  draftInput: '',
  quotes: [],
  focusInputNonce: 0,
  pendingPageSelection: null,
  pageSelectionsByConversation: {},
  sessions: [],
  currentSessionId: null,
  abortController: null,
  forks: {},
  isCrossPaperMode: false,
  crossPaperIds: [],

  loadSessions: async (paperId: string) => {
    const store = get()
    if (
      !store.isCrossPaperMode &&
      store.currentPaperId &&
      store.currentSessionId &&
      store.currentPaperId !== paperId
    ) {
      await store.saveDraft(store.currentPaperId, store.currentSessionId, store.draftInput, store.quotes)
    }

    if (store.currentPaperId !== paperId) {
      set({
        messages: [],
        currentPaperId: paperId,
        currentSessionId: null,
        sessions: [],
        forks: {},
        draftInput: '',
        quotes: [],
      })
    }

    try {
      const sessionList = await listSessionsOffline(paperId)
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
      set({ sessions, currentSessionId: activeId, isLoading: true })

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
        draftInput: '',
        quotes: [],
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
          draftInput: needSwitch ? '' : state.draftInput,
          quotes: needSwitch ? [] : state.quotes,
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
    const { currentSessionId, currentPaperId, draftInput, quotes } = get()
    if (currentSessionId === sessionId) return
    if (currentPaperId === paperId && currentSessionId) {
      await get().saveDraft(paperId, currentSessionId, draftInput, quotes)
    }
    set({ currentSessionId: sessionId, messages: [], forks: {}, draftInput: '', quotes: [], isLoading: true })
    await get().loadHistory(paperId, sessionId)
  },

  loadHistory: async (paperId: string, sessionId: string) => {
    set({ isLoading: true, error: null })
    try {
      const history = await getChatHistoryOffline(paperId, sessionId)
      const selectionKey = getConversationSelectionKey(paperId, sessionId, false)
      set((state) => {
        const nextSelections = { ...state.pageSelectionsByConversation }
        if (history.draft?.page_selections) {
          nextSelections[selectionKey] = history.draft.page_selections
        } else {
          delete nextSelections[selectionKey]
        }
        return {
          messages: history.messages,
          forks: history.forks || {},
          draftInput: history.draft?.input || '',
          quotes: history.draft?.quotes || [],
          isLoading: false,
          pageSelectionsByConversation: nextSelections,
        }
      })
    } catch (error) {
      set({ error: (error as Error).message, isLoading: false })
    }
  },

  sendMessage: async (
    paperId: string,
    sessionId: string,
    message: string,
    quotes?: QuoteItem[],
    pageSelections?: api.PaperPageSelectionInput[]
  ) => {
    const controller = new AbortController()
    const selectionKey = getConversationSelectionKey(paperId, sessionId, false)
    const effectivePageSelections = pageSelections || get().pageSelectionsByConversation[selectionKey]
    const persistedForks = cloneForkData(get().forks)

    const userMessage: api.ChatMessage = {
      role: 'user',
      content: message,
      quotes: quotes && quotes.length > 0 ? [...quotes] : undefined,
    }
    const assistantMessage: api.ChatMessage = { role: 'assistant', content: '' }
    let persistedMessages = [
      ...cloneChatMessages(get().messages),
      cloneChatMessage(userMessage),
      cloneChatMessage(assistantMessage),
    ]
    const historyPersister = createHistoryPersistController(() =>
      updateChatHistoryOffline(paperId, sessionId, persistedMessages, persistedForks)
    )
    set((state) => ({
      messages: [...state.messages, userMessage],
      isStreaming: true,
      error: null,
      abortController: controller,
      draftInput: '',
      quotes: [],
      pendingPageSelection: null,
      pageSelectionsByConversation: effectivePageSelections
        ? { ...state.pageSelectionsByConversation, [selectionKey]: effectivePageSelections }
        : state.pageSelectionsByConversation,
    }))
    set((state) => ({ messages: [...state.messages, assistantMessage] }))

    const isStillActive = () =>
      get().currentPaperId === paperId && get().currentSessionId === sessionId

    const clearStreamingState = () => {
      set((state) => (
        state.abortController === controller
          ? { isStreaming: false, abortController: null }
          : {}
      ))
    }

    try {
      for await (const data of api.sendMessage(paperId, sessionId, message, quotes, effectivePageSelections, controller.signal)) {
        if (data.type === 'open') {
          await historyPersister.flush()
          continue
        }

        if (data.type === 'done') {
          clearStreamingState()
          continue
        }

        if (data.type === 'error') {
          clearStreamingState()
          persistedMessages = removeTrailingEmptyAssistant(persistedMessages)
          await historyPersister.flush()
          if (!isStillActive()) continue
          set((state) => ({
            error: data.message || 'Unknown error',
            messages: state.messages.filter((_, i) => i !== state.messages.length - 1),
          }))
          continue
        }

        if (data.type === 'chunk' && data.content) {
          const lastPersistedMessage = persistedMessages[persistedMessages.length - 1]
          if (lastPersistedMessage?.role === 'assistant') {
            lastPersistedMessage.content += data.content
            historyPersister.schedule()
          }
        }

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
        }
      }
      await historyPersister.flush()
      clearStreamingState()
    } catch (error) {
      if ((error as Error).name === 'AbortError') {
        // Stopped by user — keep partial content if any, remove empty assistant message
        clearStreamingState()
        persistedMessages = removeTrailingEmptyAssistant(persistedMessages)
        await historyPersister.flush()
        if (!isStillActive()) return
        set((state) => {
          const msgs = [...state.messages]
          const last = msgs[msgs.length - 1]
          if (last?.role === 'assistant' && !last.content) {
            msgs.pop()
          }
          return { messages: msgs }
        })
        return
      }
      if (error instanceof api.PageSelectionRequiredError) {
        clearStreamingState()
        historyPersister.cancel()
        if (!isStillActive()) return
        set((state) => {
          const msgs = [...state.messages]
          const last = msgs[msgs.length - 1]
          if (last?.role === 'assistant' && !last.content) {
            msgs.pop()
          }
          const newLast = msgs[msgs.length - 1]
          if (newLast?.role === 'user' && newLast.content === message) {
            msgs.pop()
          }
          return {
            messages: msgs,
            draftInput: message,
            quotes: quotes ? [...quotes] : [],
            pendingPageSelection: {
              mode: 'single',
              sessionId,
              paperId,
              message,
              quotes: quotes ? [...quotes] : undefined,
              requirements: error.requirements,
              errorMessage: error.message,
            },
          }
        })
        return
      }
      clearStreamingState()
      persistedMessages = removeTrailingEmptyAssistant(persistedMessages)
      await historyPersister.flush()
      if (!isStillActive()) return
      set({ error: (error as Error).message })
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
      const selectionKey = getConversationSelectionKey(paperId, sessionId, false)
      set((state) => {
        const nextSelections = { ...state.pageSelectionsByConversation }
        delete nextSelections[selectionKey]
        return {
          messages: [],
          forks: {},
          draftInput: '',
          quotes: [],
          isLoading: false,
          pageSelectionsByConversation: nextSelections,
        }
      })
    } catch (error) {
      set({ error: (error as Error).message, isLoading: false })
    }
  },

  clearError: () => {
    set({ error: null })
  },

  setDraftInput: (input: string) => {
    set({ draftInput: input })
  },

  addQuote: (text: string, source: QuoteSource) => {
    set((state) => ({
      quotes: [...state.quotes, { text, source }],
      focusInputNonce: state.focusInputNonce + 1,
    }))
  },

  removeQuote: (index: number) => {
    set((state) => ({ quotes: state.quotes.filter((_, i) => i !== index) }))
  },

  clearQuotes: () => {
    set({ quotes: [] })
  },

  saveDraft: async (paperId: string, sessionId: string, input: string, quotes: QuoteItem[]) => {
    try {
      const selectionKey = getConversationSelectionKey(paperId, sessionId, false)
      await api.updateChatDraft(
        paperId,
        sessionId,
        buildDraft(input, quotes, get().pageSelectionsByConversation[selectionKey])
      )
    } catch {
      // 输入过程中的草稿保存失败不打断交互
    }
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

    // Truncate messages to before the fork point (sendMessage will add the user message)
    const newMessages = messages.slice(0, messageIndex)
    set({ messages: newMessages, forks: newForks })

    try {
      await updateChatHistoryOffline(paperId, sessionId, newMessages, newForks)
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

    const currentTail = messages.slice(messageIndex)
    const newForks = { ...forks }
    newForks[key] = {
      alternatives: [...fork.alternatives],
      active: forkIndex,
    }
    newForks[key].alternatives[fork.active] = currentTail

    const targetBranch = newForks[key].alternatives[forkIndex]
    const newMessages = [...messages.slice(0, messageIndex), ...targetBranch]
    set({ messages: newMessages, forks: newForks })

    try {
      await updateChatHistoryOffline(paperId, sessionId, newMessages, newForks)
    } catch {
      // Best effort save
    }
  },

  // ==================== Cross-Paper (串讲) ====================

  initCrossPaperSession: async (session: api.CrossPaperSessionMeta) => {
    const store = get()
    if (!store.isCrossPaperMode && store.currentPaperId && store.currentSessionId) {
      await store.saveDraft(store.currentPaperId, store.currentSessionId, store.draftInput, store.quotes)
    }

    set({
      isCrossPaperMode: true,
      crossPaperIds: session.paper_ids,
      currentPaperId: null,
      messages: [],
      sessions: [{ id: session.id, title: session.title, created_at: session.created_at, updated_at: session.updated_at }],
      currentSessionId: session.id,
      forks: {},
      draftInput: '',
      quotes: [],
    })
  },

  loadCrossPaperSessions: async () => {
    const store = get()
    if (!store.isCrossPaperMode && store.currentPaperId && store.currentSessionId) {
      await store.saveDraft(store.currentPaperId, store.currentSessionId, store.draftInput, store.quotes)
    }

    set({
      isCrossPaperMode: true,
      currentPaperId: null,
      messages: [],
      sessions: [],
      currentSessionId: null,
      forks: {},
      draftInput: '',
      quotes: [],
    })

    try {
      const sessionList = await listCrossPaperSessionsOffline()
      const sessions = sessionList.sessions.map((s) => ({
        id: s.id,
        title: s.title,
        created_at: s.created_at,
        updated_at: s.updated_at,
      }))

      if (sessions.length === 0) {
        set({ sessions, isCrossPaperMode: true })
        return
      }

      const activeId = sessionList.last_active_session_id || sessions[0].id
      set({ sessions, currentSessionId: activeId, isCrossPaperMode: true, isLoading: true })

      const activeSession = sessionList.sessions.find((s) => s.id === activeId)
      if (activeSession) {
        set({ crossPaperIds: activeSession.paper_ids })
      }

      get().loadCrossPaperSession(activeId)
    } catch (error) {
      set({ error: (error as Error).message })
    }
  },

  loadCrossPaperSession: async (sessionId: string) => {
    set({ isLoading: true, error: null })
    try {
      const history = await getCrossPaperChatHistoryOffline(sessionId)
      const selectionKey = getConversationSelectionKey(undefined, sessionId, true)
      set((state) => {
        const nextSelections = { ...state.pageSelectionsByConversation }
        if (history.draft?.page_selections) {
          nextSelections[selectionKey] = history.draft.page_selections
        } else {
          delete nextSelections[selectionKey]
        }
        return {
          messages: history.messages,
          forks: history.forks || {},
          draftInput: history.draft?.input || '',
          quotes: history.draft?.quotes || [],
          isLoading: false,
          crossPaperIds: history.paper_ids,
          currentSessionId: sessionId,
          pageSelectionsByConversation: nextSelections,
        }
      })
    } catch (error) {
      set({ error: (error as Error).message, isLoading: false })
    }
  },

  deleteCrossPaperSession: async (sessionId: string) => {
    try {
      await api.deleteCrossPaperSession(sessionId)
      const { currentSessionId } = get()
      set((state) => {
        const remaining = state.sessions.filter((s) => s.id !== sessionId)
        const needSwitch = currentSessionId === sessionId
        return {
          sessions: remaining,
          currentSessionId: needSwitch ? (remaining[0]?.id ?? null) : currentSessionId,
          messages: needSwitch ? [] : state.messages,
          forks: needSwitch ? {} : state.forks,
          draftInput: needSwitch ? '' : state.draftInput,
          quotes: needSwitch ? [] : state.quotes,
        }
      })
      const store = get()
      if (store.currentSessionId && currentSessionId === sessionId) {
        store.loadCrossPaperSession(store.currentSessionId)
      }
    } catch (error) {
      set({ error: (error as Error).message })
    }
  },

  switchCrossPaperSession: async (sessionId: string) => {
    const { currentSessionId, draftInput, quotes } = get()
    if (currentSessionId === sessionId) return
    if (currentSessionId) {
      await get().saveCrossPaperDraft(currentSessionId, draftInput, quotes)
    }
    set({ currentSessionId: sessionId, messages: [], forks: {}, draftInput: '', quotes: [], isLoading: true })
    await get().loadCrossPaperSession(sessionId)
  },

  sendCrossPaperMessage: async (
    sessionId: string,
    message: string,
    quotes?: QuoteItem[],
    pageSelections?: api.PaperPageSelectionInput[]
  ) => {
    const controller = new AbortController()
    const selectionKey = getConversationSelectionKey(undefined, sessionId, true)
    const effectivePageSelections = pageSelections || get().pageSelectionsByConversation[selectionKey]
    const persistedForks = cloneForkData(get().forks)

    const userMessage: api.ChatMessage = {
      role: 'user',
      content: message,
      quotes: quotes && quotes.length > 0 ? [...quotes] : undefined,
    }
    const assistantMessage: api.ChatMessage = { role: 'assistant', content: '' }
    let persistedMessages = [
      ...cloneChatMessages(get().messages),
      cloneChatMessage(userMessage),
      cloneChatMessage(assistantMessage),
    ]
    const historyPersister = createHistoryPersistController(() =>
      updateCrossPaperChatHistoryOffline(sessionId, persistedMessages, persistedForks)
    )
    set((state) => ({
      messages: [...state.messages, userMessage],
      isStreaming: true,
      error: null,
      abortController: controller,
      draftInput: '',
      quotes: [],
      pendingPageSelection: null,
      pageSelectionsByConversation: effectivePageSelections
        ? { ...state.pageSelectionsByConversation, [selectionKey]: effectivePageSelections }
        : state.pageSelectionsByConversation,
    }))
    set((state) => ({ messages: [...state.messages, assistantMessage] }))

    const isStillActive = () =>
      get().isCrossPaperMode && get().currentSessionId === sessionId

    const clearStreamingState = () => {
      set((state) => (
        state.abortController === controller
          ? { isStreaming: false, abortController: null }
          : {}
      ))
    }

    try {
      for await (const data of api.sendCrossPaperMessage(sessionId, message, quotes, effectivePageSelections, controller.signal)) {
        if (data.type === 'open') {
          await historyPersister.flush()
          continue
        }

        if (data.type === 'done') {
          clearStreamingState()
          continue
        }

        if (data.type === 'error') {
          clearStreamingState()
          persistedMessages = removeTrailingEmptyAssistant(persistedMessages)
          await historyPersister.flush()
          if (!isStillActive()) continue
          set((state) => ({
            error: data.message || 'Unknown error',
            messages: state.messages.filter((_, i) => i !== state.messages.length - 1),
          }))
          continue
        }

        if (data.type === 'chunk' && data.content) {
          const lastPersistedMessage = persistedMessages[persistedMessages.length - 1]
          if (lastPersistedMessage?.role === 'assistant') {
            lastPersistedMessage.content += data.content
            historyPersister.schedule()
          }
        }

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
        }
      }
      await historyPersister.flush()
      clearStreamingState()
    } catch (error) {
      if ((error as Error).name === 'AbortError') {
        clearStreamingState()
        persistedMessages = removeTrailingEmptyAssistant(persistedMessages)
        await historyPersister.flush()
        if (!isStillActive()) return
        set((state) => {
          const msgs = [...state.messages]
          const last = msgs[msgs.length - 1]
          if (last?.role === 'assistant' && !last.content) {
            msgs.pop()
          }
          return { messages: msgs }
        })
        return
      }
      if (error instanceof api.PageSelectionRequiredError) {
        clearStreamingState()
        historyPersister.cancel()
        if (!isStillActive()) return
        set((state) => {
          const msgs = [...state.messages]
          const last = msgs[msgs.length - 1]
          if (last?.role === 'assistant' && !last.content) {
            msgs.pop()
          }
          const newLast = msgs[msgs.length - 1]
          if (newLast?.role === 'user' && newLast.content === message) {
            msgs.pop()
          }
          return {
            messages: msgs,
            draftInput: message,
            quotes: quotes ? [...quotes] : [],
            pendingPageSelection: {
              mode: 'cross',
              sessionId,
              message,
              quotes: quotes ? [...quotes] : undefined,
              requirements: error.requirements,
              errorMessage: error.message,
            },
          }
        })
        return
      }
      clearStreamingState()
      persistedMessages = removeTrailingEmptyAssistant(persistedMessages)
      await historyPersister.flush()
      if (!isStillActive()) return
      set({ error: (error as Error).message })
      set((state) => ({
        messages: state.messages.filter((_, i) => i !== state.messages.length - 1),
      }))
    }
  },

  clearCrossPaperHistory: async (sessionId: string) => {
    set({ isLoading: true, error: null })
    try {
      await api.clearCrossPaperChatHistory(sessionId)
      const selectionKey = getConversationSelectionKey(undefined, sessionId, true)
      set((state) => {
        const nextSelections = { ...state.pageSelectionsByConversation }
        delete nextSelections[selectionKey]
        return {
          messages: [],
          forks: {},
          draftInput: '',
          quotes: [],
          isLoading: false,
          pageSelectionsByConversation: nextSelections,
        }
      })
    } catch (error) {
      set({ error: (error as Error).message, isLoading: false })
    }
  },

  editCrossPaperMessage: async (sessionId: string, messageIndex: number, newContent: string) => {
    const { messages, forks } = get()
    const oldMessage = messages[messageIndex]
    if (!oldMessage || oldMessage.role !== 'user') return

    const tailFromIndex = messages.slice(messageIndex)
    const newForks = { ...forks }
    const key = String(messageIndex)

    if (newForks[key]) {
      const currentActive = newForks[key].active
      newForks[key] = {
        alternatives: [...newForks[key].alternatives],
        active: currentActive,
      }
      newForks[key].alternatives[currentActive] = tailFromIndex
      newForks[key].alternatives.push([{ role: 'user', content: newContent }])
      newForks[key].active = newForks[key].alternatives.length - 1
    } else {
      newForks[key] = {
        alternatives: [
          tailFromIndex,
          [{ role: 'user', content: newContent }],
        ],
        active: 1,
      }
    }

    const newMessages = messages.slice(0, messageIndex)
    set({ messages: newMessages, forks: newForks })

    try {
      await updateCrossPaperChatHistoryOffline(sessionId, newMessages, newForks)
    } catch {
      // best effort
    }

    get().sendCrossPaperMessage(sessionId, newContent)
  },

  switchCrossPaperFork: async (sessionId: string, messageIndex: number, forkIndex: number) => {
    const { messages, forks } = get()
    const key = String(messageIndex)
    const fork = forks[key]
    if (!fork || forkIndex < 0 || forkIndex >= fork.alternatives.length) return

    const currentTail = messages.slice(messageIndex)
    const newForks = { ...forks }
    newForks[key] = {
      alternatives: [...fork.alternatives],
      active: forkIndex,
    }
    newForks[key].alternatives[fork.active] = currentTail

    const targetBranch = newForks[key].alternatives[forkIndex]
    const newMessages = [...messages.slice(0, messageIndex), ...targetBranch]
    set({ messages: newMessages, forks: newForks })

    try {
      await updateCrossPaperChatHistoryOffline(sessionId, newMessages, newForks)
    } catch {
      // best effort
    }
  },

  saveCrossPaperDraft: async (sessionId: string, input: string, quotes: QuoteItem[]) => {
    try {
      const selectionKey = getConversationSelectionKey(undefined, sessionId, true)
      await api.updateCrossPaperChatDraft(
        sessionId,
        buildDraft(input, quotes, get().pageSelectionsByConversation[selectionKey])
      )
    } catch {
      // 输入过程中的草稿保存失败不打断交互
    }
  },

  submitPageSelections: async (pageSelections: api.PaperPageSelectionInput[]) => {
    const pending = get().pendingPageSelection
    if (!pending) return

    set({ pendingPageSelection: null, error: null })

    if (pending.mode === 'cross') {
      await get().sendCrossPaperMessage(
        pending.sessionId,
        pending.message,
        pending.quotes,
        pageSelections
      )
      return
    }

    if (!pending.paperId) return
    await get().sendMessage(
      pending.paperId,
      pending.sessionId,
      pending.message,
      pending.quotes,
      pageSelections
    )
  },

  dismissPageSelection: () => {
    set({ pendingPageSelection: null })
  },

  addPaperToCrossChat: async (sessionId: string, newPaperIds: string[], userMessage: string) => {
    try {
      const updatedSession = await api.addPapersToCrossPaperSession(sessionId, newPaperIds)
      set({ crossPaperIds: updatedSession.paper_ids })
      const trimmedMessage = userMessage.trim()
      if (trimmedMessage) {
        await get().sendCrossPaperMessage(sessionId, trimmedMessage)
      }
    } catch (error) {
      set({ error: (error as Error).message })
    }
  },

  exitCrossPaperChat: () => {
    const { currentSessionId, draftInput, quotes } = get()
    if (currentSessionId) {
      void get().saveCrossPaperDraft(currentSessionId, draftInput, quotes)
    }
    set({
      isCrossPaperMode: false,
      crossPaperIds: [],
      messages: [],
      sessions: [],
      currentSessionId: null,
      forks: {},
      currentPaperId: null,
      draftInput: '',
      quotes: [],
      pendingPageSelection: null,
    })
  },
}))
