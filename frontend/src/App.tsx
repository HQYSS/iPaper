import { useEffect, useState, useCallback, useRef } from 'react'
import { PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { PaperLibrary } from './components/PaperLibrary'
import { PdfViewer } from './components/PdfViewer'
import { ChatPanel } from './components/ChatPanel'
import { usePaperStore } from './stores/paperStore'

const CHAT_MIN_WIDTH = 320
const CHAT_MAX_RATIO = 0.5
const CHAT_DEFAULT_WIDTH = 480

const cursorMode = new URLSearchParams(window.location.search).get('cursor') === '1'

function App() {
  const { fetchPapers, selectedPaper } = usePaperStore()
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [chatWidth, setChatWidth] = useState(CHAT_DEFAULT_WIDTH)
  const [isDragging, setIsDragging] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    fetchPapers()
  }, [fetchPapers])

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }, [])

  useEffect(() => {
    if (!isDragging) return

    const handleMouseMove = (e: MouseEvent) => {
      if (!containerRef.current) return
      const containerRect = containerRef.current.getBoundingClientRect()
      const maxWidth = containerRect.width * CHAT_MAX_RATIO
      const newWidth = containerRect.right - e.clientX
      setChatWidth(Math.max(CHAT_MIN_WIDTH, Math.min(maxWidth, newWidth)))
    }

    const handleMouseUp = () => setIsDragging(false)

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isDragging])

  return (
    <div ref={containerRef} className="h-screen flex bg-background">
      {/* 左侧：论文库（可折叠） */}
      <aside
        className="border-r border-border flex-shrink-0 overflow-hidden transition-all duration-200 ease-in-out"
        style={{ width: sidebarCollapsed ? 0 : 256 }}
      >
        <div className="w-64 h-full">
          <PaperLibrary />
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

      {/* 右侧：讲解面板（可拖拽调整宽度），Cursor 模式下隐藏 */}
      {selectedPaper && !cursorMode && (
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
            <ChatPanel paperId={selectedPaper.arxiv_id} />
          </aside>
        </>
      )}

      {/* 拖拽时禁止 PDF iframe 吞事件 */}
      {isDragging && (
        <div className="fixed inset-0 z-50 cursor-col-resize" />
      )}
    </div>
  )
}

export default App
