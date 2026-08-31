import { useEffect, useState, useCallback, useRef, useMemo } from 'react'
import { LibraryBig, PanelRightOpen, AlertTriangle, RotateCw, Plus } from 'lucide-react'
import { PaperLibrary } from './components/PaperLibrary'
import { PdfViewer } from './components/PdfViewer'
import { ChatPanel } from './components/ChatPanel'
import { CrossPaperViewer } from './components/CrossPaperViewer'
import { ProfilePanel } from './components/ProfilePanel'
import { SettingsModal } from './components/SettingsModal'
import { PaperQuickSwitcher } from './components/PaperQuickSwitcher'
import { AddPaperModal } from './components/AddPaperModal'
import { LoginPage } from './components/LoginPage'
import { MobileLayout } from './components/MobileLayout'
import { usePaperStore } from './stores/paperStore'
import { useChatStore } from './stores/chatStore'
import { useProfileStore } from './stores/profileStore'
import { useAuthStore } from './stores/authStore'
import { usePreferencesStore } from './stores/preferencesStore'
import { acknowledgePaperOpenRequest, getConfig, getPaper, getPaperOpenRequest, reportClientLog } from './services/api'
import { useDeviceLayout } from './hooks/useDeviceLayout'
import { useThemeMode, applyThemeMode } from './hooks/useThemeMode'
import { formatDownloadError } from './lib/downloadError'
import type { ThemeMode } from './hooks/useThemeMode'
import type { PaperListItem } from './services/api'
import { PdfPreparationStatus } from './components/PdfPreparationStatus'
import { SocialHub } from './components/SocialHub'

const CHAT_MIN_WIDTH = 320
const CHAT_MAX_RATIO = 0.5
const CHAT_DEFAULT_WIDTH = 480
const NARROW_SCREEN_BREAKPOINT = 1024

const openRequestTarget = (
  window.electronAPI?.isElectron
  || new URLSearchParams(window.location.search).get('electron') === '1'
) ? 'electron' : 'web'

function clampChatWidth(width: number, containerWidth: number) {
  const maxWidth = containerWidth * CHAT_MAX_RATIO
  return Math.max(CHAT_MIN_WIDTH, Math.min(maxWidth, width))
}

function App() {
  const { isAuthenticated, checkAuth, logout } = useAuthStore()
  const loadPreferences = usePreferencesStore((s) => s.loadPreferences)
  const [authChecked, setAuthChecked] = useState(false)

  // Apply cached theme immediately so login page respects dark mode
  useEffect(() => {
    const cached = usePreferencesStore.getState().getThemeMode() as ThemeMode
    applyThemeMode(cached || 'system', window.matchMedia('(prefers-color-scheme: dark)').matches)
  }, [])

  useEffect(() => {
    checkAuth().finally(() => setAuthChecked(true))
  }, [checkAuth])

  useEffect(() => {
    if (!isAuthenticated) return
    loadPreferences()
  }, [isAuthenticated, loadPreferences])

  // Handle 401 token expiry from any API call
  useEffect(() => {
    const handler = () => logout()
    window.addEventListener('ipaper:auth-expired', handler)
    return () => window.removeEventListener('ipaper:auth-expired', handler)
  }, [logout])

  if (!authChecked) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="text-muted-foreground text-sm">加载中…</div>
      </div>
    )
  }

  if (!isAuthenticated) {
    return <LoginPage />
  }

  return <AuthenticatedRouter />
}

function AuthenticatedRouter() {
  const layout = useDeviceLayout()
  const { themeMode, setThemeMode } = useThemeMode()
  usePaperOpenRequests()

  if (layout === 'mobile') {
    return <MobileLayout themeMode={themeMode} onThemeModeChange={setThemeMode} />
  }

  // 平板（768-1023）暂时复用桌面三栏布局：iPad 横屏完全够用，
  // 竖屏会退化成"窄桌面"，后续 task 8 再做平板专属抽屉式布局。
  return <AuthenticatedApp themeMode={themeMode} onThemeModeChange={setThemeMode} />
}

