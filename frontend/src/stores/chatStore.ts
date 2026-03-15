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

  pendingProfileUpdate: api.PendingProfileUpdate | null

  loadHistory: (paperId: string) => Promise<void>
  sendMessage: (paperId: string, message: string, quotes?: QuoteItem[]) => Promise<void>
  clearHistory: (paperId: string) => Promise<void>
  clearError: () => void
  addQuote: (text: string, source: QuoteSource) => void
  removeQuote: (index: number) => void
  clearQuotes: () => void

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
  pendingProfileUpdate: null,
  isAnalyzingProfile: false,

  loadHistory: async (paperId: string) => {
    if (get().currentPaperId !== paperId) {
      set({ messages: [], currentPaperId: paperId })
    }

    set({ isLoading: true, error: null })
    try {
      const history = await api.getChatHistory(paperId)
      set({ messages: history.messages, isLoading: false })

      if (history.messages.length === 0) {
        setTimeout(() => {
          const store = get()
          if (store.currentPaperId === paperId && store.messages.length === 0 && !store.isStreaming) {
            store.sendMessage(paperId, AUTO_EXPLAIN_MESSAGE)
          }
        }, 300)
      }
    } catch (error) {
      set({ error: (error as Error).message, isLoading: false })
    }
  },

  sendMessage: async (paperId: string, message: string, quotes?: QuoteItem[]) => {
    const { messages } = get()

    const userMessage: api.ChatMessage = { role: 'user', content: message }
    set({ messages: [...messages, userMessage], isStreaming: true, error: null })

    const assistantMessage: api.ChatMessage = { role: 'assistant', content: '' }
    set({ messages: [...messages, userMessage, assistantMessage] })

    try {
      for await (const data of api.sendMessage(paperId, message, quotes)) {
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
          set({ isStreaming: false })
        } else if (data.type === 'error') {
          set((state) => ({
            error: data.message || 'Unknown error',
            isStreaming: false,
            messages: state.messages.filter((_, i) => i !== state.messages.length - 1),
          }))
        }
      }
    } catch (error) {
      set({ error: (error as Error).message, isStreaming: false })
      set((state) => ({
        messages: state.messages.filter((_, i) => i !== state.messages.length - 1),
      }))
    }
  },

  clearHistory: async (paperId: string) => {
    set({ isLoading: true, error: null })
    try {
      await api.clearChatHistory(paperId)
      set({ messages: [], isLoading: false })
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
