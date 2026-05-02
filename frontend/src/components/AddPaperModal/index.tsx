import { useEffect, useRef, useState } from 'react'
import { X, Plus, Loader2, FileUp, ExternalLink } from 'lucide-react'
import { usePaperStore } from '../../stores/paperStore'
import { useToastStore } from '../../stores/toastStore'
import { cn } from '../../lib/utils'

interface AddPaperModalProps {
  open: boolean
  onClose: () => void
}

export function AddPaperModal({ open, onClose }: AddPaperModalProps) {
  const addPaper = usePaperStore((s) => s.addPaper)
  const { addToast } = useToastStore()
  const inputRef = useRef<HTMLInputElement>(null)
  const [arxivInput, setArxivInput] = useState('')
  const [isAdding, setIsAdding] = useState(false)

  useEffect(() => {
    if (!open) return
    setArxivInput('')
    setIsAdding(false)
    // 等弹窗的 fade-in 起来再聚焦，避免某些浏览器把焦点抢走
    const timer = window.setTimeout(() => inputRef.current?.focus(), 50)
    return () => window.clearTimeout(timer)
  }, [open])

  useEffect(() => {
    if (!open) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [open, onClose])

  const handleSubmit = async () => {
    const value = arxivInput.trim()
    if (!value || isAdding) return

    setIsAdding(true)
    try {
      await addPaper(value)
      addToast('success', '已加入论文库，英文 PDF 正在后台下载…')
      onClose()
    } catch (error) {
      addToast('error', (error as Error).message || '添加论文失败')
    } finally {
      setIsAdding(false)
    }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center px-4 pt-[18vh]">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm animate-in fade-in duration-200"
        onClick={() => {
          if (!isAdding) onClose()
        }}
      />

      {/* Modal */}
      <div className="relative w-full max-w-xl animate-in zoom-in-95 fade-in duration-200">
        <div className="bg-white dark:bg-slate-900 rounded-2xl shadow-2xl border border-slate-200/60 dark:border-slate-700/60 overflow-hidden">
          {/* Header */}
          <div className="relative px-6 pt-6 pb-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-500 flex items-center justify-center shadow-lg shadow-indigo-500/20">
                <FileUp className="w-5 h-5 text-white" />
              </div>
              <div>
                <h2 className="text-lg font-semibold text-slate-800 dark:text-slate-100">添加论文</h2>
                <p className="text-xs text-slate-400 mt-0.5">输入 arXiv ID、arXiv URL 或 PDF URL，加入你的论文库</p>
              </div>
            </div>
            <button
              onClick={onClose}
              disabled={isAdding}
              className="absolute right-4 top-4 p-2 rounded-xl text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:text-slate-300 dark:hover:bg-slate-800 transition-all disabled:opacity-50"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Body */}
          <div className="px-6 pb-2 space-y-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                arXiv ID、arXiv URL 或 PDF URL
              </label>
              <input
                ref={inputRef}
                type="text"
                value={arxivInput}
                onChange={(e) => setArxivInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    handleSubmit()
                  }
                }}
                placeholder="如 1706.03762、arXiv URL 或 https://example.com/paper.pdf"
                disabled={isAdding}
                className="w-full px-4 py-3 text-sm rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 focus:outline-none focus:ring-2 focus:ring-indigo-500/40 focus:border-indigo-500 transition-all placeholder:text-slate-400 disabled:opacity-60"
              />
              <a
                href="https://arxiv.org"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 mt-2 text-xs text-indigo-500 hover:text-indigo-600 transition-colors"
              >
                去 arXiv 找论文
                <ExternalLink className="w-3 h-3" />
              </a>
            </div>

            <div className="px-3 py-2 rounded-lg bg-slate-50 dark:bg-slate-800/50 text-xs text-slate-500 dark:text-slate-400 leading-relaxed">
              支持 arXiv ID（如 <code className="font-mono text-slate-700 dark:text-slate-200">1706.03762</code>）、arXiv 论文页 URL 或普通 PDF URL；普通 PDF 不会自动生成中文翻译。
            </div>
          </div>

          {/* Footer */}
          <div className="px-6 py-4 mt-2 border-t border-slate-100 dark:border-slate-800 flex gap-3">
            <button
              onClick={onClose}
              disabled={isAdding}
              className="flex-1 px-4 py-2.5 text-sm font-medium rounded-xl border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800 transition-all disabled:opacity-50"
            >
              取消
            </button>
            <button
              onClick={handleSubmit}
              disabled={!arxivInput.trim() || isAdding}
              className={cn(
                'flex-1 px-4 py-2.5 text-sm font-medium rounded-xl flex items-center justify-center gap-2 transition-all',
                'bg-gradient-to-r from-indigo-500 to-purple-500 text-white hover:from-indigo-600 hover:to-purple-600 shadow-sm shadow-indigo-500/20',
                (!arxivInput.trim() || isAdding) && 'opacity-50 cursor-not-allowed'
              )}
            >
              {isAdding ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  添加中…
                </>
              ) : (
                <>
                  <Plus className="w-4 h-4" />
                  添加
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
