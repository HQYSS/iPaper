import { create } from 'zustand'
import * as api from '../services/api'

interface CrossPaperState {
  isSelecting: boolean
  selectedPaperIds: string[]
  activeCrossPaperSession: api.CrossPaperSessionMeta | null
  activePdfTab: string | null
}

interface PaperStore {
  papers: api.PaperListItem[]
  selectedPaper: api.PaperListItem | null
  isLoading: boolean
  error: string | null

  crossPaper: CrossPaperState

  fetchPapers: () => Promise<void>
  addPaper: (arxivInput: string) => Promise<void>
  deletePaper: (paperId: string) => Promise<void>
  selectPaper: (paper: api.PaperListItem | null) => void
  clearError: () => void

  enterCrossPaperMode: () => void
  exitCrossPaperMode: () => void
  toggleCrossPaperSelection: (paperId: string) => void
  startCrossChat: () => Promise<void>
  enterCrossChatSession: (session: api.CrossPaperSessionMeta) => void
  setCrossPaperPdfTab: (paperId: string) => void
  updateCrossPaperSessionPaperIds: (paperIds: string[]) => void
}

export const usePaperStore = create<PaperStore>((set, get) => ({
  papers: [],
  selectedPaper: null,
  isLoading: false,
  error: null,

  crossPaper: {
    isSelecting: false,
    selectedPaperIds: [],
    activeCrossPaperSession: null,
    activePdfTab: null,
  },

  fetchPapers: async () => {
    set({ isLoading: true, error: null })
    try {
      const papers = await api.fetchPapers()
      set({ papers, isLoading: false })
    } catch (error) {
      set({ error: (error as Error).message, isLoading: false })
    }
  },

  addPaper: async (arxivInput: string) => {
    set({ isLoading: true, error: null })
    try {
      const paper = await api.addPaper(arxivInput)
      const papers = await api.fetchPapers()
      set({ papers, isLoading: false })
      const newPaper = papers.find(p => p.arxiv_id === paper.arxiv_id)
      if (newPaper) {
        set({ selectedPaper: newPaper })
      }
    } catch (error) {
      set({ error: (error as Error).message, isLoading: false })
      throw error
    }
  },

  deletePaper: async (paperId: string) => {
    set({ isLoading: true, error: null })
    try {
      await api.deletePaper(paperId)
      const papers = await api.fetchPapers()
      const { selectedPaper } = get()
      set({
        papers,
        isLoading: false,
        selectedPaper: selectedPaper?.arxiv_id === paperId ? null : selectedPaper,
      })
    } catch (error) {
      set({ error: (error as Error).message, isLoading: false })
    }
  },

  selectPaper: (paper) => {
    set({
      selectedPaper: paper,
      crossPaper: {
        isSelecting: false,
        selectedPaperIds: [],
        activeCrossPaperSession: null,
        activePdfTab: null,
      },
    })
  },

  clearError: () => {
    set({ error: null })
  },

  enterCrossPaperMode: () => {
    set({
      selectedPaper: null,
      crossPaper: {
        isSelecting: true,
        selectedPaperIds: [],
        activeCrossPaperSession: null,
        activePdfTab: null,
      },
    })
  },

  exitCrossPaperMode: () => {
    set({
      crossPaper: {
        isSelecting: false,
        selectedPaperIds: [],
        activeCrossPaperSession: null,
        activePdfTab: null,
      },
    })
  },

  toggleCrossPaperSelection: (paperId: string) => {
    set((state) => {
      const ids = state.crossPaper.selectedPaperIds
      const isSelected = ids.includes(paperId)
      const newIds = isSelected
        ? ids.filter((id) => id !== paperId)
        : ids.length >= 5
          ? ids
          : [...ids, paperId]
      return {
        crossPaper: { ...state.crossPaper, selectedPaperIds: newIds },
      }
    })
  },

  startCrossChat: async () => {
    const { crossPaper } = get()
    if (crossPaper.selectedPaperIds.length < 2) return

    set({ isLoading: true, error: null })
    try {
      const session = await api.createCrossPaperSession(crossPaper.selectedPaperIds)
      set({
        isLoading: false,
        crossPaper: {
          isSelecting: false,
          selectedPaperIds: [],
          activeCrossPaperSession: session,
          activePdfTab: session.paper_ids[0],
        },
      })
    } catch (error) {
      set({ error: (error as Error).message, isLoading: false })
    }
  },

  enterCrossChatSession: (session: api.CrossPaperSessionMeta) => {
    set({
      selectedPaper: null,
      crossPaper: {
        isSelecting: false,
        selectedPaperIds: [],
        activeCrossPaperSession: session,
        activePdfTab: session.paper_ids[0],
      },
    })
  },

  setCrossPaperPdfTab: (paperId: string) => {
    set((state) => ({
      crossPaper: { ...state.crossPaper, activePdfTab: paperId },
    }))
  },

  updateCrossPaperSessionPaperIds: (paperIds: string[]) => {
    set((state) => {
      if (!state.crossPaper.activeCrossPaperSession) return state
      return {
        crossPaper: {
          ...state.crossPaper,
          activeCrossPaperSession: {
            ...state.crossPaper.activeCrossPaperSession,
            paper_ids: paperIds,
          },
        },
      }
    })
  },
}))

