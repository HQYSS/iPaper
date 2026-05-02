import { useCallback, useEffect, useState } from 'react'
import { Plus, Menu, BookOpen, FileText, Sparkles, ArrowLeft } from 'lucide-react'

import { PaperLibrary } from '../PaperLibrary'
import { PdfViewer } from '../PdfViewer'
import { ChatPanel } from '../ChatPanel'
import { ProfilePanel } from '../ProfilePanel'
import { SettingsModal } from '../SettingsModal'
import { AddPaperModal } from '../AddPaperModal'
import { MobileMenu } from './MobileMenu'

import { usePaperStore } from '../../stores/paperStore'
import { useProfileStore } from '../../stores/profileStore'
import { usePreferencesStore } from '../../stores/preferencesStore'
import { useVisualViewportHeight } from '../../hooks/useDeviceLayout'
import { cn } from '../../lib/utils'

type MobileTab = 'library' | 'reading' | 'ai'
type ThemeMode = 'light' | 'dark' | 'system'

interface MobileLayoutProps {
  themeMode: ThemeMode
  onThemeModeChange: (mode: ThemeMode) => void
}

const TAB_LABELS: Record<MobileTab, string> = {
  library: '论文库',
  reading: '阅读',
  ai: 'AI',
}

export function MobileLayout({ themeMode, onThemeModeChange }: MobileLayoutProps) {
  const { selectedPaper, fetchPapers } = usePaperStore()
  const { isEvolutionOpen, openEvolution, closeEvolution } = useProfileStore()
  const loadPreferences = usePreferencesStore((s) => s.loadPreferences)

  const [activeTab, setActiveTab] = useState<MobileTab>('library')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [addPaperOpen, setAddPaperOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)

  useVisualViewportHeight()

  useEffect(() => {
    fetchPapers()
    loadPreferences()
  }, [fetchPapers, loadPreferences])

  // 选中论文后自动跳到"阅读" Tab，让用户从论文库 → 阅读的流程一气呵成
  useEffect(() => {
    if (!selectedPaper) return
    setActiveTab((tab) => (tab === 'library' ? 'reading' : tab))
  }, [selectedPaper?.arxiv_id])

  // 论文未选中时强制把"阅读 / AI" Tab 切回论文库（避免点空 tab 卡住）
  useEffect(() => {
    if (!selectedPaper && activeTab !== 'library') {
      setActiveTab('library')
    }
  }, [selectedPaper, activeTab])

  const handleOpenAddPaper = useCallback(() => setAddPaperOpen(true), [])
  const handleOpenSettings = useCallback(() => {
    setMenuOpen(false)
    setSettingsOpen(true)
  }, [])
  const handleOpenEvolution = useCallback(() => {
    setMenuOpen(false)
    if (selectedPaper) openEvolution(selectedPaper.arxiv_id, null)
  }, [selectedPaper, openEvolution])

  if (isEvolutionOpen) {
    return (
      <div className="fixed inset-0 z-40 bg-background flex flex-col">
        <ProfilePanel onClose={closeEvolution} />
      </div>
    )
  }

  const downloadStatus = selectedPaper?.download_status ?? 'ready'
  const paperReady = !selectedPaper || downloadStatus === 'ready'

  return (
    <div
      className="mobile-app-shell flex flex-col bg-background text-foreground overflow-hidden"
      style={{
        // 高度由 .mobile-app-shell 在 index.css 里按 display-mode 切换：
        // - 浏览器：100svh（避开 Safari 工具栏动画）
        // - PWA standalone：100dvh（iOS svh 在 PWA 下会扣 safe-area-bottom，dvh 不会）
        // 键盘弹起的视口适配靠 ChatPanel 内部按需消费 --visual-vh，不在外壳层处理。
        paddingTop: 'env(safe-area-inset-top)',
      }}
    >
      <MobileTopBar
        activeTab={activeTab}
        title={selectedPaper?.title ?? null}
        onOpenMenu={() => setMenuOpen(true)}
        onOpenAddPaper={handleOpenAddPaper}
        onBackToLibrary={() => setActiveTab('library')}
      />

      <main className="flex-1 min-h-0 overflow-hidden relative">
        <div className={cn('absolute inset-0', activeTab === 'library' ? 'block' : 'hidden')}>
          <PaperLibrary
            onOpenSettings={handleOpenSettings}
            onOpenAddPaper={handleOpenAddPaper}
            hideBottomActions
          />
        </div>

        <div className={cn('absolute inset-0', activeTab === 'reading' ? 'block' : 'hidden')}>
          {selectedPaper ? (
            paperReady ? (
              <PdfViewer paperId={selectedPaper.arxiv_id} sourceType={selectedPaper.source_type} mobileMode />
            ) : (
              <PaperNotReadyHint status={downloadStatus} />
            )
          ) : (
            <EmptyHint
              title="还没有选论文"
              hint="点底部「论文库」选一篇，或右上角「+」添加新论文"
            />
          )}
        </div>

        <div className={cn('absolute inset-0', activeTab === 'ai' ? 'block' : 'hidden')}>
          {selectedPaper && paperReady ? (
            <ChatPanel
              paperId={selectedPaper.arxiv_id}
              onOpenEvolution={handleOpenEvolution}
            />
          ) : (
            <EmptyHint
              title="还没法对话"
              hint="先在「论文库」里选一篇下载完成的论文，再回到这里和 AI 聊"
            />
          )}
        </div>
      </main>

      <MobileBottomTabs
        activeTab={activeTab}
        canEnterReading={!!selectedPaper}
        canEnterAi={!!selectedPaper && paperReady}
        onTabChange={setActiveTab}
      />

      <SettingsModal
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        themeMode={themeMode}
        onThemeModeChange={onThemeModeChange}
      />
      <AddPaperModal open={addPaperOpen} onClose={() => setAddPaperOpen(false)} />
      <MobileMenu
        open={menuOpen}
        onClose={() => setMenuOpen(false)}
        canOpenEvolution={!!selectedPaper && paperReady}
        onOpenSettings={handleOpenSettings}
        onOpenEvolution={handleOpenEvolution}
      />
    </div>
  )
}

