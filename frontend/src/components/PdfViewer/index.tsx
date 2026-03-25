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

import { getPdfUrl, getTranslations, triggerTranslation, getTranslateStatus, type PdfLang, type TranslationStatus, type TranslateStatus } from '../../services/api'
import { useChatStore } from '../../stores/chatStore'

interface PdfViewerProps {
  paperId: string
}

const PDF_SCALE_STORAGE_KEY = 'ipaper.pdfScale'
const PDF_DIMMING_MODE_STORAGE_KEY = 'ipaper.pdfDimmingMode'
const PDF_OVERLAY_OPACITY_STORAGE_KEY = 'ipaper.pdfOverlayOpacity'
const PDF_BRIGHTNESS_STORAGE_KEY = 'ipaper.pdfBrightness'
const PDF_READING_POSITIONS_STORAGE_KEY = 'ipaper.pdfReadingPositions'
const PDF_LANG_STORAGE_KEY = 'ipaper.pdfLangs'

type PdfDimmingMode = 'off' | 'overlay' | 'brightness'

const OVERLAY_LEVELS = [0.05, 0.08, 0.12, 0.16, 0.2]
const BRIGHTNESS_LEVELS = [0.95, 0.9, 0.85, 0.8, 0.75]

function isValidDimmingMode(value: string | null): value is PdfDimmingMode {
  return value === 'off' || value === 'overlay' || value === 'brightness'
}

function getStoredPdfDimmingMode(): PdfDimmingMode {
  const rawValue = window.localStorage.getItem(PDF_DIMMING_MODE_STORAGE_KEY)
  return isValidDimmingMode(rawValue) ? rawValue : 'off'
}

function getStoredPdfValue(storageKey: string, validValues: number[], fallbackValue: number) {
  const rawValue = window.localStorage.getItem(storageKey)
  if (!rawValue) return fallbackValue

  const value = Number(rawValue)
  return validValues.includes(value) ? value : fallbackValue
}

function getStoredPdfScale() {
  const rawValue = window.localStorage.getItem(PDF_SCALE_STORAGE_KEY)
  if (!rawValue) return null

  const scale = Number(rawValue)
  if (!Number.isFinite(scale) || scale <= 0) {
    return null
  }

  return scale
}

function getPdfReadingPositionKey(paperId: string, pdfLang: PdfLang) {
  return `${paperId}:${pdfLang}`
}

function getStoredPdfReadingPositions(): Record<string, number> {
  try {
    const rawValue = window.localStorage.getItem(PDF_READING_POSITIONS_STORAGE_KEY)
    if (!rawValue) return {}

    const parsed: unknown = JSON.parse(rawValue)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return {}
    }

    return Object.entries(parsed).reduce<Record<string, number>>((acc, [key, value]) => {
      if (typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1) {
        acc[key] = value
      }
      return acc
    }, {})
  } catch {
    return {}
  }
}

function getStoredPdfReadingPosition(paperId: string, pdfLang: PdfLang) {
  const positions = getStoredPdfReadingPositions()
  const key = getPdfReadingPositionKey(paperId, pdfLang)
  return positions[key] ?? null
}

function savePdfReadingPosition(paperId: string, pdfLang: PdfLang, ratio: number) {
  if (!Number.isFinite(ratio) || ratio < 0 || ratio > 1) return

  const positions = getStoredPdfReadingPositions()
  positions[getPdfReadingPositionKey(paperId, pdfLang)] = ratio
  window.localStorage.setItem(PDF_READING_POSITIONS_STORAGE_KEY, JSON.stringify(positions))
}

function getStoredPdfLang(paperId: string): PdfLang {
  try {
    const raw = window.localStorage.getItem(PDF_LANG_STORAGE_KEY)
    if (!raw) return 'en'
    const map: unknown = JSON.parse(raw)
    if (!map || typeof map !== 'object' || Array.isArray(map)) return 'en'
    const val = (map as Record<string, string>)[paperId]
    if (val === 'zh' || val === 'bilingual') return val
    return 'en'
  } catch {
    return 'en'
  }
}