function usePaperOpenRequests() {
  const fetchPapers = usePaperStore((state) => state.fetchPapers)
  const selectPaper = usePaperStore((state) => state.selectPaper)

  useEffect(() => {
    let cancelled = false
    let polling = false

    const pollOpenRequest = async () => {
      if (polling) return
      polling = true
      try {
        const request = await getPaperOpenRequest(openRequestTarget)
        if (!cancelled && request.paper_id && request.request_id) {
          const paper = await getPaper(request.paper_id)
          if (cancelled) return
          selectPaper(paper)
          await acknowledgePaperOpenRequest(request.request_id)
          void fetchPapers()
        }
      } catch (error) {
        reportClientLog('error', 'paper open request handling failed', {
          target: openRequestTarget,
          error: (error as Error).message,
        })
      } finally {
        polling = false
      }
    }

    pollOpenRequest()
    const timer = window.setInterval(pollOpenRequest, 1200)
    const unsubscribe = window.electronAPI?.onAppActivated?.(pollOpenRequest)
    return () => {
      cancelled = true
      window.clearInterval(timer)
      unsubscribe?.()
    }
  }, [fetchPapers, selectPaper])
}

interface AuthenticatedAppProps {
  themeMode: ThemeMode
  onThemeModeChange: (mode: ThemeMode) => void
}

