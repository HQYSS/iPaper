import { useEffect, useMemo, useRef, useState } from 'react'
import { FileText, Search } from 'lucide-react'
import { cn } from '../../lib/utils'
import type { PaperListItem } from '../../services/api'

interface PaperQuickSwitcherProps {
  open: boolean
  papers: PaperListItem[]
  title: string
  onClose: () => void
  onSelect: (paper: PaperListItem) => void
}

function normalizeKeyword(value: string) {
  return value.trim().toLowerCase()
}

function buildSearchText(paper: PaperListItem) {
  return [
    paper.title,
    paper.title_zh ?? '',
    paper.arxiv_id,
    paper.authors.join(' '),
  ].join(' ').toLowerCase()
}

export function PaperQuickSwitcher({
  open,
  papers,
  title,
  onClose,
  onSelect,
}: PaperQuickSwitcherProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const activeItemRef = useRef<HTMLButtonElement | null>(null)
  const isComposingRef = useRef(false)
  const [query, setQuery] = useState('')
  const [activeIndex, setActiveIndex] = useState(0)

  const filteredPapers = useMemo(() => {
    const keyword = normalizeKeyword(query)
    if (!keyword) return papers
    return papers.filter((paper) => buildSearchText(paper).includes(keyword))
  }, [papers, query])

  useEffect(() => {
    if (!open) return

    setQuery('')
    setActiveIndex(0)
  }, [open, papers])

  useEffect(() => {
    if (!open) return
    inputRef.current?.focus()
  }, [open])

  useEffect(() => {
    if (!open) return
    if (filteredPapers.length === 0) {
      setActiveIndex(0)
      return
    }
    setActiveIndex((prev) => Math.min(prev, filteredPapers.length - 1))
  }, [open, filteredPapers])

  useEffect(() => {
    if (!open) return
    activeItemRef.current?.scrollIntoView({ block: 'nearest' })
  }, [open, activeIndex])

  useEffect(() => {
    if (!open) return

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
        return
      }

      if (filteredPapers.length === 0) return

      if (event.key === 'ArrowDown') {
        event.preventDefault()
        setActiveIndex((prev) => (prev + 1) % filteredPapers.length)
      } else if (event.key === 'ArrowUp') {
        event.preventDefault()
        setActiveIndex((prev) => (prev - 1 + filteredPapers.length) % filteredPapers.length)
      } else if (event.key === 'Enter') {
        if (event.isComposing || isComposingRef.current || event.keyCode === 229) {
          return
        }
        event.preventDefault()
        onSelect(filteredPapers[activeIndex])
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [open, filteredPapers, activeIndex, onClose, onSelect])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center px-4 pt-[12vh]">
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm"
        onClick={onClose}
      />

      <div className="relative w-full max-w-2xl overflow-hidden rounded-2xl border border-slate-200/70 bg-white shadow-2xl dark:border-slate-700/70 dark:bg-slate-900">
        <div className="border-b border-slate-200 dark:border-slate-800">
          <div className="flex items-center gap-3 px-4 py-3">
            <Search className="h-4 w-4 flex-shrink-0 text-slate-400" />
            <input
              ref={inputRef}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onCompositionStart={() => {
                isComposingRef.current = true
              }}
              onCompositionEnd={() => {
                isComposingRef.current = false
              }}
              placeholder={title}
              className="w-full bg-transparent text-sm text-slate-800 outline-none placeholder:text-slate-400 dark:text-slate-100"
            />
            <span className="rounded-md border border-slate-200 px-2 py-1 text-[11px] text-slate-400 dark:border-slate-700">
              Esc
            </span>
          </div>
        </div>

        <div className="max-h-[420px] overflow-y-auto py-2">
          {filteredPapers.length > 0 ? (
            filteredPapers.map((paper, index) => {
              const isActive = index === activeIndex
              const firstAuthor = paper.authors[0]

              return (
                <button
                  key={paper.arxiv_id}
                  ref={isActive ? activeItemRef : null}
                  onClick={() => onSelect(paper)}
                  className={cn(
                    'flex w-full items-start gap-3 px-4 py-3 text-left transition-colors',
                    isActive
                      ? 'bg-indigo-50 dark:bg-indigo-950/30'
                      : 'hover:bg-slate-50 dark:hover:bg-slate-800/60'
                  )}
                >
                  <div className={cn(
                    'mt-0.5 rounded-lg p-2',
                    isActive
                      ? 'bg-indigo-100 text-indigo-600 dark:bg-indigo-900/50 dark:text-indigo-300'
                      : 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400'
                  )}>
                    <FileText className="h-4 w-4" />
                  </div>

                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-slate-800 dark:text-slate-100">
                      {paper.title}
                    </p>
                    <p className="mt-1 truncate text-xs text-slate-500 dark:text-slate-400">
                      {paper.arxiv_id}
                      {firstAuthor ? ` · ${firstAuthor}${paper.authors.length > 1 ? ` +${paper.authors.length - 1}` : ''}` : ''}
                    </p>
                  </div>
                </button>
              )
            })
          ) : (
            <div className="px-4 py-10 text-center text-sm text-slate-500 dark:text-slate-400">
              {query ? '没有匹配的论文' : '没有可切换的其他论文'}
            </div>
          )}
        </div>

        <div className="flex items-center justify-between border-t border-slate-200 px-4 py-2 text-[11px] text-slate-400 dark:border-slate-800">
          <span>按标题、arXiv ID 或作者搜索</span>
          <span>↑↓ 选择，Enter 打开</span>
        </div>
      </div>
    </div>
  )
}
