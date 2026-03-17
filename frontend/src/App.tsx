import { useEffect, useState, useCallback, useRef } from 'react'
import { PanelLeftClose, PanelLeftOpen, PanelRightOpen } from 'lucide-react'
import { PaperLibrary } from './components/PaperLibrary'
import { PdfViewer } from './components/PdfViewer'
import { ChatPanel } from './components/ChatPanel'
import { SettingsModal } from './components/SettingsModal'
import { usePaperStore } from './stores/paperStore'
import { getConfig } from './services/api'

const CHAT_MIN_WIDTH = 320
const CHAT_MAX_RATIO = 0.5
const CHAT_DEFAULT_WIDTH = 480
const CHAT_WIDTH_STORAGE_KEY = 'ipaper.chatPanelWidthRatio'
const THEME_MODE_STORAGE_KEY = 'ipaper.themeMode'

type ThemeMode = 'light' | 'dark' | 'system'

const cursorMode = new URLSearchParams(window.location.search).get('cursor') === '1'

function isValidThemeMode(value: string | null): value is ThemeMode {
  return value === 'light' || value === 'dark' || value === 'system'
}

function getStoredThemeMode(): ThemeMode {
  const rawValue = window.localStorage.getItem(THEME_MODE_STORAGE_KEY)
  return isValidThemeMode(rawValue) ? rawValue : 'system'
}

function applyThemeMode(themeMode: ThemeMode, prefersDark: boolean) {
  const shouldUseDark = themeMode === 'dark' || (themeMode === 'system' && prefersDark)
  document.documentElement.classList.toggle('dark', shouldUseDark)
}

function clampChatWidth(width: number, containerWidth: number) {
  const maxWidth = containerWidth * CHAT_MAX_RATIO
  return Math.max(CHAT_MIN_WIDTH, Math.min(maxWidth, width))
}

function getStoredChatWidthRatio() {
  const rawValue = window.localStorage.getItem(CHAT_WIDTH_STORAGE_KEY)
  if (!rawValue) return null

  const ratio = Number(rawValue)
  if (!Number.isFinite(ratio) || ratio <= 0 || ratio > CHAT_MAX_RATIO) {
    return null
  }

  return ratio
}

function App() {
  const { fetchPapers, selectedPaper } = usePaperStore()
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [chatCollapsed, setChatCollapsed] = useState(false)
  const [chatWidth, setChatWidth] = useState(CHAT_DEFAULT_WIDTH)
  const [isDragging, setIsDragging] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [themeMode, setThemeMode] = useState<ThemeMode>(() => getStoredThemeMode())
  const containerRef = useRef<HTMLDivElement>(null)

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
      if (!(e.metaKey || e.ctrlKey)) return
      if (e.key === 'b') {
        e.preventDefault()
        setSidebarCollapsed(prev => !prev)
      } else if (e.key === 'l') {
        e.preventDefault()
        setChatCollapsed(prev => !prev)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

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
      window.localStorage.setItem(CHAT_WIDTH_STORAGE_KEY, String(clampedWidth / containerRect.width))
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
      const storedRatio = getStoredChatWidthRatio()
      const targetWidth = storedRatio ? containerWidth * storedRatio : CHAT_DEFAULT_WIDTH
      const clampedWidth = clampChatWidth(targetWidth, containerWidth)

      setChatWidth(clampedWidth)

      if (containerWidth > 0) {
        window.localStorage.setItem(CHAT_WIDTH_STORAGE_KEY, String(clampedWidth / containerWidth))
      }
    }

    updateChatWidth()
    window.addEventListener('resize', updateChatWidth)
    return () => window.removeEventListener('resize', updateChatWidth)
  }, [])

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
    window.localStorage.setItem(THEME_MODE_STORAGE_KEY, nextThemeMode)
    applyThemeMode(nextThemeMode, window.matchMedia('(prefers-color-scheme: dark)').matches)
  }, [])

  return (
    <div ref={containerRef} className="h-screen flex bg-background">
      {/* 左侧：论文库（可折叠） */}
      <aside
        className="border-r border-border flex-shrink-0 overflow-hidden transition-all duration-200 ease-in-out"
        style={{ width: sidebarCollapsed ? 0 : 256 }}
      >
        <div className="w-64 h-full">
          <PaperLibrary onOpenSettings={() => setSettingsOpen(true)} />
        </div>
      </aside>

      {/* 折叠时的展开按钮 */}
      {sidebarCollapsed && (
        <button
          onClick={() => setSidebarCollapsed(false)}
          className="flex-shrink-0 w-8 flex items-center justify-center border-r border-border hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
          title="展开论文库"
        >
          <PanelLeftOpen className="w-4 h-4" />
        </button>
      )}

      {/* 展开时的折叠按钮（覆盖在侧边栏右上角） */}
      {!sidebarCollapsed && (
        <button
          onClick={() => setSidebarCollapsed(true)}
          className="absolute left-[228px] top-3 z-10 p-1.5 rounded-md hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
          title="收起论文库"
        >
          <PanelLeftClose className="w-4 h-4" />
        </button>
      )}

      {/* 中间：PDF 阅读器 */}
      <main className="flex-1 flex flex-col min-w-0">
        {selectedPaper ? (
          <PdfViewer paperId={selectedPaper.arxiv_id} />
        ) : (
          <div className="flex-1 flex items-center justify-center text-muted-foreground">
            <div className="text-center">
              <h2 className="text-xl font-medium mb-2">欢迎使用 iPaper</h2>
              <p>从左侧添加论文开始阅读</p>
            </div>
          </div>
        )}
      </main>

      {/* 右侧：讲解面板（可折叠、可拖拽调整宽度），Cursor 模式下隐藏 */}
      {selectedPaper && !cursorMode && (
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
                <ChatPanel paperId={selectedPaper.arxiv_id} onCollapse={() => setChatCollapsed(true)} />
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
    </div>
  )
}

export default App
