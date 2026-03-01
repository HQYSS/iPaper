import { useState } from 'react'
import { Plus, Trash2, FileText, Loader2, Clock, User } from 'lucide-react'
import { usePaperStore } from '../../stores/paperStore'
import { useToastStore } from '../../stores/toastStore'
import { cn } from '../../lib/utils'

export function PaperLibrary() {
  const { papers, selectedPaper, isLoading, addPaper, deletePaper, selectPaper } = usePaperStore()
  const { addToast } = useToastStore()
  const [arxivInput, setArxivInput] = useState('')
  const [isAdding, setIsAdding] = useState(false)
  const [showInput, setShowInput] = useState(false)

  const handleAddPaper = async () => {
    if (!arxivInput.trim()) return

    setIsAdding(true)
    try {
      await addPaper(arxivInput.trim())
      setArxivInput('')
      setShowInput(false)
      addToast('success', '论文添加成功！')
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

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr)
    return date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
  }

  return (
    <div className="h-full flex flex-col">
      {/* 标题栏 */}
      <div className="p-4 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between">
        <div>
          <h1 className="font-semibold text-lg text-slate-800 dark:text-slate-100">论文库</h1>
          <p className="text-xs text-slate-400 mt-0.5">{papers.length} 篇论文</p>
        </div>
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
      </div>

      {/* 添加论文输入框 */}
      {showInput && (
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

      {/* 论文列表 */}
      <div className="flex-1 overflow-y-auto">
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
            {papers.map((paper) => (
              <li
                key={paper.arxiv_id}
                className={cn(
                  'group relative cursor-pointer border-b border-slate-100 dark:border-slate-800 last:border-0',
                  selectedPaper?.arxiv_id === paper.arxiv_id && 'bg-indigo-50 dark:bg-indigo-950/30'
                )}
              >
                <button
                  className="w-full text-left p-4 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
                  onClick={() => selectPaper(paper)}
                >
                  <h3 className="font-medium text-sm text-slate-800 dark:text-slate-100 line-clamp-2 pr-8 leading-relaxed">
                    {paper.title}
                  </h3>
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
                </button>
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
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

