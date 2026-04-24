import { useEffect, useState, useCallback, useRef, useMemo } from 'react'
import { PanelLeftClose, PanelLeftOpen, PanelRightOpen, Loader2, AlertTriangle, RotateCw } from 'lucide-react'
import { PaperLibrary } from './components/PaperLibrary'
import { PdfViewer } from './components/PdfViewer'
import { ChatPanel } from './components/ChatPanel'
import { CrossPaperViewer } from './components/CrossPaperViewer'
import { ProfilePanel } from './components/ProfilePanel'
import { SettingsModal } from './components/SettingsModal'
import { PaperQuickSwitcher } from './components/PaperQuickSwitcher'
import { LoginPage } from './components/LoginPage'
import { usePaperStore } from './stores/paperStore'
import { useChatStore } from './stores/chatStore'
import { useProfileStore } from './stores/profileStore'
import { useAuthStore } from './stores/authStore'
import { usePreferencesStore } from './stores/preferencesStore'
import { getConfig } from './services/api'
import type { PaperListItem } from './services/api'

const CHAT_MIN_WIDTH = 320
const CHAT_MAX_RATIO = 0.5
const CHAT_DEFAULT_WIDTH = 480
const SIDEBAR_WIDTH = 256
const SIDEBAR_HOVER_TRIGGER_WIDTH = 12
const NARROW_SCREEN_BREAKPOINT = 1024

type ThemeMode = 'light' | 'dark' | 'system'

const cursorMode = new URLSearchParams(window.location.search).get('cursor') === '1'

function applyThemeMode(themeMode: ThemeMode, prefersDark: boolean) {
  const shouldUseDark = themeMode === 'dark' || (themeMode === 'system' && prefersDark)
  document.documentElement.classList.toggle('dark', shouldUseDark)
}

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

  return <AuthenticatedApp />
}

