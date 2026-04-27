import { useEffect } from 'react'
import { Settings, Sparkles, LogOut, X } from 'lucide-react'

import { useAuthStore } from '../../stores/authStore'
import { cn } from '../../lib/utils'

interface MobileMenuProps {
  open: boolean
  canOpenEvolution: boolean
  onClose: () => void
  onOpenSettings: () => void
  onOpenEvolution: () => void
}

/**
 * 顶栏左上角菜单按钮唤起的全屏抽屉。
 * 桌面端这些按钮散落在 PaperLibrary / 顶栏，移动端集中收纳到一个 Sheet 里。
 */
export function MobileMenu({
  open,
  canOpenEvolution,
  onClose,
  onOpenSettings,
  onOpenEvolution,
}: MobileMenuProps) {
  const logout = useAuthStore((s) => s.logout)
  const user = useAuthStore((s) => s.user)

  useEffect(() => {
    if (!open) return
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden
      />
      <aside
        className="fixed left-0 top-0 bottom-0 z-50 w-72 max-w-[80vw] bg-background border-r border-border shadow-xl flex flex-col"
        style={{
          paddingTop: 'env(safe-area-inset-top)',
          paddingBottom: 'env(safe-area-inset-bottom)',
        }}
        role="dialog"
        aria-modal="true"
      >
        <div className="h-12 px-2 flex items-center justify-between border-b border-border">
          <span className="text-base font-medium pl-2">iPaper</span>
          <button
            type="button"
            onClick={onClose}
            className="w-10 h-10 flex items-center justify-center rounded-lg active:bg-accent text-foreground"
            aria-label="关闭菜单"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {user?.username && (
          <div className="px-4 pt-4 text-xs text-muted-foreground">已登录为 {user.username}</div>
        )}

        <nav className="flex-1 overflow-y-auto py-2">
          <MenuItem icon={Settings} label="设置" onClick={onOpenSettings} />
          <MenuItem
            icon={Sparkles}
            label="阅读进化"
            description={canOpenEvolution ? undefined : '先选一篇论文再进入'}
            disabled={!canOpenEvolution}
            onClick={onOpenEvolution}
          />
        </nav>

        <div className="border-t border-border p-2">
          <MenuItem
            icon={LogOut}
            label="退出登录"
            onClick={() => {
              onClose()
              logout()
            }}
          />
        </div>
      </aside>
    </>
  )
}

interface MenuItemProps {
  icon: typeof Settings
  label: string
  description?: string
  disabled?: boolean
  onClick: () => void
}

function MenuItem({ icon: Icon, label, description, disabled, onClick }: MenuItemProps) {
  return (
    <button
      type="button"
      onClick={() => !disabled && onClick()}
      disabled={disabled}
      className={cn(
        'w-full flex items-center gap-3 px-4 py-3 text-left transition-colors',
        disabled
          ? 'text-muted-foreground/50 cursor-not-allowed'
          : 'text-foreground active:bg-accent'
      )}
    >
      <Icon className="w-5 h-5 flex-shrink-0" />
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium">{label}</div>
        {description && (
          <div className="text-[11px] text-muted-foreground mt-0.5">{description}</div>
        )}
      </div>
    </button>
  )
}
