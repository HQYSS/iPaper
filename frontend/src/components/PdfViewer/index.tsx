import { useEffect, useState, useRef, useCallback } from 'react'
import { Worker, Viewer } from '@react-pdf-viewer/core'
import { searchPlugin } from '@react-pdf-viewer/search'
import { bookmarkPlugin } from '@react-pdf-viewer/bookmark'
import { pageNavigationPlugin } from '@react-pdf-viewer/page-navigation'
import { zoomPlugin } from '@react-pdf-viewer/zoom'

import '@react-pdf-viewer/core/lib/styles/index.css'
import '@react-pdf-viewer/search/lib/styles/index.css'
import '@react-pdf-viewer/bookmark/lib/styles/index.css'
import '@react-pdf-viewer/page-navigation/lib/styles/index.css'
import '@react-pdf-viewer/zoom/lib/styles/index.css'

import { getPdfUrl, getTranslations, type PdfLang, type TranslationStatus } from '../../services/api'
import { useChatStore } from '../../stores/chatStore'

interface PdfViewerProps {
  paperId: string
}

function SearchBox({
  onClose,
  searchPluginInstance
}: {
  onClose: () => void
  searchPluginInstance: ReturnType<typeof searchPlugin>
}) {
  const [keyword, setKeyword] = useState('')
  const [lastKeyword, setLastKeyword] = useState('')
  const [matchCount, setMatchCount] = useState(0)
  const [currentMatch, setCurrentMatch] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const timer = setTimeout(() => {
      inputRef.current?.focus()
    }, 50)
    return () => clearTimeout(timer)
  }, [])

  const scrollCurrentMatchToCenter = useCallback(() => {
    setTimeout(() => {
      const el = document.querySelector('.rpv-search__highlight--current') as HTMLElement
      if (!el) return

      // 从高亮元素向上查找实际可滚动的容器
      let scrollContainer: HTMLElement | null = el.parentElement
      while (scrollContainer) {
        const { overflow, overflowY } = getComputedStyle(scrollContainer)
        if (
          (overflow === 'auto' || overflow === 'scroll' ||
           overflowY === 'auto' || overflowY === 'scroll') &&
          scrollContainer.scrollHeight > scrollContainer.clientHeight
        ) {
          break
        }
        scrollContainer = scrollContainer.parentElement
      }

      if (!scrollContainer) return

      const elRect = el.getBoundingClientRect()
      const containerRect = scrollContainer.getBoundingClientRect()
      const offset = elRect.top - containerRect.top - (scrollContainer.clientHeight / 2) + (elRect.height / 2)
      scrollContainer.scrollTop += offset
    }, 200)
  }, [])

  const goToNext = useCallback(() => {
    if (!keyword) return
    
    if (keyword !== lastKeyword) {
      searchPluginInstance.highlight(keyword).then((matches) => {
        const count = matches?.length || 0
        setLastKeyword(keyword)
        setMatchCount(count)
        setCurrentMatch(count > 0 ? 1 : 0)
        scrollCurrentMatchToCenter()
      }).catch(() => {})
      return
    }

    searchPluginInstance.jumpToNextMatch()
    setCurrentMatch((prev) => (prev >= matchCount ? 1 : prev + 1))
    scrollCurrentMatchToCenter()
  }, [keyword, lastKeyword, matchCount, searchPluginInstance, scrollCurrentMatchToCenter])

  const goToPrev = useCallback(() => {
    if (!keyword) return
    
    if (keyword !== lastKeyword) {
      searchPluginInstance.highlight(keyword).then((matches) => {
        const count = matches?.length || 0
        setLastKeyword(keyword)
        setMatchCount(count)
        setCurrentMatch(count > 0 ? 1 : 0)
        scrollCurrentMatchToCenter()
      }).catch(() => {})
      return
    }

    searchPluginInstance.jumpToPreviousMatch()
    setCurrentMatch((prev) => (prev <= 1 ? matchCount : prev - 1))
    scrollCurrentMatchToCenter()
  }, [keyword, lastKeyword, matchCount, searchPluginInstance, scrollCurrentMatchToCenter])

  const handleClose = () => {
    searchPluginInstance.clearHighlights()
    onClose()
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      handleClose()
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (e.shiftKey) {
        goToPrev()
      } else {
        goToNext()
      }
    }
  }

  return (
    <div className="absolute top-4 right-4 z-50 bg-white rounded-lg shadow-lg border p-3 flex items-center gap-2">
      <input
        ref={inputRef}
        type="text"
        value={keyword}
        onChange={(e) => setKeyword(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="搜索..."
        className="px-3 py-1.5 border rounded-md text-sm w-48 focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
      {matchCount > 0 && (
        <span className="text-xs text-gray-500 min-w-[60px]">
          {currentMatch} / {matchCount}
        </span>
      )}
      <button
        onClick={goToPrev}
        className="p-1.5 hover:bg-gray-100 rounded"
        title="上一个 (Shift+Enter)"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
        </svg>
      </button>
      <button
        onClick={goToNext}
        className="p-1.5 hover:bg-gray-100 rounded"
        title="下一个 (Enter)"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      <button
        onClick={handleClose}
        className="p-1.5 hover:bg-gray-100 rounded"
        title="关闭 (Esc)"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>
  )
}

export function PdfViewer({ paperId }: PdfViewerProps) {
  const [pdfUrl, setPdfUrl] = useState<string>('')
  const [showSearch, setShowSearch] = useState(false)
  const [showBookmarks, setShowBookmarks] = useState(false)
  const [selectedText, setSelectedText] = useState('')
  const [selectionPosition, setSelectionPosition] = useState<{ x: number; y: number } | null>(null)
  const [currentPage, setCurrentPage] = useState(1)
  const [totalPages, setTotalPages] = useState(0)
  const [pdfLang, setPdfLang] = useState<PdfLang>('en')
  const [translations, setTranslations] = useState<TranslationStatus>({ zh: false, bilingual: false })
  const [scrollBackStack, setScrollBackStack] = useState<number[]>([])
  const scaleRef = useRef(1)
  const restoreScaleRef = useRef<number | null>(null)
  const restoreScrollRatioRef = useRef<number | null>(null)
  const pdfContainerRef = useRef<HTMLDivElement>(null)

  const addQuote = useChatStore((state) => state.addQuote)

  const searchPluginInstance = searchPlugin()
  const bookmarkPluginInstance = bookmarkPlugin()
  const pageNavigationPluginInstance = pageNavigationPlugin()
  const zoomPluginInstance = zoomPlugin()

  const { Bookmarks } = bookmarkPluginInstance
  const { CurrentPageLabel: _CurrentPageLabel } = pageNavigationPluginInstance
  const { ZoomIn, ZoomOut, CurrentScale } = zoomPluginInstance

  const blobCache = useRef<Record<string, string>>({})

  useEffect(() => {
    const cached = blobCache.current[pdfLang]
    setPdfUrl(cached || getPdfUrl(paperId, pdfLang))
  }, [paperId, pdfLang])

  useEffect(() => {
    setPdfLang('en')
    Object.values(blobCache.current).forEach(URL.revokeObjectURL)
    blobCache.current = {}
    getTranslations(paperId).then(setTranslations)
    return () => {
      Object.values(blobCache.current).forEach(URL.revokeObjectURL)
      blobCache.current = {}
    }
  }, [paperId])

  useEffect(() => {
    (['zh', 'bilingual'] as const).forEach(lang => {
      if (translations[lang] && !blobCache.current[lang]) {
        fetch(getPdfUrl(paperId, lang))
          .then(r => r.blob())
          .then(blob => { blobCache.current[lang] = URL.createObjectURL(blob) })
          .catch(() => {})
      }
    })
  }, [paperId, translations])

  // 初始加载时居中
  useEffect(() => {
    const container = pdfContainerRef.current
    if (!container) return

    const centerScroll = () => {
      const scrollContainer = container.querySelector('.rpv-core__inner-pages') as HTMLElement
      if (!scrollContainer) return

      const scrollWidth = scrollContainer.scrollWidth
      const clientWidth = scrollContainer.clientWidth

      if (scrollWidth > clientWidth) {
        scrollContainer.scrollLeft = (scrollWidth - clientWidth) / 2
      }
    }

    // 等待 PDF 加载完成后居中
    const checkInterval = setInterval(() => {
      const scrollContainer = container.querySelector('.rpv-core__inner-pages')
      if (scrollContainer) {
        clearInterval(checkInterval)
        setTimeout(centerScroll, 200)
      }
    }, 100)

    return () => {
      clearInterval(checkInterval)
    }
  }, [pdfUrl])

  useEffect(() => {
    const container = pdfContainerRef.current
    if (!container) return

    const handleLinkClick = (e: MouseEvent) => {
      const target = e.target as HTMLElement
      if (target.closest('[data-annotation-id]') || target.closest('a[href^="#"]')) {
        const sc = container.querySelector('.rpv-core__inner-pages') as HTMLElement
        if (sc) {
          setScrollBackStack(prev => [...prev, sc.scrollTop])
        }
      }
    }

    container.addEventListener('click', handleLinkClick, true)
    return () => container.removeEventListener('click', handleLinkClick, true)
  }, [])

  const handleScrollBack = useCallback(() => {
    setScrollBackStack(prev => {
      if (prev.length === 0) return prev
      const pos = prev[prev.length - 1]
      const sc = pdfContainerRef.current?.querySelector('.rpv-core__inner-pages') as HTMLElement
      if (sc) sc.scrollTop = pos
      return prev.slice(0, -1)
    })
  }, [])

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'f') {
        e.preventDefault()
        setShowSearch(true)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  useEffect(() => {
    const container = pdfContainerRef.current
    if (!container) return

    const handleMouseUp = (e: MouseEvent) => {
      if ((e.target as HTMLElement).closest('[data-quote-button]')) {
        return
      }
      
      setTimeout(() => {
        const selection = window.getSelection()
        const text = selection?.toString().trim()
        if (text && text.length > 0) {
          const range = selection?.getRangeAt(0)
          const rect = range?.getBoundingClientRect()
          if (rect && container.contains(selection?.anchorNode as Node)) {
            setSelectedText(text)
            setSelectionPosition({
              x: rect.left + rect.width / 2,
              y: rect.top - 10
            })
          }
        } else {
          setSelectedText('')
          setSelectionPosition(null)
        }
      }, 10)
    }

    const handleMouseDown = (e: MouseEvent) => {
      if ((e.target as HTMLElement).closest('[data-quote-button]')) {
        return
      }
      setSelectedText('')
      setSelectionPosition(null)
    }

    container.addEventListener('mouseup', handleMouseUp)
    container.addEventListener('mousedown', handleMouseDown)
    return () => {
      container.removeEventListener('mouseup', handleMouseUp)
      container.removeEventListener('mousedown', handleMouseDown)
    }
  }, [])

  const handleQuoteSelection = () => {
    if (selectedText) {
      addQuote(selectedText, 'pdf')
      setSelectedText('')
      setSelectionPosition(null)
      window.getSelection()?.removeAllRanges()
    }
  }

  // 包装缩放操作：先淡出，再缩放，最后居中并淡入
  const handleZoomWithFade = (zoomAction: () => void) => {
    const container = pdfContainerRef.current
    if (!container) {
      zoomAction()
      return
    }

    const scrollContainer = container.querySelector('.rpv-core__inner-pages') as HTMLElement
    if (!scrollContainer) {
      zoomAction()
      return
    }

    // 先淡出
    scrollContainer.style.transition = 'opacity 0.1s ease-out'
    scrollContainer.style.opacity = '0'

    // 等淡出完成后执行缩放
    setTimeout(() => {
      zoomAction()

      // 等缩放渲染完成后居中并淡入
      setTimeout(() => {
        const scrollWidth = scrollContainer.scrollWidth
        const clientWidth = scrollContainer.clientWidth
        if (scrollWidth > clientWidth) {
          scrollContainer.scrollLeft = (scrollWidth - clientWidth) / 2
        }

        scrollContainer.style.transition = 'opacity 0.1s ease-in'
        scrollContainer.style.opacity = '1'

        setTimeout(() => {
          scrollContainer.style.transition = ''
        }, 100)
      }, 50)
    }, 100)
  }

  if (!pdfUrl) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted-foreground">
        加载中...
      </div>
    )
  }

  return (
    <div ref={pdfContainerRef} className="flex-1 flex h-full overflow-hidden relative">
      {/* 书签侧边栏 */}
      {showBookmarks && (
        <div className="w-64 border-r bg-gray-50 overflow-auto">
          <div className="p-3 border-b bg-white flex items-center justify-between">
            <span className="font-medium text-sm">目录</span>
            <button
              onClick={() => setShowBookmarks(false)}
              className="p-1 hover:bg-gray-100 rounded"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          <div className="p-2">
            <Bookmarks />
          </div>
        </div>
      )}

      {/* PDF 主区域 */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* 搜索框 */}
        {showSearch && (
          <SearchBox
            onClose={() => setShowSearch(false)}
            searchPluginInstance={searchPluginInstance}
          />
        )}

        {/* 选中文字引用按钮 */}
        {selectedText && selectionPosition && (
          <button
            data-quote-button
            onClick={handleQuoteSelection}
            className="fixed z-50 px-3 py-1.5 bg-blue-500 text-white text-sm rounded-lg shadow-lg hover:bg-blue-600 transition-colors"
            style={{
              left: selectionPosition.x,
              top: selectionPosition.y,
              transform: 'translate(-50%, -100%)'
            }}
          >
            引用到对话
          </button>
        )}

        {/* PDF Viewer */}
        <div className="flex-1 overflow-hidden">
          <Worker workerUrl="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js">
            <Viewer
              fileUrl={pdfUrl}
              plugins={[
                searchPluginInstance,
                bookmarkPluginInstance,
                pageNavigationPluginInstance,
                zoomPluginInstance
              ]}
              defaultScale={1}
              onDocumentLoad={(e) => {
                setTotalPages(e.doc.numPages)
                const savedScale = restoreScaleRef.current
                const savedRatio = restoreScrollRatioRef.current
                restoreScaleRef.current = null
                restoreScrollRatioRef.current = null

                if (savedScale !== null || savedRatio !== null) {
                  setTimeout(() => {
                    if (savedScale !== null) {
                      zoomPluginInstance.zoomTo(savedScale)
                    }
                    setTimeout(() => {
                      if (savedRatio !== null) {
                        const sc = pdfContainerRef.current?.querySelector('.rpv-core__inner-pages') as HTMLElement
                        if (sc) {
                          sc.scrollTop = savedRatio * (sc.scrollHeight - sc.clientHeight)
                        }
                      }
                    }, 200)
                  }, 100)
                }
              }}
              onPageChange={(e) => setCurrentPage(e.currentPage + 1)}
            />
          </Worker>
        </div>

        {/* 底部浮动工具栏 */}
        <div className="absolute bottom-4 left-1/2 transform -translate-x-1/2 z-40">
          <div className="flex items-center gap-2 bg-white/95 backdrop-blur rounded-full shadow-lg border px-4 py-2">
            {/* 目录按钮 */}
            <button
              onClick={() => setShowBookmarks(!showBookmarks)}
              className={`p-2 rounded-full transition-colors ${showBookmarks ? 'bg-blue-100 text-blue-600' : 'hover:bg-gray-100'}`}
              title="目录"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h7" />
              </svg>
            </button>

            {/* 搜索按钮 */}
            <button
              onClick={() => setShowSearch(true)}
              className="p-2 rounded-full hover:bg-gray-100 transition-colors"
              title="搜索 (⌘F)"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
            </button>

            {/* 引用返回按钮 */}
            {scrollBackStack.length > 0 && (
              <button
                onClick={handleScrollBack}
                className="p-2 rounded-full bg-blue-100 text-blue-600 hover:bg-blue-200 transition-colors"
                title="返回引用位置"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 15L3 9m0 0l6-6M3 9h12a6 6 0 010 12h-3" />
                </svg>
              </button>
            )}

            <div className="w-px h-6 bg-gray-200" />

            {/* 缩放控制 */}
            <ZoomOut>
              {(props) => (
                <button
                  onClick={() => handleZoomWithFade(props.onClick)}
                  className="p-2 rounded-full hover:bg-gray-100 transition-colors"
                  title="缩小"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20 12H4" />
                  </svg>
                </button>
              )}
            </ZoomOut>

            <CurrentScale>
              {(props) => {
                scaleRef.current = props.scale
                return (
                  <span className="text-sm text-gray-600 min-w-[50px] text-center">
                    {Math.round(props.scale * 100)}%
                  </span>
                )
              }}
            </CurrentScale>

            <ZoomIn>
              {(props) => (
                <button
                  onClick={() => handleZoomWithFade(props.onClick)}
                  className="p-2 rounded-full hover:bg-gray-100 transition-colors"
                  title="放大"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                  </svg>
                </button>
              )}
            </ZoomIn>

            <div className="w-px h-6 bg-gray-200" />

            {/* 页码显示 */}
            <span className="text-sm text-gray-600 min-w-[60px] text-center">
              {currentPage} / {totalPages}
            </span>

            {/* 语言切换 */}
            {(translations.zh || translations.bilingual) && (
              <>
                <div className="w-px h-6 bg-gray-200" />
                <div className="flex items-center gap-0.5">
                  {(['en', 'zh', 'bilingual'] as const)
                    .filter(lang => lang === 'en' || translations[lang])
                    .map(lang => (
                      <button
                        key={lang}
                        onClick={() => {
                          restoreScaleRef.current = scaleRef.current
                          const sc = pdfContainerRef.current?.querySelector('.rpv-core__inner-pages') as HTMLElement
                          if (sc && sc.scrollHeight > sc.clientHeight) {
                            restoreScrollRatioRef.current = sc.scrollTop / (sc.scrollHeight - sc.clientHeight)
                          }
                          setPdfLang(lang)
                        }}
                        className={`px-2.5 py-1 rounded-full text-xs font-medium transition-colors ${
                          pdfLang === lang
                            ? 'bg-blue-100 text-blue-700'
                            : 'hover:bg-gray-100 text-gray-500'
                        }`}
                      >
                        {{ en: 'EN', zh: '中文', bilingual: '双语' }[lang]}
                      </button>
                    ))
                  }
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