function AuthenticatedApp() {
  const { papers, recentPaperIds, fetchPapers, selectedPaper, crossPaper, exitCrossPaperMode, setCrossPaperPdfTab, selectPaper, addPaper } = usePaperStore()
  const { exitCrossPaperChat } = useChatStore()
  const { isEvolutionOpen, openEvolution, closeEvolution } = useProfileStore()
  const { getThemeMode, setThemeMode: prefsSetThemeMode, getChatPanelWidthRatio, setChatPanelWidthRatio } = usePreferencesStore()
  const isNarrowScreen = useCallback(() => window.innerWidth <= NARROW_SCREEN_BREAKPOINT, [])
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => isNarrowScreen())
  const [sidebarHoverOpen, setSidebarHoverOpen] = useState(false)
  const [chatCollapsed, setChatCollapsed] = useState(() => isNarrowScreen())
  const [chatWidth, setChatWidth] = useState(CHAT_DEFAULT_WIDTH)
  const [isDragging, setIsDragging] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [quickSwitcherOpen, setQuickSwitcherOpen] = useState(false)
  const [themeMode, setThemeMode] = useState<ThemeMode>(() => (getThemeMode() as ThemeMode) || 'system')
  const containerRef = useRef<HTMLDivElement>(null)
  const isSidebarVisible = !sidebarCollapsed || sidebarHoverOpen

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
      if (!config.llm.api_key_configured) {
        setSettingsOpen(true)
      }
    }).catch(() => {})
  }, [fetchPapers])

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (quickSwitcherOpen) return
      if (!(e.metaKey || e.ctrlKey)) return
      const key = e.key.toLowerCase()
      if (key === 'p') {
        if (quickSwitcherPapers.length === 0) return
        e.preventDefault()
        setQuickSwitcherOpen(true)
      } else if (key === 'b') {
        e.preventDefault()
        setSidebarCollapsed(prev => !prev)
        setSidebarHoverOpen(false)
      } else if (key === 'l') {
        e.preventDefault()
        setChatCollapsed(prev => !prev)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [quickSwitcherOpen, quickSwitcherPapers.length])

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
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
    const updateTheme = () => applyThemeMode(themeMode, mediaQuery.matches)

    updateTheme()

    if (themeMode !== 'system') {
      return
    }

    mediaQuery.addEventListener('change', updateTheme)
    return () => mediaQuery.removeEventListener('change', updateTheme)
  }, [themeMode])

  const handleThemeModeChange = useCallback((nextThemeMode: ThemeMode) => {
    setThemeMode(nextThemeMode)
    prefsSetThemeMode(nextThemeMode)
    applyThemeMode(nextThemeMode, window.matchMedia('(prefers-color-scheme: dark)').matches)
  }, [prefsSetThemeMode])

  useEffect(() => {
    if (!selectedPaper) return

    setSidebarCollapsed(true)
    setSidebarHoverOpen(false)
    if (isNarrowScreen()) setChatCollapsed(true)
  }, [selectedPaper, isNarrowScreen])

  useEffect(() => {
    if (!isInCrossChat) return

    setSidebarCollapsed(true)
    setSidebarHoverOpen(false)
    if (!isNarrowScreen()) setChatCollapsed(false)
  }, [isInCrossChat, isNarrowScreen])

  const handleSidebarToggle = useCallback(() => {
    if (sidebarCollapsed) {
      setSidebarCollapsed(false)
      setSidebarHoverOpen(false)
      return
    }

    setSidebarCollapsed(true)
    setSidebarHoverOpen(false)
  }, [sidebarCollapsed])

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
  }, [settingsOpen, isEvolutionOpen])

  // 下载中 / 下载失败的论文不渲染对话面板：LLM 调用依赖 PDF，必须等 ready
  const singlePaperDownloadStatus = selectedPaper?.download_status ?? 'ready'
  const singlePaperReady = !selectedPaper || singlePaperDownloadStatus === 'ready'
  const showChat = ((showSinglePaper && singlePaperReady) || isInCrossChat) && !cursorMode

  return (
    <div ref={containerRef} className="relative h-screen flex bg-background">
      {sidebarCollapsed && !sidebarHoverOpen && (
        <div
          className="absolute left-0 top-0 bottom-0 z-20"
          style={{ width: SIDEBAR_HOVER_TRIGGER_WIDTH }}
          onMouseEnter={() => setSidebarHoverOpen(true)}
        />
      )}

      {/* 左侧：论文库（可折叠） */}
      <aside
        className={`${isSidebarVisible ? 'border-r border-border' : ''} relative flex-shrink-0 overflow-hidden transition-all duration-200 ease-in-out`}
        style={{ width: isSidebarVisible ? SIDEBAR_WIDTH : 0 }}
        onMouseLeave={() => {
          if (sidebarCollapsed) {
            setSidebarHoverOpen(false)
          }
        }}
      >
        <div className="h-full" style={{ width: SIDEBAR_WIDTH }}>
          <PaperLibrary onOpenSettings={() => setSettingsOpen(true)} />
        </div>
      </aside>

      {/* 左栏切换按钮 */}
      {isSidebarVisible && (
        <button
          onClick={handleSidebarToggle}
          className="absolute top-3 z-30 p-1.5 rounded-md hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
          style={{ left: SIDEBAR_WIDTH - 28 }}
          title={sidebarCollapsed ? '固定展开论文库' : '收起论文库'}
        >
          {sidebarCollapsed ? (
            <PanelLeftOpen className="w-4 h-4" />
          ) : (
            <PanelLeftClose className="w-4 h-4" />
          )}
        </button>
      )}

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
                    <Loader2 className="w-8 h-8 animate-spin mx-auto mb-4 text-indigo-500" />
                    <h2 className="text-lg font-medium mb-1">正在下载英文 PDF…</h2>
                    <p className="text-sm text-muted-foreground">
                      下载完成后这里会自动进入阅读界面。你可以继续浏览或添加其他论文。
                    </p>
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
                      多数是 arXiv 速率限制或网络抖动，稍后重试通常可恢复。
                    </p>
                    <button
                      onClick={() => addPaper(selectedPaper.arxiv_id)}
                      className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium bg-red-500 hover:bg-red-600 text-white rounded-lg transition-all shadow-sm"
                    >
                      <RotateCw className="w-4 h-4" />
                      重新下载
                    </button>
                  </div>
                </div>
              )
            }
            return <PdfViewer paperId={selectedPaper.arxiv_id} />
          })()
        ) : (
          <div className="flex-1 flex items-center justify-center text-muted-foreground">
            <div className="text-center">
              <h2 className="text-xl font-medium mb-2">欢迎使用 iPaper</h2>
              <p>从左侧添加论文开始阅读</p>
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
                ) : (
                  <ChatPanel
                    paperId={selectedPaper!.arxiv_id}
                    onCollapse={() => setChatCollapsed(true)}
                    onOpenEvolution={handleOpenEvolution}
                  />
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
        onThemeModeChange={handleThemeModeChange}
      />
      <PaperQuickSwitcher
        open={quickSwitcherOpen}
        papers={quickSwitcherPapers}
        title={isInCrossChat ? '切换当前串讲中的论文' : '切换论文'}
        onClose={handleQuickSwitcherClose}
        onSelect={handleQuickSwitcherSelect}
      />
    </div>
  )
}

export default App