interface MobileTopBarProps {
  activeTab: MobileTab
  title: string | null
  onOpenMenu: () => void
  onOpenAddPaper: () => void
  onBackToLibrary: () => void
}

function MobileTopBar({ activeTab, title, onOpenMenu, onOpenAddPaper, onBackToLibrary }: MobileTopBarProps) {
  const showBack = activeTab !== 'library'
  const headerTitle = activeTab === 'library' ? 'iPaper' : (title || TAB_LABELS[activeTab])

  return (
    <header className="flex-shrink-0 h-12 px-2 flex items-center gap-1 border-b border-border bg-background">
      {showBack ? (
        <button
          type="button"
          onClick={onBackToLibrary}
          className="flex-shrink-0 w-10 h-10 flex items-center justify-center rounded-lg active:bg-accent transition-colors text-foreground"
          aria-label="返回论文库"
        >
          <ArrowLeft className="w-5 h-5" />
        </button>
      ) : (
        <button
          type="button"
          onClick={onOpenMenu}
          className="flex-shrink-0 w-10 h-10 flex items-center justify-center rounded-lg active:bg-accent transition-colors text-foreground"
          aria-label="菜单"
        >
          <Menu className="w-5 h-5" />
        </button>
      )}

      <h1 className="flex-1 min-w-0 text-base font-medium truncate text-center px-1">{headerTitle}</h1>

      <button
        type="button"
        onClick={onOpenAddPaper}
        className="flex-shrink-0 w-10 h-10 flex items-center justify-center rounded-lg active:bg-accent transition-colors text-foreground"
        aria-label="添加论文"
      >
        <Plus className="w-5 h-5" />
      </button>
    </header>
  )
}

interface MobileBottomTabsProps {
  activeTab: MobileTab
  canEnterReading: boolean
  canEnterAi: boolean
  onTabChange: (tab: MobileTab) => void
}

function MobileBottomTabs({ activeTab, canEnterReading, canEnterAi, onTabChange }: MobileBottomTabsProps) {
  const tabs: Array<{ id: MobileTab; label: string; icon: typeof BookOpen; enabled: boolean }> = [
    { id: 'library', label: '论文库', icon: BookOpen, enabled: true },
    { id: 'reading', label: '阅读', icon: FileText, enabled: canEnterReading },
    { id: 'ai', label: 'AI', icon: Sparkles, enabled: canEnterAi },
  ]

  return (
    <nav
      className="flex-shrink-0 border-t border-border bg-background"
      style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
    >
      <div className="grid grid-cols-3 h-14">
        {tabs.map((tab) => {
          const Icon = tab.icon
          const isActive = activeTab === tab.id
          const disabled = !tab.enabled
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => tab.enabled && onTabChange(tab.id)}
              disabled={disabled}
              className={cn(
                'flex flex-col items-center justify-center gap-0.5 transition-colors',
                isActive && 'text-purple-600 dark:text-purple-400',
                !isActive && !disabled && 'text-muted-foreground active:text-foreground',
                disabled && 'text-muted-foreground/40 cursor-not-allowed'
              )}
              aria-current={isActive ? 'page' : undefined}
            >
              <Icon className={cn('w-5 h-5', isActive && 'stroke-[2.4]')} />
              <span className="text-[11px] font-medium">{tab.label}</span>
            </button>
          )
        })}
      </div>
    </nav>
  )
}

function EmptyHint({ title, hint }: { title: string; hint: string }) {
  return (
    <div className="h-full flex items-center justify-center px-8 text-center">
      <div className="max-w-xs">
        <h2 className="text-lg font-medium mb-2">{title}</h2>
        <p className="text-sm text-muted-foreground leading-relaxed">{hint}</p>
      </div>
    </div>
  )
}

function PaperNotReadyHint({ status }: { status: string }) {
  if (status === 'downloading') {
    return (
      <EmptyHint
        title="正在下载 PDF…"
        hint="下载完成后这里会自动打开论文，可以先回论文库添加更多。"
      />
    )
  }
  if (status === 'failed') {
    return (
      <EmptyHint
        title="PDF 下载失败"
        hint="多数是 arXiv 速率限制或网络抖动，回论文库点重试通常可恢复。"
      />
    )
  }
  return <EmptyHint title="论文未就绪" hint="请稍候…" />
}