function savePdfLang(paperId: string, lang: PdfLang) {
  try {
    const raw = window.localStorage.getItem(PDF_LANG_STORAGE_KEY)
    const map: Record<string, string> = raw ? JSON.parse(raw) : {}
    if (lang === 'en') {
      delete map[paperId]
    } else {
      map[paperId] = lang
    }
    window.localStorage.setItem(PDF_LANG_STORAGE_KEY, JSON.stringify(map))
  } catch {
    // ignore
  }
}

function isSelectionInsidePdf(container: HTMLDivElement, selection: Selection | null): boolean {
  if (!selection || selection.rangeCount === 0) return false

  const innerPages = container.querySelector('.rpv-core__inner-pages')
  const selectionRoot = innerPages ?? container
  const range = selection.getRangeAt(0)
  const anchorNode = range.commonAncestorContainer || selection.anchorNode

  return !!anchorNode && selectionRoot.contains(anchorNode)
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
  const cleanupRef = useRef<(() => void) | null>(null)

  useEffect(() => {
    const timer = setTimeout(() => {
      inputRef.current?.focus()
    }, 50)
    return () => clearTimeout(timer)
  }, [])

  const scrollCurrentMatchToCenter = useCallback(() => {
    cleanupRef.current?.()

    const scrollContainer = document.querySelector('.rpv-core__inner-pages') as HTMLElement
    if (!scrollContainer) return

    scrollContainer.style.transition = 'opacity 0.05s'
    scrollContainer.style.opacity = '0'

    const fadeIn = () => {
      requestAnimationFrame(() => {
        scrollContainer.style.transition = 'opacity 0.08s'
        scrollContainer.style.opacity = '1'
        setTimeout(() => { scrollContainer.style.transition = '' }, 100)
      })
    }

    let pollTimer: ReturnType<typeof setInterval>
    let safetyTimer: ReturnType<typeof setTimeout>
    let lastScrollTop = scrollContainer.scrollTop
    let stableCount = 0

    const cleanup = () => {
      clearInterval(pollTimer)
      clearTimeout(safetyTimer)
      cleanupRef.current = null
    }

    const tryCenter = () => {
      const currentScrollTop = scrollContainer.scrollTop
      if (currentScrollTop !== lastScrollTop) {
        lastScrollTop = currentScrollTop
        stableCount = 0
        return
      }

      stableCount++
      if (stableCount < 2) return

      const all = document.querySelectorAll('.rpv-search__highlight--current')
      if (all.length === 0) return

      const containerRect = scrollContainer.getBoundingClientRect()

      let el: Element | null = null
      let bestDist = Infinity
      for (const e of all) {
        const rect = e.getBoundingClientRect()
        if (rect.top < containerRect.bottom && rect.bottom > containerRect.top) {
          const dist = Math.abs(rect.top + rect.height / 2 - (containerRect.top + containerRect.height / 2))
          if (dist < bestDist) {
            bestDist = dist
            el = e
          }
        }
      }

      if (!el) {
        stableCount = 0
        return
      }

      const elRect = el.getBoundingClientRect()
      const offset = elRect.top - containerRect.top - (scrollContainer.clientHeight / 2) + (elRect.height / 2)
      scrollContainer.scrollTop += offset

      cleanup()
      fadeIn()
    }

    cleanupRef.current = cleanup
    pollTimer = setInterval(tryCenter, 80)

    safetyTimer = setTimeout(() => {
      cleanup()
      fadeIn()
    }, 8000)
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
    <div className="absolute top-4 right-4 z-50 flex items-center gap-2 rounded-lg border border-slate-200 bg-white p-3 shadow-lg dark:border-slate-700 dark:bg-slate-900">
      <input
        ref={inputRef}
        type="text"
        value={keyword}
        onChange={(e) => setKeyword(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="搜索..."
        className="w-48 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
      />
      {matchCount > 0 && (
        <span className="min-w-[60px] text-xs text-slate-500 dark:text-slate-400">
          {currentMatch} / {matchCount}
        </span>
      )}
      <button
        onClick={goToPrev}
        className="rounded p-1.5 transition-colors hover:bg-slate-100 dark:hover:bg-slate-800"
        title="上一个 (Shift+Enter)"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
        </svg>
      </button>
      <button
        onClick={goToNext}
        className="rounded p-1.5 transition-colors hover:bg-slate-100 dark:hover:bg-slate-800"
        title="下一个 (Enter)"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      <button
        onClick={handleClose}
        className="rounded p-1.5 transition-colors hover:bg-slate-100 dark:hover:bg-slate-800"
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
  const [showDimmingControls, setShowDimmingControls] = useState(false)
  const [selectedText, setSelectedText] = useState('')
  const [selectionPosition, setSelectionPosition] = useState<{ x: number; y: number } | null>(null)
  const [currentPage, setCurrentPage] = useState(1)
  const [totalPages, setTotalPages] = useState(0)
  const [pageInputValue, setPageInputValue] = useState('1')
  const [isEditingPageInput, setIsEditingPageInput] = useState(false)
  const [pdfLang, setPdfLang] = useState<PdfLang>('en')
  const [translations, setTranslations] = useState<TranslationStatus>({ zh: false, bilingual: false })
  const [translateStatus, setTranslateStatus] = useState<TranslateStatus | null>(null)
  const translatePollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [scrollBackStack, setScrollBackStack] = useState<number[]>([])
  const [pdfDimmingMode, setPdfDimmingMode] = useState<PdfDimmingMode>(() => getStoredPdfDimmingMode())
  const [overlayOpacity, setOverlayOpacity] = useState(() => getStoredPdfValue(PDF_OVERLAY_OPACITY_STORAGE_KEY, OVERLAY_LEVELS, 0.12))
  const [brightnessLevel, setBrightnessLevel] = useState(() => getStoredPdfValue(PDF_BRIGHTNESS_STORAGE_KEY, BRIGHTNESS_LEVELS, 0.85))
  const scaleRef = useRef(1)
  const restoreScaleRef = useRef<number | null>(null)
  const restoreScrollRatioRef = useRef<number | null>(null)
  const pdfContainerRef = useRef<HTMLDivElement>(null)
  const cancelPageInputCommitRef = useRef(false)

  const addQuote = useChatStore((state) => state.addQuote)

  const searchPluginInstance = searchPlugin()
  const bookmarkPluginInstance = bookmarkPlugin()
  const pageNavigationPluginInstance = pageNavigationPlugin()
  const zoomPluginInstance = zoomPlugin()

  const { Bookmarks } = bookmarkPluginInstance
  const { CurrentPageLabel: _CurrentPageLabel } = pageNavigationPluginInstance
  const { ZoomIn, ZoomOut, CurrentScale } = zoomPluginInstance

  const blobCache = useRef<Record<string, string>>({})

  const persistScale = useCallback((scale: number) => {
    window.localStorage.setItem(PDF_SCALE_STORAGE_KEY, String(scale))
  }, [])

  const persistReadingPosition = useCallback((targetPaperId: string, targetPdfLang: PdfLang) => {
    const scrollContainer = pdfContainerRef.current?.querySelector('.rpv-core__inner-pages') as HTMLElement | null
    if (!scrollContainer) return null

    const maxScrollTop = scrollContainer.scrollHeight - scrollContainer.clientHeight
    const ratio = maxScrollTop > 0 ? scrollContainer.scrollTop / maxScrollTop : 0
    savePdfReadingPosition(targetPaperId, targetPdfLang, ratio)
    return ratio
  }, [])

  const handleDimmingModeChange = useCallback((mode: PdfDimmingMode) => {
    setPdfDimmingMode(mode)
    window.localStorage.setItem(PDF_DIMMING_MODE_STORAGE_KEY, mode)
  }, [])

  const handleOverlayOpacityChange = useCallback((value: number) => {
    setOverlayOpacity(value)
    window.localStorage.setItem(PDF_OVERLAY_OPACITY_STORAGE_KEY, String(value))
  }, [])

  const handleBrightnessLevelChange = useCallback((value: number) => {
    setBrightnessLevel(value)
    window.localStorage.setItem(PDF_BRIGHTNESS_STORAGE_KEY, String(value))
  }, [])

  useEffect(() => {
    const cached = blobCache.current[pdfLang]
    setPdfUrl(cached || getPdfUrl(paperId, pdfLang))
  }, [paperId, pdfLang])

  useEffect(() => {
    if (!isEditingPageInput) {
      setPageInputValue(String(currentPage))
    }
  }, [currentPage, isEditingPageInput])

  const stopTranslatePoll = useCallback(() => {
    if (translatePollRef.current) {
      clearInterval(translatePollRef.current)
      translatePollRef.current = null
    }
  }, [])

  const startTranslatePoll = useCallback((targetPaperId: string) => {
    stopTranslatePoll()
    const poll = async () => {
      try {
        const st = await getTranslateStatus(targetPaperId)
        setTranslateStatus(st)
        if (st.status === 'finished') {
          stopTranslatePoll()
          setTranslations(prev => ({ ...prev, zh: true }))
          fetch(getPdfUrl(targetPaperId, 'zh'))
            .then(r => r.blob())
            .then(blob => {
              blobCache.current['zh'] = URL.createObjectURL(blob)
              restoreScaleRef.current = scaleRef.current
              setPdfLang('zh')
              savePdfLang(targetPaperId, 'zh')
            })
            .catch(() => {})
        } else if (st.status === 'failed' || st.status === 'error' || st.status === 'needs_login') {
          stopTranslatePoll()
        }
      } catch {
        // ignore transient errors
      }
    }
    poll()
    translatePollRef.current = setInterval(poll, 5000)
  }, [stopTranslatePoll])

  const handleTriggerTranslation = useCallback(async (targetPaperId: string) => {
    try {
      const st = await triggerTranslation(targetPaperId)
      setTranslateStatus(st)
      if (st.status === 'polling') {
        startTranslatePoll(targetPaperId)
      } else if (st.status === 'finished') {
        setTranslations(prev => ({ ...prev, zh: true }))
      }
    } catch {
      setTranslateStatus({ status: 'error', info: '', error: '触发翻译失败' })
    }
  }, [startTranslatePoll])

  useEffect(() => {
    setTranslateStatus(null)
    stopTranslatePoll()
    Object.values(blobCache.current).forEach(URL.revokeObjectURL)
    blobCache.current = {}
    getTranslations(paperId).then(tr => {
      setTranslations(tr)
      const saved = getStoredPdfLang(paperId)
      setPdfLang(saved !== 'en' && tr[saved] ? saved : 'en')
    })
    return () => {
      stopTranslatePoll()
      Object.values(blobCache.current).forEach(URL.revokeObjectURL)
      blobCache.current = {}
    }
  }, [paperId, stopTranslatePoll])

  useEffect(() => {
    return () => {
      persistReadingPosition(paperId, pdfLang)
    }
  }, [paperId, pdfLang, persistReadingPosition])

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
        const raw = selection?.toString() || ''
        const text = raw.replace(/[^\u0020-\u007E\u00A0-\u024F\u0370-\u03FF\u2000-\u206F\u2100-\u214F\u2190-\u21FF\u2200-\u22FF\u2300-\u23FF\u2500-\u257F\u2600-\u26FF\u3000-\u9FFF\uF900-\uFAFF\uFF00-\uFFEF]/g, '').replace(/\s+/g, ' ').trim()
        if (text && text.length > 0) {
          if (!selection || selection.rangeCount === 0) return
          const range = selection.getRangeAt(0)
          const rect = range?.getBoundingClientRect()
          if (rect && isSelectionInsidePdf(container, selection)) {
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
      const target = e.target as HTMLElement
      if (target.closest('[data-quote-button]')) {
        return
      }
      if (target.closest('.rpv-core__text-layer') || target.closest('.rpv-core__inner-pages')) {
        return
      }
      setSelectedText('')
      setSelectionPosition(null)
    }

    container.addEventListener('mouseup', handleMouseUp, true)
    container.addEventListener('mousedown', handleMouseDown, true)
    return () => {
      container.removeEventListener('mouseup', handleMouseUp, true)
      container.removeEventListener('mousedown', handleMouseDown, true)
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

  const commitPageInput = useCallback(() => {
    if (!totalPages) {
      setPageInputValue(String(currentPage))
      return
    }

    const trimmedValue = pageInputValue.trim()
    if (!trimmedValue) {
      setPageInputValue(String(currentPage))
      return
    }

    const parsedPage = Number.parseInt(trimmedValue, 10)
    if (!Number.isFinite(parsedPage)) {
      setPageInputValue(String(currentPage))
      return
    }

    const targetPage = Math.min(Math.max(parsedPage, 1), totalPages)
    setPageInputValue(String(targetPage))

    if (targetPage !== currentPage) {
      pageNavigationPluginInstance.jumpToPage(targetPage - 1)
    }
  }, [currentPage, pageInputValue, pageNavigationPluginInstance, totalPages])

  const handlePageInputBlur = useCallback(() => {
    if (cancelPageInputCommitRef.current) {
      cancelPageInputCommitRef.current = false
      setPageInputValue(String(currentPage))
      setIsEditingPageInput(false)
      return
    }

    commitPageInput()
    setIsEditingPageInput(false)
  }, [commitPageInput, currentPage])

  // 包装缩放操作：先淡出，再缩放，最后居中并淡入
  const handleZoomWithFade = (zoomAction: () => void, shouldPersist = false) => {
    const container = pdfContainerRef.current
    if (!container) {
      zoomAction()
      if (shouldPersist) {
        setTimeout(() => persistScale(scaleRef.current), 0)
      }
      return
    }

    const scrollContainer = container.querySelector('.rpv-core__inner-pages') as HTMLElement
    if (!scrollContainer) {
      zoomAction()
      if (shouldPersist) {
        setTimeout(() => persistScale(scaleRef.current), 0)
      }
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
        if (shouldPersist) {
          persistScale(scaleRef.current)
        }
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

  const effectiveBrightness = pdfDimmingMode === 'brightness' ? brightnessLevel : 1
  const effectiveOverlayOpacity = pdfDimmingMode === 'overlay' ? overlayOpacity : 0

  return (
    <div ref={pdfContainerRef} className="flex-1 flex h-full overflow-hidden relative">
      {/* 书签侧边栏 */}
      {showBookmarks && (
        <div className="w-64 overflow-auto border-r border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-slate-950/60">
          <div className="flex items-center justify-between border-b border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
            <span className="text-sm font-medium text-slate-800 dark:text-slate-100">目录</span>
            <button
              onClick={() => setShowBookmarks(false)}
              className="rounded p-1 text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200"
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
      <div className="flex-1 flex flex-col overflow-hidden bg-background">
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
        <div className="relative flex-1 overflow-hidden bg-slate-100 dark:bg-slate-950">
          <div
            className="h-full transition-[filter] duration-200"
            style={{ filter: `brightness(${effectiveBrightness})` }}
          >
            <Worker workerUrl="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js">
              <Viewer
                fileUrl={pdfUrl}
                characterMap={{
                  url: 'https://unpkg.com/pdfjs-dist@3.11.174/cmaps/',
                  isCompressed: true,
                }}
                plugins={[
                  searchPluginInstance,
                  bookmarkPluginInstance,
                  pageNavigationPluginInstance,
                  zoomPluginInstance
                ]}
                defaultScale={1}
                onDocumentLoad={(e) => {
                  setTotalPages(e.doc.numPages)
                  const savedScale = restoreScaleRef.current ?? getStoredPdfScale()
                  const savedRatio = restoreScrollRatioRef.current ?? getStoredPdfReadingPosition(paperId, pdfLang)
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
          {effectiveOverlayOpacity > 0 && (
            <div
              className="absolute inset-0 pointer-events-none z-10 transition-colors duration-200"
              style={{ backgroundColor: `rgba(15, 23, 42, ${effectiveOverlayOpacity})` }}
            />
          )}
        </div>

        {/* 底部浮动工具栏 */}
        <div className="absolute bottom-4 left-1/2 transform -translate-x-1/2 z-40">
          {showDimmingControls && (
            <div className="absolute bottom-full left-1/2 mb-3 w-[360px] -translate-x-1/2 rounded-2xl border border-slate-200 bg-white/95 px-4 py-3 shadow-xl backdrop-blur dark:border-slate-700 dark:bg-slate-900/95">
              <div className="mb-3 flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-slate-800 dark:text-slate-100">实验性调光</p>
                  <p className="text-xs text-slate-500 dark:text-slate-400">对比 Overlay 和 Brightness 两种方案</p>
                </div>
                <button
                  onClick={() => setShowDimmingControls(false)}
                  className="rounded-md p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-200"
                  title="关闭调光面板"
                >
                  <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>

              <div className="mb-3 flex items-center gap-1 rounded-xl bg-slate-100 p-1 dark:bg-slate-800">
                {([
                  { key: 'off', label: '关闭' },
                  { key: 'overlay', label: 'Overlay' },
                  { key: 'brightness', label: 'Brightness' },
                ] as const).map((option) => (
                  <button
                    key={option.key}
                    onClick={() => handleDimmingModeChange(option.key)}
                    className={`flex-1 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                      pdfDimmingMode === option.key
                        ? 'bg-white text-slate-800 shadow-sm dark:bg-slate-700 dark:text-slate-100'
                        : 'text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200'
                    }`}
                  >
                    {option.label}
                  </button>
                ))}
              </div>

              {pdfDimmingMode === 'overlay' && (
                <div className="space-y-2">
                  <p className="text-xs font-medium text-slate-600 dark:text-slate-300">遮罩强度</p>
                  <div className="flex flex-wrap gap-2">
                    {OVERLAY_LEVELS.map((value) => (
                      <button
                        key={value}
                        onClick={() => handleOverlayOpacityChange(value)}
                        className={`rounded-full px-3 py-1 text-xs transition-colors ${
                          overlayOpacity === value
                            ? 'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900'
                            : 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700'
                        }`}
                      >
                        {Math.round(value * 100)}%
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {pdfDimmingMode === 'brightness' && (
                <div className="space-y-2">
                  <p className="text-xs font-medium text-slate-600 dark:text-slate-300">亮度档位</p>
                  <div className="flex flex-wrap gap-2">
                    {BRIGHTNESS_LEVELS.map((value) => (
                      <button
                        key={value}
                        onClick={() => handleBrightnessLevelChange(value)}
                        className={`rounded-full px-3 py-1 text-xs transition-colors ${
                          brightnessLevel === value
                            ? 'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900'
                            : 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700'
                        }`}
                      >
                        {Math.round(value * 100)}%
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          <div className="flex items-center gap-2 rounded-full border border-slate-200 bg-white/95 px-4 py-2 shadow-lg backdrop-blur dark:border-slate-700 dark:bg-slate-900/95">
            {/* 目录按钮 */}
            <button
              onClick={() => setShowBookmarks(!showBookmarks)}
              className={`rounded-full p-2 transition-colors ${showBookmarks ? 'bg-blue-100 text-blue-600 dark:bg-blue-950/40 dark:text-blue-300' : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'}`}
              title="目录"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h7" />
              </svg>
            </button>

            {/* 搜索按钮 */}
            <button
              onClick={() => setShowSearch(true)}
              className="rounded-full p-2 text-slate-600 transition-colors hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
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
                className="rounded-full bg-blue-100 p-2 text-blue-600 transition-colors hover:bg-blue-200 dark:bg-blue-950/40 dark:text-blue-300 dark:hover:bg-blue-900/50"
                title="返回引用位置"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 15L3 9m0 0l6-6M3 9h12a6 6 0 010 12h-3" />
                </svg>
              </button>
            )}

            <div className="h-6 w-px bg-slate-200 dark:bg-slate-700" />

            {/* 缩放控制 */}
            <ZoomOut>
              {(props) => (
                <button
                  onClick={() => handleZoomWithFade(props.onClick, true)}
                  className="rounded-full p-2 text-slate-600 transition-colors hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
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
                  <span className="min-w-[50px] text-center text-sm text-slate-600 dark:text-slate-300">
                    {Math.round(props.scale * 100)}%
                  </span>
                )
              }}
            </CurrentScale>

            <ZoomIn>
              {(props) => (
                <button
                  onClick={() => handleZoomWithFade(props.onClick, true)}
                  className="rounded-full p-2 text-slate-600 transition-colors hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
                  title="放大"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                  </svg>
                </button>
              )}
            </ZoomIn>

            <div className="h-6 w-px bg-slate-200 dark:bg-slate-700" />

            {/* 页码跳转 */}
            <div className="flex items-center gap-1 text-sm text-slate-600 dark:text-slate-300">
              <input
                type="text"
                inputMode="numeric"
                pattern="[0-9]*"
                value={pageInputValue}
                onFocus={(e) => {
                  setIsEditingPageInput(true)
                  e.target.select()
                }}
                onChange={(e) => {
                  const nextValue = e.target.value.replace(/\D/g, '')
                  setPageInputValue(nextValue)
                }}
                onBlur={handlePageInputBlur}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.currentTarget.blur()
                    return
                  }

                  if (e.key === 'Escape') {
                    cancelPageInputCommitRef.current = true
                    e.currentTarget.blur()
                  }
                }}
                className="w-12 rounded-md border border-slate-200 bg-white px-2 py-1 text-center text-sm text-slate-700 outline-none transition-colors focus:border-blue-400 focus:ring-2 focus:ring-blue-100 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 dark:focus:border-blue-500 dark:focus:ring-blue-950"
                aria-label="输入页码跳转"
              />
              <span>/ {totalPages}</span>
            </div>

            <button
              onClick={() => setShowDimmingControls(prev => !prev)}
              className={`px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
                pdfDimmingMode === 'off'
                  ? 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700'
                  : 'bg-amber-100 text-amber-700 hover:bg-amber-200 dark:bg-amber-950/40 dark:text-amber-300 dark:hover:bg-amber-900/50'
              }`}
              title="实验性调光"
            >
              {pdfDimmingMode === 'off'
                ? '调光'
                : `${pdfDimmingMode === 'overlay' ? 'Overlay' : 'Brightness'} ${
                    Math.round((pdfDimmingMode === 'overlay' ? overlayOpacity : brightnessLevel) * 100)
                  }%`}
            </button>

            {/* 语言切换 */}
            <div className="h-6 w-px bg-slate-200 dark:bg-slate-700" />
            <div className="flex items-center gap-0.5">
              <button
                onClick={() => {
                  if (pdfLang === 'en') return
                  restoreScaleRef.current = scaleRef.current
                  const currentRatio = persistReadingPosition(paperId, pdfLang)
                  if (currentRatio !== null) {
                    restoreScrollRatioRef.current = currentRatio
                  }
                  setPdfLang('en')
                  savePdfLang(paperId, 'en')
                }}
                className={`px-2.5 py-1 rounded-full text-xs font-medium transition-colors ${
                  pdfLang === 'en'
                    ? 'bg-blue-100 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300'
                    : 'text-slate-500 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800'
                }`}
              >
                EN
              </button>
              <button
                onClick={() => {
                  if (translations.zh) {
                    if (pdfLang === 'zh') return
                    restoreScaleRef.current = scaleRef.current
                    const currentRatio = persistReadingPosition(paperId, pdfLang)
                    if (currentRatio !== null) {
                      restoreScrollRatioRef.current = currentRatio
                    }
                    setPdfLang('zh')
                    savePdfLang(paperId, 'zh')
                  } else {
                    handleTriggerTranslation(paperId)
                  }
                }}
                className={`px-2.5 py-1 rounded-full text-xs font-medium transition-colors ${
                  pdfLang === 'zh'
                    ? 'bg-blue-100 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300'
                    : 'text-slate-500 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800'
                }`}
              >
                中文
              </button>
            </div>
            {/* 翻译进度 */}
            {translateStatus && translateStatus.status !== 'finished' && translateStatus.status !== 'none' && (
              <div className="flex items-center gap-1.5 text-xs max-w-[200px]">
                {translateStatus.status === 'polling' && (
                  <>
                    <svg className="h-3 w-3 animate-spin text-blue-500 shrink-0" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
                    </svg>
                    <span className="text-blue-600 dark:text-blue-400 truncate">{translateStatus.info || '翻译中…'}</span>
                  </>
                )}
                {translateStatus.status === 'pending' && (
                  <span className="text-slate-500 dark:text-slate-400 truncate">等待翻译…</span>
                )}
                {(translateStatus.status === 'failed' || translateStatus.status === 'error') && (
                  <span className="text-red-500 dark:text-red-400 truncate" title={translateStatus.error}>
                    {translateStatus.error || '翻译失败'}
                  </span>
                )}
                {translateStatus.status === 'needs_login' && (
                  <span className="text-amber-600 dark:text-amber-400 truncate" title={translateStatus.error}>
                    需要配置 Cookie
                  </span>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
