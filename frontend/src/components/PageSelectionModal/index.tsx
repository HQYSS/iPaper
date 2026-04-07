import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, BookOpen, Plus, X } from 'lucide-react'
import type { PageRangeInput } from '../../services/api'
import type { PendingPageSelectionRequest } from '../../stores/chatStore'
import { cn } from '../../lib/utils'

interface PageSelectionModalProps {
  request: PendingPageSelectionRequest | null
  onClose: () => void
  onConfirm: (pageSelections: Array<{ paper_id: string; ranges: PageRangeInput[] }>) => Promise<void> | void
}

interface DraftSelection {
  paperId: string
  title: string
  totalPages: number
  ranges: PageRangeInput[]
  input: string
  error: string | null
}

function parseRangeInput(value: string): PageRangeInput | null {
  const normalized = value.trim()
  const match = normalized.match(/^(\d+)(?:\s*-\s*(\d+))?$/)
  if (!match) return null

  const start = Number(match[1])
  const end = Number(match[2] || match[1])
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < 1 || end < 1 || start > end) {
    return null
  }
  return { start, end }
}

function formatRange(range: PageRangeInput): string {
  return range.start === range.end ? String(range.start) : `${range.start}-${range.end}`
}

export function PageSelectionModal({ request, onClose, onConfirm }: PageSelectionModalProps) {
  const [drafts, setDrafts] = useState<DraftSelection[]>([])
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!request) {
      setDrafts([])
      setSubmitting(false)
      return
    }

    setDrafts(
      request.requirements.map((item) => ({
        paperId: item.paper_id,
        title: item.title,
        totalPages: item.total_pages,
        ranges: item.selected_ranges ? [...item.selected_ranges] : [],
        input: '',
        error: null,
      }))
    )
    setSubmitting(false)
  }, [request])

  const allValid = useMemo(
    () => drafts.length > 0 && drafts.every((item) => item.ranges.length > 0 && !item.error),
    [drafts]
  )

  if (!request) return null

  const updateDraft = (paperId: string, updater: (draft: DraftSelection) => DraftSelection) => {
    setDrafts((prev) => prev.map((item) => (item.paperId === paperId ? updater(item) : item)))
  }

  const handleAddRange = (paperId: string) => {
    const current = drafts.find((item) => item.paperId === paperId)
    if (!current) return

    const parsed = parseRangeInput(current.input)
    if (!parsed) {
      updateDraft(paperId, (item) => ({ ...item, error: '请输入单页或范围，例如 12 或 12-18' }))
      return
    }
    if (parsed.end > current.totalPages) {
      updateDraft(paperId, (item) => ({
        ...item,
        error: `页码超出范围，这篇论文总共 ${current.totalPages} 页`,
      }))
      return
    }

    updateDraft(paperId, (item) => ({
      ...item,
      ranges: [...item.ranges, parsed],
      input: '',
      error: null,
    }))
  }

  const handleSubmit = async () => {
    if (!allValid || submitting) return
    setSubmitting(true)
    try {
      await onConfirm(
        drafts.map((item) => ({
          paper_id: item.paperId,
          ranges: item.ranges,
        }))
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center">
      <div
        className="absolute inset-0 bg-black/45 backdrop-blur-sm animate-in fade-in duration-200"
        onClick={() => {
          if (!submitting) onClose()
        }}
      />

      <div className="relative w-full max-w-3xl mx-4 animate-in zoom-in-95 fade-in duration-200">
        <div className="bg-white dark:bg-slate-900 rounded-2xl shadow-2xl border border-slate-200/70 dark:border-slate-700/70 overflow-hidden">
          <div className="px-6 pt-6 pb-4 border-b border-slate-200 dark:border-slate-700">
            <div className="flex items-start gap-3">
              <div className="w-10 h-10 rounded-xl bg-amber-500/10 text-amber-600 dark:text-amber-400 flex items-center justify-center">
                <AlertTriangle className="w-5 h-5" />
              </div>
              <div className="flex-1 min-w-0">
                <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">选择要保留的 PDF 页码</h2>
                <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
                  这些论文转成图像后仍超过 20MB。请只保留和当前问题最相关的页面，每输入一段后按回车加入列表。
                </p>
                <p className="mt-2 text-sm text-amber-700 dark:text-amber-300">{request.errorMessage}</p>
              </div>
              <button
                onClick={onClose}
                disabled={submitting}
                className="p-2 rounded-xl text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:text-slate-200 dark:hover:bg-slate-800 transition-colors disabled:opacity-50"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
          </div>

          <div className="px-6 py-5 max-h-[70vh] overflow-y-auto space-y-4">
            {drafts.map((item) => (
              <div key={item.paperId} className="rounded-2xl border border-slate-200 dark:border-slate-700 bg-slate-50/70 dark:bg-slate-950/30 p-4">
                <div className="flex items-start gap-3">
                  <div className="w-9 h-9 rounded-xl bg-sky-500/10 text-sky-600 dark:text-sky-400 flex items-center justify-center flex-shrink-0">
                    <BookOpen className="w-4 h-4" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium text-slate-900 dark:text-slate-100">{item.title}</div>
                    <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                      `{item.paperId}` · 共 {item.totalPages} 页
                    </div>
                  </div>
                </div>

                <div className="mt-4 flex gap-2">
                  <input
                    value={item.input}
                    onChange={(e) => updateDraft(item.paperId, (draft) => ({ ...draft, input: e.target.value, error: null }))}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault()
                        handleAddRange(item.paperId)
                      }
                    }}
                    placeholder="输入 12 或 12-18，按回车添加"
                    className="flex-1 px-3 py-2 text-sm rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 focus:outline-none focus:ring-2 focus:ring-sky-500"
                    disabled={submitting}
                  />
                  <button
                    onClick={() => handleAddRange(item.paperId)}
                    disabled={submitting || !item.input.trim()}
                    className="px-3 py-2 rounded-xl bg-sky-600 text-white hover:bg-sky-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-1.5"
                  >
                    <Plus className="w-4 h-4" />
                    添加
                  </button>
                </div>

                <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                  支持单页和连续范围。多段范围请逐条添加，不需要用逗号拼接。
                </div>

                {item.error && (
                  <div className="mt-3 text-sm text-red-600 dark:text-red-400">{item.error}</div>
                )}

                <div className={cn('mt-4 flex flex-wrap gap-2', item.ranges.length === 0 && 'hidden')}>
                  {item.ranges.map((range, index) => (
                    <div
                      key={`${range.start}-${range.end}-${index}`}
                      className="inline-flex items-center gap-2 rounded-full bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900 px-3 py-1.5 text-sm"
                    >
                      <span>{formatRange(range)}</span>
                      <button
                        onClick={() => {
                          updateDraft(item.paperId, (draft) => ({
                            ...draft,
                            ranges: draft.ranges.filter((_, rangeIndex) => rangeIndex !== index),
                          }))
                        }}
                        disabled={submitting}
                        className="opacity-70 hover:opacity-100 transition-opacity"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  ))}
                </div>

                {item.ranges.length === 0 && (
                  <div className="mt-4 rounded-xl border border-dashed border-slate-300 dark:border-slate-700 px-3 py-4 text-sm text-slate-500 dark:text-slate-400">
                    还没有选择任何页码范围
                  </div>
                )}
              </div>
            ))}
          </div>

          <div className="px-6 py-4 border-t border-slate-200 dark:border-slate-700 flex items-center justify-between bg-slate-50/80 dark:bg-slate-950/40">
            <div className="text-sm text-slate-500 dark:text-slate-400">
              建议优先保留摘要、方法、实验和你当前关心的问题对应的页面。
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={onClose}
                disabled={submitting}
                className="px-4 py-2 rounded-xl border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors disabled:opacity-50"
              >
                取消
              </button>
              <button
                onClick={handleSubmit}
                disabled={!allValid || submitting}
                className="px-4 py-2 rounded-xl bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {submitting ? '正在发送...' : '确认并发送'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
