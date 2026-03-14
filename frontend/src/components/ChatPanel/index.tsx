import { useEffect, useRef, useState } from 'react'
import { Send, Trash2, Loader2, X, ChevronDown, ChevronRight, UserCog, Check, RefreshCw } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'
import { useChatStore } from '../../stores/chatStore'

interface ChatPanelProps {
  paperId: string
}

import type { PendingProfileUpdate } from '../../services/api'

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

      {/* 展开/收起详情 */}
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

function cleanSelectedText(raw: string): string {
  return raw
    .replace(/[\uFFFD\uE000-\uF8FF\uFE00-\uFE0F]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

function stripLine(line: string): string {
  return line
    .replace(/\$\$[\s\S]*?\$\$/g, (m) => m.replace(/[\\\${}^_]/g, ' '))
    .replace(/\$[^$]*?\$/g, (m) => m.replace(/[\\\${}^_]/g, ' '))
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/\*(.+?)\*/g, '$1')
    .replace(/`(.+?)`/g, '$1')
    .replace(/[#>]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function findRawQuote(renderedText: string, rawMarkdown: string): string {
  const clean = cleanSelectedText(renderedText)
  if (clean.length < 4) return clean

  const lines = rawMarkdown.split('\n')
  const strippedLines = lines.map(stripLine)

  const concatMap: { lineIdx: number; charStart: number }[] = []
  let concat = ''
  for (let i = 0; i < strippedLines.length; i++) {
    if (strippedLines[i].length === 0) continue
    if (concat.length > 0) {
      concatMap.push({ lineIdx: -1, charStart: concat.length })
      concat += ' '
    }
    const start = concat.length
    concat += strippedLines[i]
    concatMap.push({ lineIdx: i, charStart: start })
  }

  const pos = concat.indexOf(clean)
  if (pos === -1) {
    const words = clean.split(/\s+/).filter(w => w.length >= 2)
    if (words.length === 0) return clean
    let bestStart = 0, bestEnd = 0, bestScore = 0
    for (let i = 0; i < lines.length; i++) {
      for (let j = i; j < Math.min(i + 6, lines.length); j++) {
        const block = strippedLines.slice(i, j + 1).join(' ')
        const hits = words.filter(w => block.includes(w)).length
        const score = hits / words.length
        if (score > bestScore) {
          bestScore = score
          bestStart = i
          bestEnd = j
        }
      }
    }
    if (bestScore >= 0.5) {
      return lines.slice(bestStart, bestEnd + 1).join('\n').trim()
    }
    return clean
  }

  const endPos = pos + clean.length
  let firstLine = 0, lastLine = lines.length - 1
  for (const entry of concatMap) {
    if (entry.lineIdx >= 0 && entry.charStart <= pos) firstLine = entry.lineIdx
    if (entry.lineIdx >= 0 && entry.charStart < endPos) lastLine = entry.lineIdx
  }

  return lines.slice(firstLine, lastLine + 1).join('\n').trim()
}

export function ChatPanel({ paperId }: ChatPanelProps) {
  const {
    messages,
    isLoading,
    isStreaming,
    loadHistory,
    sendMessage,
    clearHistory,
    quotes,
    addQuote,
    removeQuote,
    clearQuotes,
    pendingProfileUpdate,
    isAnalyzingProfile,
    triggerProfileAnalysis,
    checkPendingProfileUpdates,
    applyProfileUpdate,
    rejectProfileUpdate,
  } = useChatStore()

  const [input, setInput] = useState('')
  const [chatSelectedText, setChatSelectedText] = useState('')
  const [chatSelectionPosition, setChatSelectionPosition] = useState<{ x: number; y: number } | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const messagesContainerRef = useRef<HTMLDivElement>(null)
  const isNearBottomRef = useRef(true)

  useEffect(() => {
    loadHistory(paperId)
  }, [paperId, loadHistory])

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
    const container = messagesContainerRef.current
    if (!container) return

    const handleMouseUp = (e: MouseEvent) => {
      if ((e.target as HTMLElement).closest('[data-chat-quote-button]')) {
        return
      }

      setTimeout(() => {
        const selection = window.getSelection()
        const rawText = selection?.toString() || ''
        const text = cleanSelectedText(rawText)
        if (text && text.length > 0) {
          const range = selection?.getRangeAt(0)
          const rect = range?.getBoundingClientRect()
          if (rect && container.contains(selection?.anchorNode as Node)) {
            const msgEl = (selection?.anchorNode as HTMLElement)?.closest?.('[data-message-index]')
              || (selection?.anchorNode?.parentElement)?.closest?.('[data-message-index]')
            const msgIndex = msgEl ? parseInt(msgEl.getAttribute('data-message-index') || '', 10) : -1
            const { messages: msgs } = useChatStore.getState()
            let quoteText = text
            if (msgIndex >= 0 && msgs[msgIndex]?.role === 'assistant') {
              quoteText = findRawQuote(rawText, msgs[msgIndex].content)
            }
            setChatSelectedText(quoteText)
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

  const handleSend = async () => {
    if (!input.trim() || isStreaming) return

    const messageContent = input.trim()
    const currentQuotes = quotes.length > 0 ? [...quotes] : undefined

    setInput('')
    clearQuotes()
    isNearBottomRef.current = true
    await sendMessage(paperId, messageContent, currentQuotes)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="h-full flex flex-col relative">
      {/* 标题栏 */}
      <div className="p-4 border-b border-border flex items-center justify-between">
        <h2 className="font-semibold">AI 助手</h2>
        <div className="flex items-center gap-1">
          <button
            onClick={() => triggerProfileAnalysis(paperId)}
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
          <button
            onClick={() => {
              if (confirm('确定清空对话历史吗？')) {
                clearHistory(paperId)
              }
            }}
            className="p-1.5 rounded-md hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
            title="清空对话"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </div>

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
            <p>开始提问吧！</p>
            <p className="text-xs mt-2 text-center px-4">
              你可以询问关于这篇论文的任何问题，AI 会基于论文内容为你解答。
            </p>
          </div>
        ) : (
          <div>
            {messages.map((message, index) =>
              message.role === 'user' ? (
                <div
                  key={index}
                  data-message-index={index}
                  className="border-l-[3px] border-blue-400 dark:border-blue-500 bg-blue-50/50 dark:bg-blue-950/20 mx-6 my-4 px-4 py-2.5 rounded-r-md"
                >
                  {(() => {
                    const { quote, source, question } = parseMessageWithQuote(message.content)
                    return (
                      <>
                        {quote && source && <CollapsibleQuote quote={quote} source={source} />}
                        <p className="text-[15px] leading-relaxed text-foreground/70 whitespace-pre-wrap">{question}</p>
                      </>
                    )
                  })()}
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
                      remarkPlugins={[remarkMath]}
                      rehypePlugins={[rehypeKatex]}
                    >
                      {message.content || '...'}
                    </ReactMarkdown>
                  </div>
                </div>
              )
            )}
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* 输入框 */}
      <div className="p-4 border-t border-border">
        {/* 引用块显示 */}
        {quotes.length > 0 && (
          <div className="mb-2 space-y-1.5">
            {quotes.map((q, i) => (
              <div key={i} className="p-2 bg-muted rounded-md text-sm flex items-start gap-2">
                <div className="flex-1 overflow-hidden">
                  <span className="text-xs text-muted-foreground">
                    {q.source === 'pdf' ? '引用论文内容：' : '引用对话内容：'}
                  </span>
                  <p className="text-xs mt-1 line-clamp-2">{q.text}</p>
                </div>
                <button
                  onClick={() => removeQuote(i)}
                  className="p-1 hover:bg-accent rounded flex-shrink-0"
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="flex gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入问题..."
            className="flex-1 px-3 py-2 text-sm rounded-md border border-input bg-background resize-none focus:outline-none focus:ring-2 focus:ring-ring"
            rows={2}
            disabled={isStreaming}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || isStreaming}
            className="px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center"
          >
            {isStreaming ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Send className="w-4 h-4" />
            )}
          </button>
        </div>
        <p className="text-xs text-muted-foreground mt-2">
          按 Enter 发送，Shift+Enter 换行
        </p>
      </div>
    </div>
  )
}
