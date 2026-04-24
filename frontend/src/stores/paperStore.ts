import { create } from 'zustand'
import * as api from '../services/api'
import { fetchPapersOffline } from '../services/offlineApi'
import { usePreferencesStore } from './preferencesStore'

const DOWNLOAD_POLL_INTERVAL_MS = 2000
let downloadPollTimer: ReturnType<typeof setInterval> | null = null
let pollerAttached = false

function hasDownloadingPaper(papers: api.PaperListItem[]): boolean {
  return papers.some((p) => (p.download_status ?? 'ready') === 'downloading')
}

function getStoredRecentPaperIds(): string[] {
  return usePreferencesStore.getState().getRecentPaperIds()
}

function saveRecentPaperIds(paperIds: string[]) {
  usePreferencesStore.getState().setRecentPaperIds(paperIds)
}

function movePaperToFront(paperIds: string[], paperId: string): string[] {
  return [paperId, ...paperIds.filter((id) => id !== paperId)]
}

function syncRecentPaperIds(paperIds: string[], papers: api.PaperListItem[]): string[] {
  const validPaperIds = new Set(papers.map((paper) => paper.arxiv_id))
  return paperIds.filter((paperId) => validPaperIds.has(paperId))
}

interface CrossPaperState {
  isSelecting: boolean
  selectedPaperIds: string[]
  activeCrossPaperSession: api.CrossPaperSessionMeta | null
  activePdfTab: string | null
}

interface PaperStore {
  papers: api.PaperListItem[]
  selectedPaper: api.PaperListItem | null
  recentPaperIds: string[]
  isLoading: boolean
  error: string | null

  crossPaper: CrossPaperState

  fetchPapers: () => Promise<void>
  addPaper: (arxivInput: string) => Promise<void>
  deletePaper: (paperId: string) => Promise<void>
  selectPaper: (paper: api.PaperListItem | null) => void
  clearError: () => void
  ensureDownloadPolling: () => void

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
  recentPaperIds: getStoredRecentPaperIds(),
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
      const papers = await fetchPapersOffline()
      const recentPaperIds = syncRecentPaperIds(get().recentPaperIds, papers)
      saveRecentPaperIds(recentPaperIds)
      set({ papers, recentPaperIds, isLoading: false })
      get().ensureDownloadPolling()
    } catch (error) {
      set({ error: (error as Error).message, isLoading: false })
    }
  },

  addPaper: async (arxivInput: string) => {
    set({ isLoading: true, error: null })
    try {
      const paper = await api.addPaper(arxivInput)
      const papers = await fetchPapersOffline()
      const newPaper = papers.find(p => p.arxiv_id === paper.arxiv_id)
      const syncedRecentPaperIds = syncRecentPaperIds(get().recentPaperIds, papers)
      const recentPaperIds = newPaper
        ? movePaperToFront(syncedRecentPaperIds, newPaper.arxiv_id)
        : syncedRecentPaperIds
      saveRecentPaperIds(recentPaperIds)
      if (newPaper) {
        set({
          papers,
          selectedPaper: newPaper,
          recentPaperIds,
          isLoading: false,
        })
      } else {
        set({ papers, recentPaperIds, isLoading: false })
      }
      get().ensureDownloadPolling()
    } catch (error) {
      set({ error: (error as Error).message, isLoading: false })
      throw error
    }
  },

  deletePaper: async (paperId: string) => {
    set({ isLoading: true, error: null })
    try {
      await api.deletePaper(paperId)
      const papers = await fetchPapersOffline()
      const { selectedPaper, recentPaperIds } = get()
      const nextRecentPaperIds = syncRecentPaperIds(
        recentPaperIds.filter((id) => id !== paperId),
        papers
      )
      saveRecentPaperIds(nextRecentPaperIds)
      set({
        papers,
        isLoading: false,
        selectedPaper: selectedPaper?.arxiv_id === paperId ? null : selectedPaper,
        recentPaperIds: nextRecentPaperIds,
      })
    } catch (error) {
      set({ error: (error as Error).message, isLoading: false })
    }
  },

  selectPaper: (paper) => {
    const recentPaperIds = paper
      ? movePaperToFront(syncRecentPaperIds(get().recentPaperIds, get().papers), paper.arxiv_id)
      : get().recentPaperIds
    if (paper) {
      saveRecentPaperIds(recentPaperIds)
    }
    set({
      selectedPaper: paper,
      recentPaperIds,
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

  /**
   * 存在 download_status === 'downloading' 的论文时，启动 2s 周期性刷新；
   * 全部 ready/failed 后自动停止。幂等——重复调用只启动一个 timer。
   * 同时驱动 selectedPaper 随新列表更新（让 PdfViewer 感知状态变化）。
   */
  ensureDownloadPolling: () => {
    const { papers } = get()
    if (!hasDownloadingPaper(papers)) {
      if (downloadPollTimer) {
        clearInterval(downloadPollTimer)
        downloadPollTimer = null
      }
      return
    }
    if (pollerAttached && downloadPollTimer) return
    pollerAttached = true
    const tick = async () => {
      try {
        const fresh = await fetchPapersOffline()
        const { selectedPaper, recentPaperIds } = get()
        const syncedRecent = syncRecentPaperIds(recentPaperIds, fresh)
        const nextSelected = selectedPaper
          ? fresh.find((p) => p.arxiv_id === selectedPaper.arxiv_id) ?? selectedPaper
          : null
        set({ papers: fresh, recentPaperIds: syncedRecent, selectedPaper: nextSelected })
        if (!hasDownloadingPaper(fresh)) {
          if (downloadPollTimer) {
            clearInterval(downloadPollTimer)
            downloadPollTimer = null
          }
          pollerAttached = false
        }
      } catch {
        // 瞬时错误不终止轮询
      }
    }
    tick()
    downloadPollTimer = setInterval(tick, DOWNLOAD_POLL_INTERVAL_MS)
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
      const recentPaperIds = session.paper_ids[0]
        ? movePaperToFront(syncRecentPaperIds(get().recentPaperIds, get().papers), session.paper_ids[0])
        : get().recentPaperIds
      if (session.paper_ids[0]) {
        saveRecentPaperIds(recentPaperIds)
      }
      set({
        isLoading: false,
        recentPaperIds,
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
    const recentPaperIds = session.paper_ids[0]
      ? movePaperToFront(syncRecentPaperIds(get().recentPaperIds, get().papers), session.paper_ids[0])
      : get().recentPaperIds
    if (session.paper_ids[0]) {
      saveRecentPaperIds(recentPaperIds)
    }
    set({
      selectedPaper: null,
      recentPaperIds,
      crossPaper: {
        isSelecting: false,
        selectedPaperIds: [],
        activeCrossPaperSession: session,
        activePdfTab: session.paper_ids[0],
      },
    })
  },

  setCrossPaperPdfTab: (paperId: string) => {
    const recentPaperIds = movePaperToFront(syncRecentPaperIds(get().recentPaperIds, get().papers), paperId)
    saveRecentPaperIds(recentPaperIds)
    set((state) => ({
      recentPaperIds,
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

