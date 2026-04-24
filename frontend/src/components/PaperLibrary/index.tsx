import { useState, useEffect, useRef } from 'react'
import { Plus, Trash2, FileText, Loader2, Clock, User, Settings, GitCompareArrows, Check, X, AlertTriangle, RotateCw } from 'lucide-react'
import { usePaperStore } from '../../stores/paperStore'
import { useChatStore } from '../../stores/chatStore'
import { useToastStore } from '../../stores/toastStore'
import { cn } from '../../lib/utils'
import * as api from '../../services/api'

interface PaperLibraryProps {
  onOpenSettings?: () => void
}

interface PaperContextMenuState {
  paperId: string
  paperTitle: string
  x: number
  y: number
}

const CONTEXT_MENU_WIDTH = 160
const CONTEXT_MENU_HEIGHT = 104

export function PaperLibrary({ onOpenSettings }: PaperLibraryProps) {
  const {
    papers, selectedPaper, isLoading, addPaper, deletePaper, selectPaper,
    crossPaper, enterCrossPaperMode, exitCrossPaperMode, toggleCrossPaperSelection,
    startCrossChat, enterCrossChatSession,
  } = usePaperStore()
  const { initCrossPaperSession, loadCrossPaperSessions, exitCrossPaperChat } = useChatStore()
  const { addToast } = useToastStore()
  const [arxivInput, setArxivInput] = useState('')
  const [isAdding, setIsAdding] = useState(false)
  const [showInput, setShowInput] = useState(false)
  const [crossPaperSessions, setCrossPaperSessions] = useState<api.CrossPaperSessionMeta[]>([])
  const [contextMenu, setContextMenu] = useState<PaperContextMenuState | null>(null)
  const paperListRef = useRef<HTMLDivElement>(null)

  const isSelectingMode = crossPaper.isSelecting
  const isInCrossChat = !!crossPaper.activeCrossPaperSession

  useEffect(() => {
    if (isSelectingMode) {
      api.listCrossPaperSessions().then((list) => {
        setCrossPaperSessions(list.sessions)
      }).catch(() => {})
    }
  }, [isSelectingMode])

  useEffect(() => {
    if (!contextMenu) return

    const handleClose = () => setContextMenu(null)
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setContextMenu(null)
      }
    }
    const paperListElement = paperListRef.current

    document.addEventListener('click', handleClose)
    window.addEventListener('resize', handleClose)
    window.addEventListener('keydown', handleKeyDown)
    paperListElement?.addEventListener('scroll', handleClose)

    return () => {
      document.removeEventListener('click', handleClose)
      window.removeEventListener('resize', handleClose)
      window.removeEventListener('keydown', handleKeyDown)
      paperListElement?.removeEventListener('scroll', handleClose)
    }
  }, [contextMenu])

  const handleAddPaper = async () => {
    if (!arxivInput.trim()) return

    setIsAdding(true)
    try {
      await addPaper(arxivInput.trim())
      setArxivInput('')
      setShowInput(false)
      addToast('success', '已加入论文库，英文 PDF 正在后台下载…')
    } catch (error) {
      addToast('error', (error as Error).message || '添加论文失败')
    } finally {
      setIsAdding(false)
    }
  }

  const handleDeletePaper = async (paperId: string) => {
    try {
      await deletePaper(paperId)
      addToast('success', '论文已删除')
    } catch (error) {
      addToast('error', (error as Error).message || '删除论文失败')
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleAddPaper()
    } else if (e.key === 'Escape') {
      setShowInput(false)
      setArxivInput('')
    }
  }

  const handleStartCrossChat = async () => {
    if (crossPaper.selectedPaperIds.length < 2) return

    try {
      await startCrossChat()
      const { crossPaper: cp } = usePaperStore.getState()
      if (cp.activeCrossPaperSession) {
        await initCrossPaperSession(cp.activeCrossPaperSession)
      }
    } catch (error) {
      addToast('error', (error as Error).message || '创建串讲失败')
    }
  }

  const handleOpenHistorySession = async (session: api.CrossPaperSessionMeta) => {
    enterCrossChatSession(session)
    loadCrossPaperSessions()
  }

  const handleDeleteCrossPaperSession = async (sessionId: string) => {
    try {
      await api.deleteCrossPaperSession(sessionId)
      setCrossPaperSessions((prev) => prev.filter((s) => s.id !== sessionId))
      addToast('success', '串讲会话已删除')
    } catch (error) {
      addToast('error', (error as Error).message || '删除失败')
    }
  }

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr)
    return date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
  }

  const getPaperTitle = (paperId: string) => {
    const paper = papers.find((p) => p.arxiv_id === paperId)
    if (!paper) return paperId
    return paper.title.length > 30 ? paper.title.slice(0, 30) + '…' : paper.title
  }

  const handlePaperContextMenu = (event: React.MouseEvent, paperId: string, paperTitle: string) => {
    if (isSelectingMode) return

    event.preventDefault()
    event.stopPropagation()

    const x = Math.min(event.clientX, window.innerWidth - CONTEXT_MENU_WIDTH - 8)
    const y = Math.min(event.clientY, window.innerHeight - CONTEXT_MENU_HEIGHT - 8)

    setContextMenu({
      paperId,
      paperTitle,
      x: Math.max(8, x),
      y: Math.max(8, y),
    })
  }

  const handleCopyPaperTitle = async () => {
    if (!contextMenu) return

    try {
      await navigator.clipboard.writeText(contextMenu.paperTitle)
      addToast('success', '已复制文章名')
    } catch {
      addToast('error', '复制失败，请检查剪贴板权限')
    } finally {
      setContextMenu(null)
    }
  }

  const handleCopyPaperId = async () => {
    if (!contextMenu) return

    try {
      await navigator.clipboard.writeText(contextMenu.paperId)
      addToast('success', '已复制 arXiv ID')
    } catch {
      addToast('error', '复制失败，请检查剪贴板权限')
    } finally {
      setContextMenu(null)
    }
  }

  return (
    <div className="h-full flex flex-col relative">
      {/* 标题栏 */}
      <div className="p-4 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between">
        <div>
          <h1 className="font-semibold text-lg text-slate-800 dark:text-slate-100">
            {isSelectingMode ? '串讲模式' : isInCrossChat ? '串讲中' : '论文库'}
          </h1>
          <p className="text-xs text-slate-400 mt-0.5">
            {isSelectingMode
              ? `已选 ${crossPaper.selectedPaperIds.length} 篇（2~5 篇）`
              : isInCrossChat
                ? `${crossPaper.activeCrossPaperSession!.paper_ids.length} 篇论文`
                : `${papers.length} 篇论文`}
          </p>
        </div>
        {isSelectingMode || isInCrossChat ? (
          <button
            onClick={() => {
              if (isInCrossChat) {
                exitCrossPaperChat()
                exitCrossPaperMode()
              } else {
                exitCrossPaperMode()
              }
            }}
            className="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-400 transition-all"
            title={isInCrossChat ? '退出串讲' : '退出串讲模式'}
          >
            <X className="w-5 h-5" />
          </button>
        ) : (
          <button
            onClick={() => setShowInput(!showInput)}
            className={cn(
              "p-2 rounded-lg transition-all",
              showInput
                ? "bg-indigo-100 text-indigo-600 dark:bg-indigo-900/50 dark:text-indigo-400"
                : "hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-400"
            )}
            title="添加论文"
          >
            <Plus className="w-5 h-5" />
          </button>
        )}
      </div>

      {/* 添加论文输入框 */}
      {showInput && !isSelectingMode && (
        <div className="p-4 border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50">
          <input
            type="text"
            value={arxivInput}
            onChange={(e) => setArxivInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入 arXiv ID，如 1706.03762"
            className="w-full px-3 py-2.5 text-sm rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all"
            autoFocus
            disabled={isAdding}
          />
          <p className="text-xs text-slate-400 mt-2">支持 arXiv ID 或完整 URL</p>
          <div className="flex gap-2 mt-3">
            <button
              onClick={handleAddPaper}
              disabled={isAdding || !arxivInput.trim()}
              className="flex-1 px-4 py-2 text-sm font-medium bg-gradient-to-r from-indigo-500 to-purple-500 text-white rounded-lg hover:from-indigo-600 hover:to-purple-600 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 transition-all shadow-sm"
            >
              {isAdding ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  下载中...
                </>
              ) : (
                '添加论文'
              )}
            </button>
            <button
              onClick={() => {
                setShowInput(false)
                setArxivInput('')
              }}
              className="px-4 py-2 text-sm text-slate-600 dark:text-slate-400 border border-slate-200 dark:border-slate-600 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-all"
            >
              取消
            </button>
          </div>
        </div>
      )}

      {/* 历史串讲会话（串讲模式下显示） */}
      {isSelectingMode && crossPaperSessions.length > 0 && (
        <div className="border-b border-slate-200 dark:border-slate-700">
          <div className="px-4 pt-3 pb-1">
            <p className="text-xs font-medium text-slate-500 dark:text-slate-400">历史串讲</p>
          </div>
          <ul className="max-h-40 overflow-y-auto">
            {crossPaperSessions.map((session) => (
              <li
                key={session.id}
                className="group relative cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
              >
                <button
                  className="w-full text-left px-4 py-2.5"
                  onClick={() => handleOpenHistorySession(session)}
                >
                  <p className="text-sm text-slate-700 dark:text-slate-200 truncate">
                    {session.paper_ids.map((id) => getPaperTitle(id)).join(' × ')}
                  </p>
                  <p className="text-xs text-slate-400 mt-0.5">
                    {session.paper_ids.length} 篇 · {formatDate(session.updated_at)}
                  </p>
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    if (confirm('确定删除这个串讲会话吗？')) {
                      handleDeleteCrossPaperSession(session.id)
                    }
                  }}
                  className="absolute right-3 top-3 p-1 rounded-md opacity-0 group-hover:opacity-100 text-slate-400 hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-950/50 transition-all"
                  title="删除串讲"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </li>
            ))}
          </ul>
          {crossPaperSessions.length > 0 && (
            <div className="px-4 pb-2 pt-1">
              <div className="border-t border-slate-100 dark:border-slate-800" />
              <p className="text-xs text-slate-400 mt-2 mb-1">选择论文开始新串讲 ↓</p>
            </div>
          )}
        </div>
      )}

      {/* 论文列表 */}
      <div ref={paperListRef} className="flex-1 overflow-y-auto">
        {isLoading && papers.length === 0 ? (
          <div className="flex items-center justify-center h-32 text-slate-400">
            <Loader2 className="w-5 h-5 animate-spin mr-2" />
            加载中...
          </div>
        ) : papers.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-48 text-slate-400 text-sm px-6">
            <div className="w-16 h-16 rounded-full bg-slate-100 dark:bg-slate-800 flex items-center justify-center mb-4">
              <FileText className="w-8 h-8 opacity-50" />
            </div>
            <p className="font-medium">暂无论文</p>
            <p className="text-xs mt-1 text-center">点击上方 + 按钮添加 arXiv 论文</p>
          </div>
        ) : (
          <ul>
            {papers.map((paper) => {
              const isChecked = crossPaper.selectedPaperIds.includes(paper.arxiv_id)
              const downloadStatus = paper.download_status ?? 'ready'
              const isDownloading = downloadStatus === 'downloading'
              const isFailed = downloadStatus === 'failed'
              const notReady = isDownloading || isFailed
              return (
                <li
                  key={paper.arxiv_id}
                  className={cn(
                    'group relative cursor-pointer border-b border-slate-100 dark:border-slate-800 last:border-0',
                    !isSelectingMode && selectedPaper?.arxiv_id === paper.arxiv_id && 'bg-indigo-50 dark:bg-indigo-950/30',
                    isSelectingMode && isChecked && 'bg-purple-50 dark:bg-purple-950/20',
                    isFailed && 'bg-red-50/40 dark:bg-red-950/10'
                  )}
                  onContextMenu={(event) => handlePaperContextMenu(event, paper.arxiv_id, paper.title)}
                >
                  <button
                    className="w-full text-left p-4 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors flex items-start gap-3"
                    onClick={() => {
                      if (isSelectingMode) {
                        if (notReady) {
                          addToast('error', isDownloading ? '论文还在下载中，下好才能加入串讲' : '论文下载失败，请先重试')
                          return
                        }
                        toggleCrossPaperSelection(paper.arxiv_id)
                      } else {
                        selectPaper(paper)
                      }
                    }}
                  >
                    {/* 多选模式下的 checkbox */}
                    {isSelectingMode && (
                      <div className={cn(
                        'mt-0.5 w-5 h-5 rounded border-2 flex-shrink-0 flex items-center justify-center transition-all',
                        notReady && 'opacity-40',
                        isChecked
                          ? 'bg-purple-500 border-purple-500 text-white'
                          : 'border-slate-300 dark:border-slate-600'
                      )}>
                        {isChecked && <Check className="w-3.5 h-3.5" />}
                      </div>
                    )}

                    <div className="flex-1 min-w-0">
                      <h3 className={cn(
                        'font-medium text-sm line-clamp-2 pr-8 leading-relaxed',
                        isFailed
                          ? 'text-slate-500 dark:text-slate-400'
                          : 'text-slate-800 dark:text-slate-100'
                      )}>
                        {paper.title}
                      </h3>

                      {/* 下载状态标识 */}
                      {isDownloading && (
                        <div className="flex items-center gap-1.5 mt-1.5 text-xs text-indigo-600 dark:text-indigo-400">
                          <Loader2 className="w-3 h-3 animate-spin" />
                          <span>正在下载英文 PDF…</span>
                        </div>
                      )}
                      {isFailed && (
                        <div
                          className="flex items-center gap-1.5 mt-1.5 text-xs text-red-600 dark:text-red-400"
                          title={paper.download_error || undefined}
                        >
                          <AlertTriangle className="w-3 h-3" />
                          <span className="truncate">下载失败{paper.download_error ? `：${paper.download_error}` : ''}</span>
                        </div>
                      )}

                      <div className="flex items-center gap-3 mt-2 text-xs text-slate-400">
                        <span className="font-mono bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded">
                          {paper.arxiv_id}
                        </span>
                        {paper.authors && paper.authors.length > 0 && (
                          <span className="flex items-center gap-1 truncate">
                            <User className="w-3 h-3" />
                            {paper.authors[0]}{paper.authors.length > 1 && ` +${paper.authors.length - 1}`}
                          </span>
                        )}
                        <span className="flex items-center gap-1">
                          <Clock className="w-3 h-3" />
                          {formatDate(paper.download_time)}
                        </span>
                      </div>
                    </div>
                  </button>

                  {/* 失败状态下的重试按钮 */}
                  {!isSelectingMode && isFailed && (
                    <button
                      onClick={async (e) => {
                        e.stopPropagation()
                        try {
                          await addPaper(paper.arxiv_id)
                          addToast('success', '已重新开始下载')
                        } catch (err) {
                          addToast('error', (err as Error).message || '重试失败')
                        }
                      }}
                      className="absolute right-11 top-4 p-1.5 rounded-md text-red-500 hover:bg-red-100 dark:hover:bg-red-950/40 transition-all"
                      title="重新下载"
                    >
                      <RotateCw className="w-4 h-4" />
                    </button>
                  )}

                  {!isSelectingMode && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        if (confirm('确定删除这篇论文吗？')) {
                          handleDeletePaper(paper.arxiv_id)
                        }
                      }}
                      className="absolute right-3 top-4 p-1.5 rounded-md opacity-0 group-hover:opacity-100 text-slate-400 hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-950/50 transition-all"
                      title="删除论文"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </div>

      {/* 串讲模式操作栏 */}
      {isSelectingMode && (
        <div className="border-t border-slate-200 dark:border-slate-700 p-3">
          <button
            onClick={handleStartCrossChat}
            disabled={crossPaper.selectedPaperIds.length < 2 || isLoading}
            className="w-full px-4 py-2.5 text-sm font-medium bg-gradient-to-r from-purple-500 to-indigo-500 text-white rounded-lg hover:from-purple-600 hover:to-indigo-600 disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center gap-2 transition-all shadow-sm"
          >
            {isLoading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <GitCompareArrows className="w-4 h-4" />
            )}
            开始串讲 ({crossPaper.selectedPaperIds.length} 篇)
          </button>
        </div>
      )}

      {/* 底部按钮（正常模式） */}
      {!isSelectingMode && (
        <div className="border-t border-slate-200 dark:border-slate-700 p-3 space-y-1">
          <button
            onClick={enterCrossPaperMode}
            className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm text-purple-600 dark:text-purple-400 hover:bg-purple-50 dark:hover:bg-purple-950/30 transition-all"
          >
            <GitCompareArrows className="w-4 h-4" />
            串讲模式
          </button>
          <button
            onClick={onOpenSettings}
            className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 hover:text-slate-700 dark:hover:text-slate-300 transition-all"
          >
            <Settings className="w-4 h-4" />
            设置
          </button>
        </div>
      )}

      {contextMenu && (
        <div
          className="fixed z-50 min-w-[140px] rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 shadow-lg py-1"
          style={{
            left: `${contextMenu.x}px`,
            top: `${contextMenu.y}px`,
          }}
          onClick={(event) => event.stopPropagation()}
        >
          <button
            className="w-full px-3 py-2 text-left text-sm text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            onClick={handleCopyPaperTitle}
          >
            复制文章名
          </button>
          <button
            className="w-full px-3 py-2 text-left text-sm text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            onClick={handleCopyPaperId}
          >
            复制 arXiv ID
          </button>
          <div className="px-3 pb-1 text-[11px] text-slate-400 truncate">
            {contextMenu.paperId}
          </div>
        </div>
      )}
    </div>
  )
}
