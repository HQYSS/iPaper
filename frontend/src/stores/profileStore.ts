import { create } from 'zustand'
import * as api from '../services/api'

interface EvolutionMessage {
  role: 'user' | 'assistant'
  content: string
}

interface ProfileStore {
  isEvolutionOpen: boolean
  evolutionMessages: EvolutionMessage[]
  isStreaming: boolean
  error: string | null
  abortController: AbortController | null
  editPlan: { edits: api.ProfileEdit[]; changelog_summary: string } | null
  paperTitle: string

  profileContent: string
  isLoadingProfile: boolean

  sourcePaperId: string | null
  sourceCrossPaperSessionId: string | null

  openEvolution: (paperId: string | null, crossPaperSessionId: string | null) => void
  closeEvolution: () => void
  sendMessage: (message: string) => Promise<void>
  stopStreaming: () => void
  applyEditPlan: () => Promise<void>
  rejectEditPlan: () => void
  clearError: () => void
  loadProfile: () => Promise<void>
}

export const useProfileStore = create<ProfileStore>((set, get) => ({
  isEvolutionOpen: false,
  evolutionMessages: [],
  isStreaming: false,
  error: null,
  abortController: null,
  editPlan: null,
  paperTitle: '',
  profileContent: '',
  isLoadingProfile: false,
  sourcePaperId: null,
  sourceCrossPaperSessionId: null,

  openEvolution: (paperId, crossPaperSessionId) => {
    const { abortController: prev } = get()
    if (prev) prev.abort()

    set({
      isEvolutionOpen: true,
      evolutionMessages: [],
      isStreaming: false,
      error: null,
      abortController: null,
      editPlan: null,
      sourcePaperId: paperId,
      sourceCrossPaperSessionId: crossPaperSessionId,
      paperTitle: '',
    })

    get().loadProfile()

    const autoStartTimer = setTimeout(() => {
      if (get().isEvolutionOpen) {
        get().sendMessage('请分析这次对话，找出画像中哪些地方不够好，导致讲解模型没能完全符合我的预期。')
      }
    }, 100)
    set({ _autoStartTimer: autoStartTimer } as any)
  },

  closeEvolution: () => {
    const state = get()
    if (state.abortController) state.abortController.abort()
    const timer = (state as any)._autoStartTimer
    if (timer) clearTimeout(timer)
    set({
      isEvolutionOpen: false,
      evolutionMessages: [],
      isStreaming: false,
      error: null,
      abortController: null,
      editPlan: null,
      sourcePaperId: null,
      sourceCrossPaperSessionId: null,
      paperTitle: '',
      profileContent: '',
      _autoStartTimer: undefined,
    } as any)
  },

  loadProfile: async () => {
    set({ isLoadingProfile: true })
    try {
      const result = await api.getProfile()
      set({ profileContent: result.content, isLoadingProfile: false })
    } catch {
      set({ isLoadingProfile: false })
    }
  },

  sendMessage: async (message: string) => {
    const { sourcePaperId, sourceCrossPaperSessionId, evolutionMessages } = get()
    const controller = new AbortController()

    const previousMessages = evolutionMessages.map(m => ({
      role: m.role,
      content: m.content,
    }))

    const userMsg: EvolutionMessage = { role: 'user', content: message }
    const assistantMsg: EvolutionMessage = { role: 'assistant', content: '' }

    set(state => ({
      evolutionMessages: [...state.evolutionMessages, userMsg, assistantMsg],
      isStreaming: true,
      error: null,
      abortController: controller,
    }))

    try {
      for await (const data of api.sendEvolutionMessage(
        message,
        previousMessages,
        sourcePaperId ?? undefined,
        sourceCrossPaperSessionId ?? undefined,
        controller.signal,
      )) {
        if (!get().isEvolutionOpen) break

        if (data.type === 'chunk' && data.content) {
          set(state => {
            const msgs = [...state.evolutionMessages]
            const last = msgs[msgs.length - 1]
            if (last.role === 'assistant') {
              last.content += data.content
            }
            return { evolutionMessages: msgs }
          })
        } else if (data.type === 'done') {
          const editPlan = data.edit_plan ?? null
          set({ isStreaming: false, abortController: null, editPlan })
        } else if (data.type === 'error') {
          set(state => ({
            error: data.message || 'Unknown error',
            isStreaming: false,
            abortController: null,
            evolutionMessages: state.evolutionMessages.slice(0, -1),
          }))
        }
      }

      // SSE 连接正常结束但没收到 done 事件（服务器重启等）
      if (get().isStreaming && get().isEvolutionOpen) {
        set(state => {
          const msgs = [...state.evolutionMessages]
          const last = msgs[msgs.length - 1]
          if (last?.role === 'assistant' && !last.content) msgs.pop()
          return {
            evolutionMessages: msgs,
            isStreaming: false,
            abortController: null,
            error: '连接意外断开，请重试',
          }
        })
      }
    } catch (error) {
      if ((error as Error).name === 'AbortError') {
        if (!get().isEvolutionOpen) return
        set(state => {
          const msgs = [...state.evolutionMessages]
          const last = msgs[msgs.length - 1]
          if (last?.role === 'assistant' && !last.content) msgs.pop()
          return { evolutionMessages: msgs, isStreaming: false, abortController: null }
        })
        return
      }
      if (!get().isEvolutionOpen) return
      set({
        error: (error as Error).message,
        isStreaming: false,
        abortController: null,
      })
    }
  },

  stopStreaming: () => {
    const { abortController } = get()
    if (abortController) abortController.abort()
  },

  applyEditPlan: async () => {
    const { editPlan, paperTitle } = get()
    if (!editPlan) return

    try {
      const result = await api.saveEditPlan(editPlan, paperTitle)
      if (!result.validation.valid) {
        set({ error: `编辑验证失败: ${result.validation.issue}` })
        return
      }
      await api.applyProfileUpdates()
      set(state => ({
        editPlan: null,
        evolutionMessages: [
          ...state.evolutionMessages,
          { role: 'assistant', content: '画像已成功更新。' } as EvolutionMessage,
        ],
      }))
      get().loadProfile()
    } catch (error) {
      set({ error: (error as Error).message })
    }
  },

  rejectEditPlan: () => {
    set({ editPlan: null })
  },

  clearError: () => set({ error: null }),
}))
