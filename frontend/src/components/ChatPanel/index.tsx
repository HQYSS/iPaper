import { useEffect, useRef, useState, useMemo, type ReactNode } from 'react'
import { Send, Square, Trash2, Loader2, X, ChevronDown, ChevronRight, ChevronLeft, UserCog, Check, RefreshCw, FileText, MessageSquare, AlertCircle, PanelRightClose, Plus, Pencil, GitCompareArrows, ArrowLeft } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkMath from 'remark-math'
import remarkGfm from 'remark-gfm'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'
import { useChatStore } from '../../stores/chatStore'

interface ChatPanelProps {
  paperId?: string
  crossPaperSessionId?: string
  onCollapse?: () => void
  onPaperLinkClick?: (paperId: string) => void
  onExitCrossChat?: () => void
}

import type { PendingProfileUpdate, SessionMeta } from '../../services/api'

const SIGNAL_TYPE_LABELS: Record<string, string> = {
  knowledge_update: '知识更新',
  positive_example: '好的讲解',
  negative_example: '待改进',
  preference_update: '偏好变化',
  interest_update: '兴趣变化',
}

function ProfileUpdateNotification({
  update,
  onApply,
  onReject,
}: {
  update: PendingProfileUpdate
  onApply: () => void
  onReject: () => void
}) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="mx-4 mt-3 p-3 bg-blue-50 dark:bg-blue-950/30 border border-blue-200 dark:border-blue-800 rounded-lg text-sm">
      <div className="flex items-start gap-2">
        <UserCog className="w-4 h-4 text-blue-500 mt-0.5 flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="font-medium text-blue-700 dark:text-blue-300">画像更新建议</p>
          <p className="text-blue-600 dark:text-blue-400 mt-1 text-xs">
            {update.summary}
          </p>
          {update.paper_title && (
            <p className="text-blue-500/70 dark:text-blue-500/50 mt-0.5 text-xs">
              来源：{update.paper_title}
            </p>
          )}
        </div>
      </div>

      <button
        onClick={() => setExpanded(!expanded)}
        className="mt-2 ml-6 text-xs text-blue-500 hover:text-blue-700 dark:hover:text-blue-300 flex items-center gap-1"
      >
        {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        {expanded ? '收起详情' : '查看详情'}
      </button>

      {expanded && (
        <div className="mt-2 ml-6 space-y-2">
          {update.signals && update.signals.length > 0 && (
            <div>
              <p className="text-xs font-medium text-blue-600 dark:text-blue-400">识别到的信号：</p>
              <ul className="mt-1 space-y-1">
                {update.signals.map((sig, i) => (
                  <li key={i} className="text-xs text-blue-600/80 dark:text-blue-400/80 pl-2 border-l-2 border-blue-300 dark:border-blue-700">
                    <span className="font-medium">[{SIGNAL_TYPE_LABELS[sig.type] || sig.type}]</span>{' '}
                    {sig.description}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {update.edits && update.edits.length > 0 && (
            <div>
              <p className="text-xs font-medium text-blue-600 dark:text-blue-400">将执行的编辑：</p>
              <ul className="mt-1 space-y-1">
                {update.edits.map((edit, i) => (
                  <li key={i} className="text-xs text-blue-600/80 dark:text-blue-400/80 pl-2 border-l-2 border-blue-300 dark:border-blue-700">
                    {edit.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      <div className="flex gap-2 mt-2 ml-6">
        <button
          onClick={onApply}
          className="flex items-center gap-1 px-2.5 py-1 text-xs bg-blue-500 text-white rounded-md hover:bg-blue-600 transition-colors"
        >
          <Check className="w-3 h-3" />
          应用
        </button>
        <button
          onClick={onReject}
          className="flex items-center gap-1 px-2.5 py-1 text-xs bg-transparent text-blue-600 dark:text-blue-400 border border-blue-300 dark:border-blue-700 rounded-md hover:bg-blue-100 dark:hover:bg-blue-900/30 transition-colors"
        >
          <X className="w-3 h-3" />
          忽略
        </button>
      </div>
    </div>
  )
}

import type { QuoteItem } from '../../stores/chatStore'

function QuoteCard({ quote, onRemove }: { quote: QuoteItem; onRemove: () => void }) {
  const [expanded, setExpanded] = useState(false)
  const isPdf = quote.source === 'pdf'
  const truncated = quote.text.length > 80 ? quote.text.slice(0, 80) + '...' : quote.text
  const needsExpand = quote.text.length > 80

  return (
    <div className={`flex rounded-lg overflow-hidden ${
      isPdf
        ? 'border-l-[3px] border-l-sky-400 bg-sky-50/60 dark:bg-sky-950/20'
        : 'border-l-[3px] border-l-purple-400 bg-purple-50/60 dark:bg-purple-950/20'
    }`}>
      <div
        className={`flex-1 flex items-start gap-2 px-3 py-2 ${needsExpand ? 'cursor-pointer' : ''}`}
        onClick={() => needsExpand && setExpanded(!expanded)}
      >
        {isPdf ? (
          <FileText className="w-3.5 h-3.5 mt-0.5 flex-shrink-0 text-sky-400" />
        ) : (
          <MessageSquare className="w-3.5 h-3.5 mt-0.5 flex-shrink-0 text-purple-400" />
        )}
        <p className="text-xs text-slate-600 dark:text-slate-300 leading-relaxed whitespace-pre-wrap">
          {expanded ? quote.text : truncated}
        </p>
      </div>
      <button
        onClick={(e) => { e.stopPropagation(); onRemove() }}
        className="px-2 flex-shrink-0 text-slate-300 hover:text-red-400 transition-colors"
      >
        <X className="w-3 h-3" />
      </button>
    </div>
  )
}

const CollapsibleQuote = ({ quote, source }: { quote: string; source: 'pdf' | 'chat' }) => {
  const [expanded, setExpanded] = useState(false)
  const prefix = source === 'pdf' ? '关于文中的这段内容' : '刚才说到'
  const truncatedQuote = quote.length > 50 ? quote.slice(0, 50) + '...' : quote

  return (
    <div
      className="mb-2 p-2 bg-black/10 rounded cursor-pointer text-xs"
      onClick={() => setExpanded(!expanded)}
    >
      <div className="flex items-center gap-1 text-opacity-80">
        {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        <span className="font-medium">{prefix}：</span>
      </div>
      <div className="mt-1 pl-4">
        {expanded ? (
          <span className="whitespace-pre-wrap">{quote}</span>
        ) : (
          <span className="text-opacity-70">{truncatedQuote}</span>
        )}
      </div>
    </div>
  )
}

const parseMessageWithQuote = (content: string) => {
  const quoteMatch = content.match(/<<<QUOTE:(pdf|chat)>>>([\s\S]*?)<<<END_QUOTE>>>\n\n([\s\S]*)/)
  if (quoteMatch) {
    return {
      source: quoteMatch[1] as 'pdf' | 'chat',
      quote: quoteMatch[2],
      question: quoteMatch[3]
    }
  }
  return { source: null, quote: null, question: content }
}

function processChildren(
  children: ReactNode,
  renderLinks: (text: string) => ReactNode[]
): ReactNode {
  if (typeof children === 'string') {
    const parts = renderLinks(children)
    if (parts.length === 1 && typeof parts[0] === 'string') return parts[0]
    return <>{parts}</>
  }
  if (Array.isArray(children)) {
    return children.map((child, i) => {
      if (typeof child === 'string') {
        const parts = renderLinks(child)
        if (parts.length === 1 && typeof parts[0] === 'string') return child
        return <span key={i}>{parts}</span>
      }
      return child
    })
  }
  return children
}

function cleanSelectedText(raw: string): string {
  return raw
    .replace(/[^\u0020-\u007E\u00A0-\u024F\u0370-\u03FF\u2000-\u206F\u2100-\u214F\u2190-\u21FF\u2200-\u22FF\u2300-\u23FF\u2500-\u257F\u2600-\u26FF\u3000-\u9FFF\uF900-\uFAFF\uFF00-\uFFEF]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

function SessionTabBar({
  sessions,
  currentSessionId,
  onSwitch,
  onCreate,
  onDelete,
  paperId,
}: {
  sessions: SessionMeta[]
  currentSessionId: string | null
  onSwitch: (paperId: string, sessionId: string) => void
  onCreate: (paperId: string) => void
  onDelete: (paperId: string, sessionId: string) => void
  paperId: string
}) {
  const tabsRef = useRef<HTMLDivElement>(null)

  if (sessions.length === 0) return null

  return (
    <div className="border-b border-border flex items-center">
      <div ref={tabsRef} className="flex-1 flex overflow-x-auto no-scrollbar">
        {sessions.map((session) => {
          const isActive = session.id === currentSessionId
          const truncatedTitle = session.title.length > 12 ? session.title.slice(0, 12) + '…' : session.title
          return (
            <button
              key={session.id}
              onClick={() => onSwitch(paperId, session.id)}
              className={`group relative flex items-center gap-1 px-3 py-1.5 text-xs whitespace-nowrap border-b-2 transition-colors flex-shrink-0 ${
                isActive
                  ? 'border-primary text-foreground'
                  : 'border-transparent text-muted-foreground hover:text-foreground hover:bg-accent/50'
              }`}
              title={session.title}
            >
              <span>{truncatedTitle}</span>
              {sessions.length > 1 && (
                <span
                  role="button"
                  onClick={(e) => {
                    e.stopPropagation()
                    onDelete(paperId, session.id)
                  }}
                  className="ml-0.5 opacity-0 group-hover:opacity-100 hover:text-red-400 transition-opacity"
                >
                  <X className="w-3 h-3" />
                </span>
              )}
            </button>
          )
        })}
      </div>
      <button
        onClick={() => onCreate(paperId)}
        className="flex-shrink-0 p-1.5 mx-1 rounded-md hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
        title="新建对话"
      >
        <Plus className="w-3.5 h-3.5" />
      </button>
    </div>
  )
}

function ForkNavigator({
  forkData,
  onSwitch,
}: {
  forkData: { alternatives: unknown[][]; active: number }
  onSwitch: (index: number) => void
}) {
  const total = forkData.alternatives.length
  const current = forkData.active

  return (
    <div className="flex items-center gap-0.5 text-xs text-muted-foreground">
      <button
        onClick={() => onSwitch(current - 1)}
        disabled={current === 0}
        className="p-0.5 rounded hover:bg-accent disabled:opacity-30 transition-colors"
      >
        <ChevronLeft className="w-3 h-3" />
      </button>
      <span className="min-w-[2rem] text-center">{current + 1}/{total}</span>
      <button
        onClick={() => onSwitch(current + 1)}
        disabled={current === total - 1}
        className="p-0.5 rounded hover:bg-accent disabled:opacity-30 transition-colors"
      >
        <ChevronRight className="w-3 h-3" />
      </button>
    </div>
  )
}

export function ChatPanel({ paperId, crossPaperSessionId, onCollapse, onPaperLinkClick, onExitCrossChat }: ChatPanelProps) {
  const isCrossMode = !!crossPaperSessionId

  const {
    messages,
    isLoading,
    isStreaming,
    loadSessions,
    sendMessage,
    stopStreaming,
    clearHistory,
    quotes,
    addQuote,
    removeQuote,
    clearQuotes,
    error,
    clearError,
    pendingProfileUpdate,
    isAnalyzingProfile,
    triggerProfileAnalysis,
    checkPendingProfileUpdates,
    applyProfileUpdate,
    rejectProfileUpdate,
    sessions,
    currentSessionId,
    createSession,
    deleteSession,
    switchSession,
    forks,
    editMessage,
    switchFork,
    focusInputNonce,
    sendCrossPaperMessage,
    clearCrossPaperHistory,
    editCrossPaperMessage,
    switchCrossPaperFork,
  } = useChatStore()

  const [input, setInput] = useState('')
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [editingContent, setEditingContent] = useState('')
  const [chatSelectedText, setChatSelectedText] = useState('')
  const [chatSelectionPosition, setChatSelectionPosition] = useState<{ x: number; y: number } | null>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const messagesContainerRef = useRef<HTMLDivElement>(null)
  const isNearBottomRef = useRef(true)

  useEffect(() => {
    if (!isCrossMode && paperId) {
      loadSessions(paperId)
    }
  }, [paperId, loadSessions, isCrossMode])

  useEffect(() => {
    checkPendingProfileUpdates()
  }, [checkPendingProfileUpdates])

  useEffect(() => {
    const container = messagesContainerRef.current
    if (!container) return
    const handleScroll = () => {
      const threshold = 80
      isNearBottomRef.current =
        container.scrollHeight - container.scrollTop - container.clientHeight < threshold
    }
    container.addEventListener('scroll', handleScroll)
    return () => container.removeEventListener('scroll', handleScroll)
  }, [])

  useEffect(() => {
    if (isNearBottomRef.current) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages])

  useEffect(() => {
    const textarea = inputRef.current
    if (!textarea || textarea.disabled) return

    textarea.focus()
    const cursorPosition = textarea.value.length
    textarea.setSelectionRange(cursorPosition, cursorPosition)
  }, [focusInputNonce])

  useEffect(() => {
    const container = messagesContainerRef.current
    if (!container) return

    const handleMouseUp = (e: MouseEvent) => {
      if ((e.target as HTMLElement).closest('[data-chat-quote-button]')) {
        return
      }

      setTimeout(() => {
        const selection = window.getSelection()
        const text = cleanSelectedText(selection?.toString() || '')
        if (text && text.length > 0) {
          const range = selection?.getRangeAt(0)
          const rect = range?.getBoundingClientRect()
          if (rect && container.contains(selection?.anchorNode as Node)) {
            setChatSelectedText(text)
            setChatSelectionPosition({
              x: rect.left + rect.width / 2,
              y: rect.top - 10
            })
          }
        } else {
          setChatSelectedText('')
          setChatSelectionPosition(null)
        }
      }, 10)
    }

    const handleMouseDown = (e: MouseEvent) => {
      if ((e.target as HTMLElement).closest('[data-chat-quote-button]')) {
        return
      }
      setChatSelectedText('')
      setChatSelectionPosition(null)
    }

    container.addEventListener('mouseup', handleMouseUp)
    container.addEventListener('mousedown', handleMouseDown)
    return () => {
      container.removeEventListener('mouseup', handleMouseUp)
      container.removeEventListener('mousedown', handleMouseDown)
    }
  }, [])

  const handleQuoteChatSelection = () => {
    if (chatSelectedText) {
      addQuote(chatSelectedText, 'chat')
      setChatSelectedText('')
      setChatSelectionPosition(null)
      window.getSelection()?.removeAllRanges()
    }
  }

  const activeSessionId = isCrossMode ? crossPaperSessionId : currentSessionId

  const handleSend = async () => {
    if (!input.trim() || isStreaming || !activeSessionId) return

    const messageContent = input.trim()
    const currentQuotes = quotes.length > 0 ? [...quotes] : undefined

    setInput('')
    clearQuotes()
    isNearBottomRef.current = true

    if (isCrossMode) {
      await sendCrossPaperMessage(activeSessionId, messageContent, currentQuotes)
    } else if (paperId) {
      await sendMessage(paperId, activeSessionId, messageContent, currentQuotes)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      handleSend()
    }
  }

  const renderPaperLinks = useMemo(() => {
    const PAPER_LINK_RE = /\[\[(\d{4}\.\d{4,5})\]\]/g

    return (text: string): ReactNode[] => {
      if (!onPaperLinkClick) return [text]

      const parts: ReactNode[] = []
      let lastIndex = 0
      let match: RegExpExecArray | null

      while ((match = PAPER_LINK_RE.exec(text)) !== null) {
        if (match.index > lastIndex) {
          parts.push(text.slice(lastIndex, match.index))
        }
        const arxivId = match[1]
        parts.push(
          <button
            key={`${match.index}-${arxivId}`}
            onClick={() => onPaperLinkClick(arxivId)}
            className="inline-flex items-center gap-0.5 px-1.5 py-0.5 -my-0.5 rounded bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 hover:bg-purple-200 dark:hover:bg-purple-900/50 text-sm font-mono transition-colors cursor-pointer"
            title={`切换到论文 ${arxivId}`}
          >
            {arxivId}
          </button>
        )
        lastIndex = match.index + match[0].length
      }

      if (lastIndex < text.length) {
        parts.push(text.slice(lastIndex))
      }

      return parts.length > 0 ? parts : [text]
    }
  }, [onPaperLinkClick])

  /* eslint-disable @typescript-eslint/no-explicit-any */
  const crossPaperMarkdownComponents = useMemo((): any => {
    if (!onPaperLinkClick) return undefined

    const makeComponent = (Tag: any) => {
      const Component = ({ children, node: _node, ...rest }: any) => {
        const processed = processChildren(children, renderPaperLinks)
        return <Tag {...rest}>{processed}</Tag>
      }
      return Component
    }

    return {
      p: makeComponent('p'),
      li: makeComponent('li'),
      td: makeComponent('td'),
      th: makeComponent('th'),
      strong: makeComponent('strong'),
    }
  }, [onPaperLinkClick, renderPaperLinks])
  /* eslint-enable @typescript-eslint/no-explicit-any */

  return (
    <div className="h-full flex flex-col relative">
      {/* 标题栏 */}
      <div className="p-4 border-b border-border flex items-center justify-between">
        <div className="flex items-center gap-1">
          {isCrossMode && onExitCrossChat && (
            <button
              onClick={onExitCrossChat}
              className="p-1.5 rounded-md hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
              title="退出串讲"
            >
              <ArrowLeft className="w-4 h-4" />
            </button>
          )}
          {!isCrossMode && onCollapse && (
            <button
              onClick={onCollapse}
              className="p-1.5 rounded-md hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
              title="收起讲解面板"
            >
              <PanelRightClose className="w-4 h-4" />
            </button>
          )}
          <h2 className="font-semibold flex items-center gap-1.5">
            {isCrossMode && <GitCompareArrows className="w-4 h-4 text-purple-500" />}
            {isCrossMode ? '串讲' : 'AI 助手'}
          </h2>
        </div>
        <div className="flex items-center gap-1">
          {!isCrossMode && (
            <button
              onClick={() => paperId && triggerProfileAnalysis(paperId)}
              disabled={isAnalyzingProfile || messages.length < 2}
              className="p-1.5 rounded-md hover:bg-accent transition-colors text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed"
              title="分析对话并更新画像"
            >
              {isAnalyzingProfile ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <RefreshCw className="w-4 h-4" />
              )}
            </button>
          )}
          <button
            onClick={() => {
              if (!activeSessionId || !confirm('确定清空当前对话历史吗？')) return
              if (isCrossMode) {
                clearCrossPaperHistory(activeSessionId)
              } else if (paperId) {
                clearHistory(paperId, activeSessionId)
              }
            }}
            className="p-1.5 rounded-md hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
            title="清空对话"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* 会话标签栏（仅单论文模式） */}
      {!isCrossMode && paperId && (
        <SessionTabBar
          sessions={sessions}
          currentSessionId={currentSessionId}
          onSwitch={switchSession}
          onCreate={createSession}
          onDelete={deleteSession}
          paperId={paperId}
        />
      )}

      {/* 画像更新通知 */}
      {pendingProfileUpdate && (
        <ProfileUpdateNotification
          update={pendingProfileUpdate}
          onApply={applyProfileUpdate}
          onReject={rejectProfileUpdate}
        />
      )}

      {/* 消息列表（笔记本式文档流） */}
      <div ref={messagesContainerRef} className="flex-1 overflow-y-auto relative">
        {/* 聊天内容引用按钮 */}
        {chatSelectedText && chatSelectionPosition && (
          <button
            data-chat-quote-button
            onClick={handleQuoteChatSelection}
            className="fixed z-50 px-3 py-1.5 bg-blue-500 text-white text-sm rounded-lg shadow-lg hover:bg-blue-600 transition-colors"
            style={{
              left: chatSelectionPosition.x,
              top: chatSelectionPosition.y,
              transform: 'translate(-50%, -100%)'
            }}
          >
            引用到对话
          </button>
        )}

        {isLoading && messages.length === 0 ? (
          <div className="flex items-center justify-center h-full text-muted-foreground">
            <Loader2 className="w-5 h-5 animate-spin mr-2" />
            加载中...
          </div>
        ) : messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-muted-foreground text-sm">
            <p>{isCrossMode ? '串讲即将开始…' : '开始提问吧！'}</p>
            <p className="text-xs mt-2 text-center px-4">
              {isCrossMode
                ? 'AI 正在阅读所有论文，即将产出对比分析。'
                : '你可以询问关于这篇论文的任何问题，AI 会基于论文内容为你解答。'}
            </p>
          </div>
        ) : (
          <div>
            {messages.map((message, index) =>
              message.role === 'user' ? (
                <div
                  key={index}
                  data-message-index={index}
                  className="group/msg border-l-[3px] border-blue-400 dark:border-blue-500 bg-blue-50/50 dark:bg-blue-950/20 mx-6 my-4 px-4 py-2.5 rounded-r-md"
                >
                  {editingIndex === index ? (
                    <div className="space-y-2">
                      <textarea
                        value={editingContent}
                        onChange={(e) => setEditingContent(e.target.value)}
                        className="w-full px-2 py-1.5 text-sm rounded border border-input bg-background resize-none focus:outline-none focus:ring-2 focus:ring-ring"
                        rows={3}
                        autoFocus
                        onKeyDown={(e) => {
                          if (e.key === 'Escape') setEditingIndex(null)
                        }}
                      />
                      <div className="flex gap-2 justify-end">
                        <button
                          onClick={() => setEditingIndex(null)}
                          className="px-2.5 py-1 text-xs rounded border border-input hover:bg-accent transition-colors"
                        >
                          取消
                        </button>
                        <button
                          onClick={() => {
                            if (editingContent.trim() && activeSessionId) {
                              if (isCrossMode) {
                                editCrossPaperMessage(activeSessionId, index, editingContent.trim())
                              } else if (paperId) {
                                editMessage(paperId, activeSessionId, index, editingContent.trim())
                              }
                              setEditingIndex(null)
                            }
                          }}
                          disabled={!editingContent.trim() || isStreaming}
                          className="px-2.5 py-1 text-xs rounded bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors"
                        >
                          发送
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      {(() => {
                        const { quote, source, question } = parseMessageWithQuote(message.content)
                        return (
                          <>
                            {quote && source && <CollapsibleQuote quote={quote} source={source} />}
                            <p className="text-[15px] leading-relaxed text-foreground/70 whitespace-pre-wrap">{question}</p>
                          </>
                        )
                      })()}
                      <div className="flex items-center justify-between mt-1">
                        <div>
                          {forks[String(index)] && (
                            <ForkNavigator
                              forkData={forks[String(index)]}
                              onSwitch={(fi) => {
                                if (!activeSessionId) return
                                if (isCrossMode) {
                                  switchCrossPaperFork(activeSessionId, index, fi)
                                } else if (paperId) {
                                  switchFork(paperId, activeSessionId, index, fi)
                                }
                              }}
                            />
                          )}
                        </div>
                        {!isStreaming && (
                          <button
                            onClick={() => {
                              setEditingIndex(index)
                              setEditingContent(parseMessageWithQuote(message.content).question)
                            }}
                            className="p-1 rounded opacity-0 group-hover/msg:opacity-100 hover:bg-accent text-muted-foreground hover:text-foreground transition-all"
                            title="编辑消息"
                          >
                            <Pencil className="w-3 h-3" />
                          </button>
                        )}
                      </div>
                    </>
                  )}
                </div>
              ) : (
                <div key={index} data-message-index={index} className="px-8 py-6">
                  <div className="prose dark:prose-invert max-w-none
                    prose-p:text-[15px] prose-p:leading-[1.8] prose-p:my-3
                    prose-headings:font-semibold
                    prose-h1:text-xl prose-h1:mt-8 prose-h1:mb-4
                    prose-h2:text-lg prose-h2:mt-7 prose-h2:mb-3
                    prose-h3:text-base prose-h3:mt-5 prose-h3:mb-2
                    prose-li:text-[15px] prose-li:leading-[1.8] prose-li:my-1
                    prose-strong:text-foreground prose-strong:font-semibold
                    prose-blockquote:border-l-[3px] prose-blockquote:border-muted-foreground/30 prose-blockquote:pl-4 prose-blockquote:text-muted-foreground prose-blockquote:not-italic
                    prose-table:text-sm
                    prose-pre:bg-muted prose-pre:text-foreground prose-pre:rounded-lg
                    prose-code:text-[14px] prose-code:before:content-none prose-code:after:content-none
                    prose-hr:my-6 prose-hr:border-border
                  ">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm, remarkMath]}
                      rehypePlugins={[rehypeKatex]}
                      components={isCrossMode ? crossPaperMarkdownComponents : undefined}
                    >
                      {message.content || '...'}
                    </ReactMarkdown>
                  </div>
                </div>
              )
            )}
          </div>
        )}
        {error && (
          <div className="mx-6 my-4 p-3 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 rounded-lg flex items-start gap-2">
            <AlertCircle className="w-4 h-4 text-red-500 mt-0.5 flex-shrink-0" />
            <p className="flex-1 text-sm text-red-700 dark:text-red-300">{error}</p>
            <button
              onClick={clearError}
              className="flex-shrink-0 text-red-400 hover:text-red-600 dark:hover:text-red-200 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* 输入框 */}
      <div className="p-4 border-t border-border">
        {/* 引用块显示 */}
        {quotes.length > 0 && (
          <div className="mb-3 space-y-2">
            {quotes.map((q, i) => (
              <QuoteCard key={i} quote={q} onRemove={() => removeQuote(i)} />
            ))}
          </div>
        )}

        <div className="flex gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入问题..."
            className="flex-1 px-3 py-2 text-sm rounded-md border border-input bg-background resize-none focus:outline-none focus:ring-2 focus:ring-ring"
            rows={2}
            disabled={isStreaming}
          />
          {isStreaming ? (
            <button
              onClick={stopStreaming}
              className="px-4 py-2 bg-destructive text-destructive-foreground rounded-md hover:bg-destructive/90 flex items-center justify-center"
              title="停止生成"
            >
              <Square className="w-4 h-4" />
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={!input.trim()}
              className="px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center"
            >
              <Send className="w-4 h-4" />
            </button>
          )}
        </div>
        <p className="text-xs text-muted-foreground mt-2">
          按 Enter 发送，Shift+Enter 换行
        </p>
      </div>
    </div>
  )
}