function AuthenticatedApp({ themeMode, onThemeModeChange }: AuthenticatedAppProps) {
  const { papers, recentPaperIds, fetchPapers, selectedPaper, crossPaper, exitCrossPaperMode, setCrossPaperPdfTab, selectPaper, addPaper } = usePaperStore()
  const exitCrossPaperChat = useChatStore((state) => state.exitCrossPaperChat)
  const { isEvolutionOpen, openEvolution, closeEvolution } = useProfileStore()
  const { getChatPanelWidthRatio, setChatPanelWidthRatio } = usePreferencesStore()
  const isNarrowScreen = useCallback(() => window.innerWidth <= NARROW_SCREEN_BREAKPOINT, [])
  const [libraryOpen, setLibraryOpen] = useState(false)
  const [socialOpen, setSocialOpen] = useState(false)
  const [chatCollapsed, setChatCollapsed] = useState(() => isNarrowScreen())
  const [chatWidth, setChatWidth] = useState(CHAT_DEFAULT_WIDTH)
  const [isDragging, setIsDragging] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [quickSwitcherOpen, setQuickSwitcherOpen] = useState(false)
  const [addPaperOpen, setAddPaperOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  const isInCrossChat = !!crossPaper.activeCrossPaperSession
  const showSinglePaper = !!selectedPaper && !isInCrossChat
  const currentQuickSwitcherPaperId = isInCrossChat
    ? (crossPaper.activePdfTab ?? crossPaper.activeCrossPaperSession?.paper_ids[0] ?? null)
    : (selectedPaper?.arxiv_id ?? null)
  const quickSwitcherPapers = useMemo(() => {
    const paperMap = new Map(papers.map((paper) => [paper.arxiv_id, paper]))
    const allowedPaperIds = isInCrossChat && crossPaper.activeCrossPaperSession
      ? crossPaper.activeCrossPaperSession.paper_ids
      : papers.map((paper) => paper.arxiv_id)

    const allowedPaperIdSet = new Set(allowedPaperIds)
    const orderedPaperIds = [
      ...recentPaperIds.filter((paperId) => allowedPaperIdSet.has(paperId)),
      ...allowedPaperIds.filter((paperId) => !recentPaperIds.includes(paperId)),
    ]

    return orderedPaperIds
      .filter((paperId) => paperId !== currentQuickSwitcherPaperId)
      .map((paperId) => paperMap.get(paperId))
      .filter((paper): paper is PaperListItem => Boolean(paper))
  }, [isInCrossChat, crossPaper.activeCrossPaperSession, papers, recentPaperIds, currentQuickSwitcherPaperId])

  useEffect(() => {
    fetchPapers()
    getConfig().then((config) => {
      const llmReady = config.llm.api_key_configured
      if (!llmReady) {
        setSettingsOpen(true)
      }
    }).catch(() => {})
  }, [fetchPapers])

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (quickSwitcherOpen || addPaperOpen) return
      if (e.key === 'Escape' && libraryOpen) {
        e.preventDefault()
        setLibraryOpen(false)
        return
      }
      if (!(e.metaKey || e.ctrlKey)) return
      if (e.shiftKey || e.altKey) return
      const key = e.key.toLowerCase()
      if (key === 'p') {
        if (quickSwitcherPapers.length === 0) return
        e.preventDefault()
        setQuickSwitcherOpen(true)
      } else if (key === 'b') {
        e.preventDefault()
        setLibraryOpen(prev => !prev)
      } else if (key === 'l') {
        e.preventDefault()
        setChatCollapsed(prev => !prev)
      } else if (key === 'n') {
        if (settingsOpen || isEvolutionOpen) return
        e.preventDefault()
        setAddPaperOpen(true)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [quickSwitcherOpen, addPaperOpen, libraryOpen, settingsOpen, isEvolutionOpen, quickSwitcherPapers.length])

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }, [])

  useEffect(() => {
    if (!isDragging) return

    const handleMouseMove = (e: MouseEvent) => {
      if (!containerRef.current) return
      const containerRect = containerRef.current.getBoundingClientRect()
      const newWidth = containerRect.right - e.clientX
      const clampedWidth = clampChatWidth(newWidth, containerRect.width)
      setChatWidth(clampedWidth)
      setChatPanelWidthRatio(clampedWidth / containerRect.width)
    }

    const handleMouseUp = () => setIsDragging(false)

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isDragging])

  useEffect(() => {
    const updateChatWidth = () => {
      if (!containerRef.current) return
      const containerWidth = containerRef.current.getBoundingClientRect().width
      const storedRatio = getChatPanelWidthRatio()
      const targetWidth = storedRatio ? containerWidth * storedRatio : CHAT_DEFAULT_WIDTH
      const clampedWidth = clampChatWidth(targetWidth, containerWidth)

      setChatWidth(clampedWidth)

      if (containerWidth > 0) {
        setChatPanelWidthRatio(clampedWidth / containerWidth)
      }

      if (window.innerWidth <= NARROW_SCREEN_BREAKPOINT) {
        setChatCollapsed(true)
      }
    }

    updateChatWidth()
    window.addEventListener('resize', updateChatWidth)
    return () => window.removeEventListener('resize', updateChatWidth)
  }, [getChatPanelWidthRatio, setChatPanelWidthRatio])

  useEffect(() => {
    if (isInCrossChat && !isNarrowScreen()) setChatCollapsed(false)
  }, [isInCrossChat, isNarrowScreen])

  const handleExitCrossChat = useCallback(() => {
    exitCrossPaperChat()
    exitCrossPaperMode()
  }, [exitCrossPaperChat, exitCrossPaperMode])

  const handlePaperLinkClick = useCallback((paperId: string) => {
    setCrossPaperPdfTab(paperId)
  }, [setCrossPaperPdfTab])

  const handleOpenEvolution = useCallback(() => {
    if (isInCrossChat && crossPaper.activeCrossPaperSession) {
      openEvolution(null, crossPaper.activeCrossPaperSession.id)
    } else if (selectedPaper) {
      openEvolution(selectedPaper.arxiv_id, null)
    }
  }, [isInCrossChat, crossPaper.activeCrossPaperSession, selectedPaper, openEvolution])

  const handleCloseEvolution = useCallback(() => {
    closeEvolution()
  }, [closeEvolution])

  const handleQuickSwitcherClose = useCallback(() => {
    setQuickSwitcherOpen(false)
  }, [])

  const handleQuickSwitcherSelect = useCallback((paper: PaperListItem) => {
    if (isInCrossChat) {
      setCrossPaperPdfTab(paper.arxiv_id)
    } else {
      selectPaper(paper)
    }
    setQuickSwitcherOpen(false)
  }, [isInCrossChat, selectPaper, setCrossPaperPdfTab])

  useEffect(() => {
    if (!settingsOpen && !isEvolutionOpen) return
    setQuickSwitcherOpen(false)
    setAddPaperOpen(false)
  }, [settingsOpen, isEvolutionOpen])

  // 下载中 / 下载失败的论文不渲染对话面板：LLM 调用依赖 PDF，必须等 ready
  const singlePaperDownloadStatus = selectedPaper?.download_status ?? 'ready'
  const singlePaperReady = !selectedPaper || singlePaperDownloadStatus === 'ready'
  const cloudPdfReady = !selectedPaper || selectedPaper.cloud_download_status !== 'downloading'
  const cloudPdfFailed = selectedPaper?.cloud_download_status === 'failed'
  const showChat = (showSinglePaper && singlePaperReady) || isInCrossChat

  return (
    <div ref={containerRef} className="relative h-screen flex bg-background">
      {!libraryOpen && (
        <button
          onClick={() => setLibraryOpen(true)}
          className="absolute left-4 top-4 z-30 inline-flex items-center gap-2 rounded-lg border border-border bg-background/90 px-3 py-2 text-sm text-foreground shadow-sm backdrop-blur hover:bg-accent transition-colors"
          title="打开论文库 (Ctrl/⌘B)"
        >
          <LibraryBig className="w-4 h-4" />
          论文库
          <span className="text-[11px] text-muted-foreground font-mono">Ctrl/⌘B</span>
        </button>
      )}

      {libraryOpen && (
        <div className="fixed inset-0 z-50 bg-background">
          <PaperLibrary
            fullScreen
            onClose={() => setLibraryOpen(false)}
            onOpenSettings={() => setSettingsOpen(true)}
            onOpenAddPaper={() => setAddPaperOpen(true)}
            onOpenSocial={() => setSocialOpen(true)}
          />
        </div>
      )}
      {socialOpen && <SocialHub onClose={() => setSocialOpen(false)} />}

      {/* 中间：PDF 阅读器 / 串讲多 PDF 视图 / 进化面板 */}
      <main className="flex-1 flex flex-col min-w-0 min-h-0 overflow-hidden">
        {isEvolutionOpen ? (
          <ProfilePanel onClose={handleCloseEvolution} />
        ) : isInCrossChat ? (
          <CrossPaperViewer />
        ) : selectedPaper ? (
          (() => {
            const status = selectedPaper.download_status ?? 'ready'
            if (status === 'downloading') {
              return (
                <div className="flex-1 flex items-center justify-center text-muted-foreground px-6">
                  <div className="text-center max-w-md">
                    <PdfPreparationStatus
                      title="正在下载英文 PDF"
                      downloadedBytes={selectedPaper.download_bytes}
                      totalBytes={selectedPaper.download_total_bytes}
                      progress={selectedPaper.download_progress}
                    />
                  </div>
                </div>
              )
            }
            if (status === 'failed') {
              return (
                <div className="flex-1 flex items-center justify-center px-6">
                  <div className="text-center max-w-md">
                    <AlertTriangle className="w-10 h-10 mx-auto mb-4 text-red-500" />
                    <h2 className="text-lg font-semibold mb-1 text-red-600 dark:text-red-400">英文 PDF 下载失败</h2>
                    <p className="text-sm text-muted-foreground mb-2 break-words">
                      已重试 3 次仍未成功
                      {selectedPaper.download_error ? `：${selectedPaper.download_error}` : '。'}
                    </p>
                    <p className="text-xs text-muted-foreground mb-4">
                      {formatDownloadError(selectedPaper.download_error)}
                    </p>
                    <button
                      onClick={() => addPaper(selectedPaper.source_type === 'pdf_url' ? selectedPaper.source_url || selectedPaper.arxiv_id : selectedPaper.arxiv_id)}
                      className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium bg-red-500 hover:bg-red-600 text-white rounded-lg transition-all shadow-sm"
                    >
                      <RotateCw className="w-4 h-4" />
                      重新下载
                    </button>
                  </div>
                </div>
              )
            }
            return <PdfViewer paperId={selectedPaper.arxiv_id} sourceType={selectedPaper.source_type} />
          })()
        ) : (
          <div className="flex-1 flex items-center justify-center text-muted-foreground">
            <div className="text-center">
              <h2 className="text-xl font-medium mb-2">欢迎使用 iPaper</h2>
                <p className="mb-5">打开论文库添加或选择论文</p>
              <button
                onClick={() => setAddPaperOpen(true)}
                className="inline-flex items-center gap-2 px-5 py-2.5 text-sm font-medium rounded-xl bg-gradient-to-r from-indigo-500 to-purple-500 text-white hover:from-indigo-600 hover:to-purple-600 shadow-sm shadow-indigo-500/20 transition-all"
              >
                <Plus className="w-4 h-4" />
                添加论文
                <span className="ml-1 text-[11px] opacity-80 font-mono">⌘N</span>
              </button>
            </div>
          </div>
        )}
      </main>

      {/* 右侧：讲解面板 */}
      {showChat && (
        <>
          {chatCollapsed ? (
            <button
              onClick={() => setChatCollapsed(false)}
              className="flex-shrink-0 w-8 flex items-center justify-center border-l border-border hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
              title="展开讲解面板"
            >
              <PanelRightOpen className="w-4 h-4" />
            </button>
          ) : (
            <>
              {/* 拖拽分隔条 */}
              <div
                onMouseDown={handleMouseDown}
                className="flex-shrink-0 w-1 cursor-col-resize hover:bg-primary/30 active:bg-primary/50 transition-colors relative group"
              >
                <div className="absolute inset-y-0 -left-1 -right-1" />
              </div>

              <aside
                className="flex-shrink-0 overflow-hidden"
                style={{
                  width: chatWidth,
                  pointerEvents: isDragging ? 'none' : undefined,
                }}
              >
                {isInCrossChat ? (
                  <ChatPanel
                    crossPaperSessionId={crossPaper.activeCrossPaperSession!.id}
                    onCollapse={() => setChatCollapsed(true)}
                    onPaperLinkClick={handlePaperLinkClick}
                    onExitCrossChat={handleExitCrossChat}
                    onOpenEvolution={handleOpenEvolution}
                  />
                ) : cloudPdfFailed ? (
                  <div className="h-full flex items-center justify-center px-8 border-l border-border bg-background">
                    <div className="max-w-sm text-center">
                      <AlertTriangle className="w-8 h-8 mx-auto mb-3 text-red-500" />
                      <h2 className="text-base font-medium">云端 PDF 下载失败</h2>
                      <p className="mt-2 text-sm text-muted-foreground break-words">
                        {selectedPaper!.cloud_download_error || '请稍后重新打开论文以重试'}
                      </p>
                    </div>
                  </div>
                ) : cloudPdfReady ? (
                  <ChatPanel
                    paperId={selectedPaper!.arxiv_id}
                    onCollapse={() => setChatCollapsed(true)}
                    onOpenEvolution={handleOpenEvolution}
                  />
                ) : (
                  <div className="h-full flex items-center justify-center px-8 border-l border-border bg-background">
                    <PdfPreparationStatus
                      title="云端正在准备 PDF"
                      downloadedBytes={selectedPaper!.cloud_download_bytes}
                      totalBytes={selectedPaper!.cloud_download_total_bytes}
                      progress={selectedPaper!.cloud_download_progress}
                    />
                  </div>
                )}
              </aside>
            </>
          )}
        </>
      )}

      {/* 拖拽时禁止 PDF iframe 吞事件 */}
      {isDragging && (
        <div className="fixed inset-0 z-50 cursor-col-resize" />
      )}

      <SettingsModal
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        themeMode={themeMode}
        onThemeModeChange={onThemeModeChange}
      />
      <PaperQuickSwitcher
        open={quickSwitcherOpen}
        papers={quickSwitcherPapers}
        title={isInCrossChat ? '切换当前串讲中的论文' : '切换论文'}
        onClose={handleQuickSwitcherClose}
        onSelect={handleQuickSwitcherSelect}
      />
      <AddPaperModal
        open={addPaperOpen}
        onClose={() => setAddPaperOpen(false)}
      />
    </div>
  )
}

export default App
