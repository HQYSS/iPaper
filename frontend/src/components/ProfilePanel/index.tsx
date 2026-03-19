import { useState, useRef, useEffect, useCallback } from 'react'
import { Send, Square, X, Check, XCircle, Loader2, ChevronDown, ChevronRight } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import { useProfileStore } from '../../stores/profileStore'

interface ProfilePanelProps {
  onClose: () => void
}

export function ProfilePanel({ onClose }: ProfilePanelProps) {
  const {
    evolutionMessages,
    isStreaming,
    error,
    editPlan,
    profileContent,
    isLoadingProfile,
    sendMessage,
    stopStreaming,
    applyEditPlan,
    rejectEditPlan,
    closeEvolution,
    clearError,
  } = useProfileStore()

  const [input, setInput] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const [editPlanExpanded, setEditPlanExpanded] = useState(true)
  const [isApplying, setIsApplying] = useState(false)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [evolutionMessages])

  useEffect(() => {
    if (!isStreaming && textareaRef.current) {
      textareaRef.current.focus()
    }
  }, [isStreaming])

  const handleSend = useCallback(() => {
    const trimmed = input.trim()
    if (!trimmed || isStreaming) return
    setInput('')
    sendMessage(trimmed)
  }, [input, isStreaming, sendMessage])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }, [handleSend])

  const handleClose = useCallback(() => {
    closeEvolution()
    onClose()
  }, [closeEvolution, onClose])

  const handleApply = useCallback(async () => {
    setIsApplying(true)
    await applyEditPlan()
    setIsApplying(false)
  }, [applyEditPlan])

  return (
    <div className="h-full flex bg-background">
      {/* Left: Profile Content */}
      <div className="w-1/2 flex flex-col border-r border-border min-w-0">
        <div className="flex items-center justify-between px-4 py-3 border-b border-border flex-shrink-0">
          <h2 className="text-sm font-semibold text-foreground">当前画像</h2>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {isLoadingProfile ? (
            <div className="flex items-center justify-center h-32 text-muted-foreground">
              <Loader2 className="w-4 h-4 animate-spin mr-2" />
              加载中...
            </div>
          ) : profileContent ? (
            <div className="prose prose-sm dark:prose-invert max-w-none
              [&>*:first-child]:mt-0
              [&_table]:text-xs [&_table]:w-full
              [&_th]:px-2 [&_th]:py-1.5 [&_th]:text-left [&_th]:font-medium [&_th]:border-b [&_th]:border-border
              [&_td]:px-2 [&_td]:py-1.5 [&_td]:border-b [&_td]:border-border/50
              [&_h2]:text-base [&_h2]:mt-6 [&_h2]:mb-2
              [&_h3]:text-sm [&_h3]:mt-4 [&_h3]:mb-1.5
            ">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {profileContent}
              </ReactMarkdown>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">画像文件不存在</p>
          )}
        </div>
      </div>

      {/* Right: Evolution Chat */}
      <div className="w-1/2 flex flex-col min-w-0">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-border flex-shrink-0">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold text-foreground">进化 Agent</h2>
            {isStreaming && (
              <Loader2 className="w-3.5 h-3.5 animate-spin text-muted-foreground" />
            )}
          </div>
          <button
            onClick={handleClose}
            className="p-1.5 rounded-md hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
            title="关闭进化面板"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
          {evolutionMessages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div
                className={`max-w-[90%] rounded-lg px-3.5 py-2.5 text-sm ${
                  msg.role === 'user'
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-muted text-foreground'
                }`}
              >
                {msg.role === 'assistant' ? (
                  <div className="prose prose-sm dark:prose-invert max-w-none [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm, remarkMath]}
                      rehypePlugins={[rehypeKatex]}
                    >
                      {msg.content || '...'}
                    </ReactMarkdown>
                  </div>
                ) : (
                  <p className="whitespace-pre-wrap">{msg.content}</p>
                )}
              </div>
            </div>
          ))}

          {error && (
            <div className="flex items-start gap-2 p-3 rounded-lg bg-destructive/10 text-destructive text-sm">
              <XCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
              <div className="flex-1">
                <p>{error}</p>
                <button onClick={clearError} className="text-xs underline mt-1">
                  关闭
                </button>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Edit Plan Preview */}
        {editPlan && (
          <div className="border-t border-border flex-shrink-0">
            <button
              onClick={() => setEditPlanExpanded(!editPlanExpanded)}
              className="w-full flex items-center gap-2 px-4 py-2.5 text-sm font-medium text-foreground hover:bg-accent/50 transition-colors"
            >
              {editPlanExpanded ? (
                <ChevronDown className="w-4 h-4 text-muted-foreground" />
              ) : (
                <ChevronRight className="w-4 h-4 text-muted-foreground" />
              )}
              编辑计划 ({editPlan.edits.length} 项操作)
            </button>

            {editPlanExpanded && (
              <div className="px-4 pb-3 space-y-2 max-h-60 overflow-y-auto">
                {editPlan.changelog_summary && (
                  <p className="text-xs text-muted-foreground italic">
                    {editPlan.changelog_summary}
                  </p>
                )}
                {editPlan.edits.map((edit, i) => (
                  <div key={i} className="p-2.5 rounded-md bg-muted/50 text-xs space-y-1">
                    <div className="flex items-center gap-1.5">
                      <span className={`px-1.5 py-0.5 rounded font-mono text-[10px] ${
                        edit.operation === 'replace_text'
                          ? 'bg-amber-500/20 text-amber-700 dark:text-amber-400'
                          : 'bg-emerald-500/20 text-emerald-700 dark:text-emerald-400'
                      }`}>
                        {edit.operation === 'replace_text' ? 'REPLACE' :
                         edit.operation === 'append_example' ? 'ADD EXAMPLE' : 'APPEND'}
                      </span>
                      {edit.section && (
                        <span className="text-muted-foreground">{edit.section}</span>
                      )}
                    </div>
                    {edit.reason && (
                      <p className="text-muted-foreground">{edit.reason}</p>
                    )}
                    {edit.operation === 'replace_text' && (
                      <div className="space-y-0.5">
                        <p className="text-red-600 dark:text-red-400 line-through">
                          {edit.old_text}
                        </p>
                        <p className="text-emerald-600 dark:text-emerald-400">
                          {edit.new_text}
                        </p>
                      </div>
                    )}
                    {edit.content && (
                      <p className="text-foreground border-l-2 border-border pl-2">
                        {edit.content}
                      </p>
                    )}
                  </div>
                ))}

                <div className="flex items-center gap-2 pt-2">
                  <button
                    onClick={handleApply}
                    disabled={isApplying}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-primary text-primary-foreground text-xs font-medium hover:bg-primary/90 transition-colors disabled:opacity-50"
                  >
                    {isApplying ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <Check className="w-3.5 h-3.5" />
                    )}
                    应用到画像
                  </button>
                  <button
                    onClick={rejectEditPlan}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-border text-xs font-medium hover:bg-accent transition-colors text-muted-foreground"
                  >
                    <X className="w-3.5 h-3.5" />
                    放弃
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Input */}
        <div className="border-t border-border p-3 flex-shrink-0">
          <div className="flex items-end gap-2">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={isStreaming ? '分析中...' : '和进化 Agent 对话...'}
              disabled={isStreaming}
              rows={1}
              className="flex-1 resize-none rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50 max-h-32 overflow-y-auto"
              style={{ minHeight: '36px' }}
              onInput={e => {
                const target = e.target as HTMLTextAreaElement
                target.style.height = 'auto'
                target.style.height = Math.min(target.scrollHeight, 128) + 'px'
              }}
            />
            {isStreaming ? (
              <button
                onClick={stopStreaming}
                className="flex-shrink-0 p-2 rounded-lg bg-destructive text-destructive-foreground hover:bg-destructive/90 transition-colors"
                title="停止"
              >
                <Square className="w-4 h-4" />
              </button>
            ) : (
              <button
                onClick={handleSend}
                disabled={!input.trim()}
                className="flex-shrink-0 p-2 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
                title="发送"
              >
                <Send className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
