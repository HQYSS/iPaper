import { create } from 'zustand'
import * as api from '../services/api'

interface PaperStore {
  papers: api.PaperListItem[]
  selectedPaper: api.PaperListItem | null
  isLoading: boolean
  error: string | null

  fetchPapers: () => Promise<void>
  addPaper: (arxivInput: string) => Promise<void>
  deletePaper: (paperId: string) => Promise<void>
  selectPaper: (paper: api.PaperListItem | null) => void
  clearError: () => void
}

export const usePaperStore = create<PaperStore>((set, get) => ({
  papers: [],
  selectedPaper: null,
  isLoading: false,
  error: null,

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
      // 自动选中新添加的论文
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
    set({ selectedPaper: paper })
  },

  clearError: () => {
    set({ error: null })
  },
}))

