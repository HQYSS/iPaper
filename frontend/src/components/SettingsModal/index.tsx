import { useState, useEffect, useCallback } from 'react'
import { X, Eye, EyeOff, Settings, Loader2, CheckCircle, ExternalLink, Sun, Moon, Monitor, Globe, Shield, User, Trash2, Copy, LogOut, Key, ChevronDown, ChevronUp } from 'lucide-react'
import { getConfig, updateLLMConfig, updateSyncConfig, updateHjfyCookie, listUsers, deleteUser, getInviteCode, updateInviteCode, changePassword, listSyncDevices, createSyncDevice, revokeSyncDevice, type AuthUser, type SyncDevice, type SyncDeviceTokenResponse } from '../../services/api'
import { useAuthStore } from '../../stores/authStore'
import { useToastStore } from '../../stores/toastStore'
import { cn } from '../../lib/utils'
import { env } from '../../services/env'

type ThemeMode = 'light' | 'dark' | 'system'
type SettingsTab = 'general' | 'account' | 'admin'

interface SettingsModalProps {
  open: boolean
  onClose: () => void
  onConfigured?: () => void
  themeMode: ThemeMode
  onThemeModeChange: (themeMode: ThemeMode) => void
}

export function SettingsModal({ open, onClose, onConfigured, themeMode, onThemeModeChange }: SettingsModalProps) {
  const { addToast } = useToastStore()
  const { user: currentUser } = useAuthStore()
  const [activeTab, setActiveTab] = useState<SettingsTab>('general')
  const [apiKey, setApiKey] = useState('')
  const [showKey, setShowKey] = useState(false)
  const [model, setModel] = useState('')
  const [isConfigured, setIsConfigured] = useState(false)
  const [syncRole, setSyncRole] = useState<'server' | 'client' | 'off'>('server')
  const [syncUrl, setSyncUrl] = useState('')
  const [syncToken, setSyncToken] = useState('')
  const [syncConfigured, setSyncConfigured] = useState(false)
  const [hjfyCookie, setHjfyCookie] = useState('')
  const [hjfyConfigured, setHjfyConfigured] = useState(false)
  const [hjfySaving, setHjfySaving] = useState(false)
  const [hjfySaveSuccess, setHjfySaveSuccess] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [saveSuccess, setSaveSuccess] = useState(false)

  const loadConfig = useCallback(async () => {
    setIsLoading(true)
    try {
      const config = await getConfig()
      setModel(config.llm.model)
      setIsConfigured(config.llm.api_key_configured)
      setApiKey('')
      setSyncRole(config.sync.role)
      setSyncUrl(config.sync.url || '')
      setSyncToken('')
      setSyncConfigured(config.sync.token_configured)
      setHjfyConfigured(config.hjfy_cookie_configured)
      setHjfyCookie('')
    } catch {
      addToast('error', '加载配置失败')
    } finally {
      setIsLoading(false)
    }
  }, [addToast])

  useEffect(() => {
    if (open) {
      loadConfig()
      setSaveSuccess(false)
      setHjfySaveSuccess(false)
      setActiveTab('general')
    }
  }, [open, loadConfig])

  useEffect(() => {
    if (!open) return
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleEsc)
    return () => window.removeEventListener('keydown', handleEsc)
  }, [open, onClose])

  const handleSaveHjfyCookie = async () => {
    const raw = hjfyCookie.trim()
    if (!raw) return
    const cookieValue = raw.startsWith('session=') ? raw : `session=${raw}`
    setHjfySaving(true)
    setHjfySaveSuccess(false)
    try {
      await updateHjfyCookie(cookieValue)
      setHjfyConfigured(true)
      setHjfySaveSuccess(true)
      setHjfyCookie('')
      addToast('success', '幻觉翻译登录成功')
    } catch (e) {
      const msg = e instanceof Error ? e.message : ''
      addToast('error', msg.includes('无效') || msg.includes('过期') ? 'Cookie 无效或已过期' : '保存失败')
    } finally {
      setHjfySaving(false)
    }
  }

  const handleSave = async () => {
    const trimmedApiKey = apiKey.trim()
    const trimmedSyncToken = syncToken.trim()
    const syncChanged = syncRole === 'client' && Boolean(trimmedSyncToken)

    if (!trimmedApiKey && !syncChanged) return

    setIsSaving(true)
    setSaveSuccess(false)
    try {
      if (trimmedApiKey) {
        await updateLLMConfig({ api_key: trimmedApiKey })
        setIsConfigured(true)
        setApiKey('')
      }
      if (syncChanged) {
        await updateSyncConfig({
          ...(trimmedSyncToken ? { sync_token: trimmedSyncToken } : {}),
        })
        setSyncConfigured(Boolean(trimmedSyncToken))
        setSyncToken('')
      }
      setSaveSuccess(true)
      addToast('success', '本地配置已保存')
      onConfigured?.()
    } catch {
      addToast('error', '保存失败，请重试')
    } finally {
      setIsSaving(false)
    }
  }

  const handleClearSyncToken = async () => {
    if (syncRole !== 'client') return
    setIsSaving(true)
    try {
      await updateSyncConfig({ clear_sync_token: true })
      setSyncConfigured(false)
      setSyncToken('')
      addToast('success', '同步凭证已清除')
    } catch {
      addToast('error', '清除同步凭证失败')
    } finally {
      setIsSaving(false)
    }
  }

  if (!open) return null

  const syncRoleLabel = syncRole === 'client' ? '同步客户端' : syncRole === 'server' ? '被动同步服务端' : '同步已禁用'

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{
        // 移动端 safe area 兜底：刘海/灵动岛和 home indicator 区域不能被弹窗占用，否则 X
        // 按钮和底部按钮按不到。1rem 是普通屏的最小留白。
        paddingTop: 'max(1rem, env(safe-area-inset-top))',
        paddingBottom: 'max(1rem, env(safe-area-inset-bottom))',
        paddingLeft: 'env(safe-area-inset-left)',
        paddingRight: 'env(safe-area-inset-right)',
      }}
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm animate-in fade-in duration-200"
        onClick={onClose}
      />

      {/* Modal —— 合并外层和卡片为一层，max-h-full + overflow-hidden + flex column
          让弹窗高度严格被父容器（屏幕 - safe area）限制，超出部分由内部 scroll 容器消化。
          原先两层嵌套会让内层卡片按内容撑大、绕过外层 max-h-full 溢出到屏幕外。 */}
      <div className="relative w-full max-w-lg mx-4 max-h-full bg-white dark:bg-slate-900 rounded-2xl shadow-2xl border border-slate-200/60 dark:border-slate-700/60 overflow-hidden flex flex-col animate-in zoom-in-95 fade-in duration-200">
          {/* Header（钉顶） */}
          <div className="relative px-6 pt-6 pb-4 flex-shrink-0">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-500 flex items-center justify-center shadow-lg shadow-indigo-500/20">
                <Settings className="w-5 h-5 text-white" />
              </div>
              <div>
                <h2 className="text-lg font-semibold text-slate-800 dark:text-slate-100">设置</h2>
                <p className="text-xs text-slate-400 mt-0.5">本地配置、账号信息与云端同步</p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="absolute right-4 top-4 p-2 rounded-xl text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:text-slate-300 dark:hover:bg-slate-800 transition-all"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Tab bar（钉顶） */}
          <div className="flex border-b border-slate-200 dark:border-slate-700 px-6 gap-1 flex-shrink-0">
            {([
              { key: 'general' as const, label: '通用', icon: Settings },
              { key: 'account' as const, label: '账号', icon: User },
              ...(currentUser?.is_admin ? [{ key: 'admin' as const, label: '管理', icon: Shield }] : []),
            ]).map(({ key, label, icon: Icon }) => (
              <button
                key={key}
                onClick={() => setActiveTab(key)}
                className={cn(
                  'flex items-center gap-1.5 px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors',
                  activeTab === key
                    ? 'border-indigo-500 text-indigo-600 dark:text-indigo-400'
                    : 'border-transparent text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200'
                )}
              >
                <Icon className="w-3.5 h-3.5" />
                {label}
              </button>
            ))}
          </div>

          {/* 可滚动区：内容超过屏幕时这里出滚动条，Header / Tab bar 永远固定 */}
          <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain">
          {isLoading ? (
            <div className="flex items-center justify-center py-16">
              <Loader2 className="w-6 h-6 animate-spin text-indigo-500" />
            </div>
          ) : activeTab === 'account' ? (
            <AccountTab onClose={onClose} />
          ) : activeTab === 'admin' ? (
            <AdminTab />
          ) : (
            <>
              {/* Body */}
              <div className="px-6 pb-2 space-y-5">
                {/* Status indicator */}
                <div className={cn('grid gap-2', env.isElectron ? 'sm:grid-cols-2' : 'sm:grid-cols-1')}>
                  <div className={cn(
                    'flex items-center gap-3 px-4 py-3 rounded-xl text-sm',
                    isConfigured
                      ? 'bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-400'
                      : 'bg-amber-50 dark:bg-amber-950/30 text-amber-700 dark:text-amber-400'
                  )}>
                    <div className={cn(
                      'w-2 h-2 rounded-full',
                      isConfigured
                        ? 'bg-emerald-500 shadow-sm shadow-emerald-500/50'
                        : 'bg-amber-500 shadow-sm shadow-amber-500/50 animate-pulse'
                    )} />
                    {isConfigured ? '本地 API Key 已配置' : '需要配置本地 API Key'}
                  </div>
                  {env.isElectron && (
                    <div className={cn(
                      'flex items-center gap-3 px-4 py-3 rounded-xl text-sm',
                      syncRole === 'client' && syncConfigured
                        ? 'bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-400'
                        : 'bg-slate-50 dark:bg-slate-800/50 text-slate-500 dark:text-slate-400'
                    )}>
                      <div className={cn(
                        'w-2 h-2 rounded-full',
                        syncRole === 'client' && syncConfigured
                          ? 'bg-emerald-500 shadow-sm shadow-emerald-500/50'
                          : 'bg-slate-400'
                      )} />
                      {syncRole === 'client'
                        ? (syncConfigured ? '设备同步已连接' : '设备同步未连接')
                        : `当前角色：${syncRoleLabel}`}
                    </div>
                  )}
                </div>

                {/* API Key */}
                <div>
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                    API Key
                  </label>
                  <div className="relative">
                    <input
                      type={showKey ? 'text' : 'password'}
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleSave()}
                      placeholder={isConfigured ? '输入新 Key 以更换' : 'sk-or-v1-...'}
                      className="w-full pl-4 pr-12 py-3 text-sm rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 focus:outline-none focus:ring-2 focus:ring-indigo-500/40 focus:border-indigo-500 transition-all placeholder:text-slate-400"
                      autoFocus
                    />
                    <button
                      type="button"
                      onClick={() => setShowKey(!showKey)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-200/50 dark:hover:text-slate-300 dark:hover:bg-slate-700/50 transition-all"
                    >
                      {showKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                  <a
                    href="https://openrouter.ai/settings/keys"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 mt-2 text-xs text-indigo-500 hover:text-indigo-600 transition-colors"
                  >
                    获取 OpenRouter API Key
                    <ExternalLink className="w-3 h-3" />
                  </a>
                </div>

                {/* Model (read-only) */}
                <div>
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                    模型
                  </label>
                  <div className="flex items-center px-4 py-3 text-sm rounded-xl bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700 text-slate-500 dark:text-slate-400">
                    <span className="font-mono text-xs">{model}</span>
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                    云端同步
                  </label>
                  <div className="space-y-2">
                    <div className="px-3 py-2 rounded-lg bg-slate-50 dark:bg-slate-800/50 text-xs text-slate-500 dark:text-slate-400 leading-relaxed">
                      {syncRole === 'client'
                        ? '当前这台本地 Electron 后端会主动把本地数据同步到固定云端。普通登录 token 不用于同步；这里只需要一枚专用的设备同步凭证。'
                        : syncRole === 'server'
                          ? '当前后端角色是被动同步服务端：它只响应 `/api/sync/*` 请求，不会主动轮询、也不会自动推送任何本地改动。'
                          : '当前后端已禁用主动同步能力。'}
                    </div>
                    <div className="flex items-center justify-between px-4 py-3 text-sm rounded-xl bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700">
                      <span className="text-slate-500 dark:text-slate-400">{`同步角色：${syncRoleLabel}`}</span>
                      <code className="text-xs font-mono text-slate-700 dark:text-slate-300">{syncUrl}</code>
                    </div>
                    {env.isElectron && syncRole === 'client' ? (
                      <>
                        <input
                          type="password"
                          value={syncToken}
                          onChange={(e) => setSyncToken(e.target.value)}
                          placeholder={syncConfigured ? '如需轮换设备同步凭证，请输入新 token' : '粘贴云端签发的设备同步凭证'}
                          className="w-full px-4 py-3 text-sm rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 focus:outline-none focus:ring-2 focus:ring-indigo-500/40 focus:border-indigo-500 transition-all placeholder:text-slate-400"
                        />
                        <div className="flex items-center justify-between gap-3">
                          <p className="text-xs text-slate-400 leading-relaxed">
                            设备凭证需要在云端网页的管理员页中生成；它只允许访问 `/api/sync/*`，可单独吊销。
                          </p>
                          {syncConfigured && (
                            <button
                              type="button"
                              onClick={handleClearSyncToken}
                              disabled={isSaving}
                              className="px-3 py-2 text-xs font-medium rounded-xl border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 transition-all whitespace-nowrap"
                            >
                              断开同步
                            </button>
                          )}
                        </div>
                      </>
                    ) : (
                      <p className="text-xs text-slate-400 leading-relaxed">
                        {syncRole === 'server'
                          ? '你当前在云端服务端。若要让某台本地 Electron 同步到这里，请到下方管理员页的“云端同步设备”里生成一枚设备凭证，再粘贴到那台本地 Electron。'
                          : '当前页面不提供主动同步客户端配置。'}
                      </p>
                    )}
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                    外观主题
                  </label>
                  <div className="grid grid-cols-3 gap-2">
                    {([
                      { key: 'light', label: '浅色', icon: Sun },
                      { key: 'dark', label: '深色', icon: Moon },
                      { key: 'system', label: '跟随系统', icon: Monitor },
                    ] as const).map((option) => {
                      const Icon = option.icon
                      const isActive = themeMode === option.key
                      return (
                        <button
                          key={option.key}
                          type="button"
                          onClick={() => onThemeModeChange(option.key)}
                          className={cn(
                            'flex items-center justify-center gap-2 rounded-xl border px-3 py-3 text-sm transition-all',
                            isActive
                              ? 'border-indigo-500 bg-indigo-50 text-indigo-700 dark:border-indigo-400 dark:bg-indigo-950/40 dark:text-indigo-300'
                              : 'border-slate-200 bg-slate-50 text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-800/50 dark:text-slate-300 dark:hover:bg-slate-800'
                          )}
                        >
                          <Icon className="w-4 h-4" />
                          <span>{option.label}</span>
                        </button>
                      )
                    })}
                  </div>
                </div>

                {/* 幻觉翻译 */}
                <div>
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                    论文翻译
                    <span className="ml-1.5 text-xs font-normal text-slate-400">由 hjfy.top 提供，大部分论文无需登录</span>
                  </label>
                  <div className={cn(
                    "flex items-center gap-2 mb-3 px-3 py-2 rounded-lg text-xs",
                    hjfyConfigured
                      ? "bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-400"
                      : "bg-slate-50 dark:bg-slate-800/50 text-slate-500 dark:text-slate-400"
                  )}>
                    <Globe className="w-3.5 h-3.5 shrink-0" />
                    {hjfyConfigured ? '已登录幻觉翻译' : '未登录（遇到未翻译的论文时需要）'}
                  </div>
                  <div className="space-y-2">
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={() => window.open('https://hjfy.top', '_blank', 'noopener')}
                        className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 transition-all"
                      >
                        <ExternalLink className="w-3.5 h-3.5" />
                        1. 打开 hjfy.top 并登录
                      </button>
                    </div>
                    <div className="px-3 py-2 rounded-lg bg-slate-50 dark:bg-slate-800/50 text-xs text-slate-500 dark:text-slate-400 leading-relaxed">
                      2. 登录后按 <kbd className="px-1.5 py-0.5 rounded bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-200 font-mono text-[10px]">F12</kbd> 打开 DevTools → <span className="text-slate-700 dark:text-slate-200">Application</span> → <span className="text-slate-700 dark:text-slate-200">Cookies</span> → hjfy.top → 复制 <span className="text-slate-700 dark:text-slate-200 font-mono">session</span> 的值
                    </div>
                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={hjfyCookie}
                        onChange={(e) => setHjfyCookie(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' && hjfyCookie.trim()) {
                            e.preventDefault()
                            handleSaveHjfyCookie()
                          }
                        }}
                        placeholder="3. 粘贴 session 值"
                        className="flex-1 pl-3 pr-3 py-2.5 text-sm font-mono rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 focus:outline-none focus:ring-2 focus:ring-indigo-500/40 focus:border-indigo-500 transition-all placeholder:text-slate-400 placeholder:font-sans"
                      />
                      <button
                        onClick={handleSaveHjfyCookie}
                        disabled={!hjfyCookie.trim() || hjfySaving}
                        className={cn(
                          "px-4 py-2.5 text-sm font-medium rounded-xl flex items-center gap-1.5 transition-all whitespace-nowrap",
                          hjfySaveSuccess
                            ? "bg-emerald-500 text-white"
                            : "bg-slate-800 text-white hover:bg-slate-700 dark:bg-slate-200 dark:text-slate-900 dark:hover:bg-slate-300",
                          (!hjfyCookie.trim() || hjfySaving) && "opacity-50 cursor-not-allowed"
                        )}
                      >
                        {hjfySaving ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : hjfySaveSuccess ? (
                          <CheckCircle className="w-3.5 h-3.5" />
                        ) : null}
                        {hjfySaveSuccess ? '已验证' : '验证并保存'}
                      </button>
                    </div>
                  </div>
                </div>
              </div>

              {/* Footer */}
              <div className="px-6 py-4 mt-2 border-t border-slate-100 dark:border-slate-800 flex gap-3">
                <button
                  onClick={onClose}
                  className="flex-1 px-4 py-2.5 text-sm font-medium rounded-xl border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800 transition-all"
                >
                  取消
                </button>
                <button
                  onClick={handleSave}
                  disabled={(!apiKey.trim() && !(syncRole === 'client' && syncToken.trim())) || isSaving}
                  className={cn(
                    "flex-1 px-4 py-2.5 text-sm font-medium rounded-xl flex items-center justify-center gap-2 transition-all",
                    saveSuccess
                      ? "bg-emerald-500 text-white"
                      : "bg-gradient-to-r from-indigo-500 to-purple-500 text-white hover:from-indigo-600 hover:to-purple-600 shadow-sm shadow-indigo-500/20",
                    (!apiKey.trim() && !(syncRole === 'client' && syncToken.trim()) || isSaving) && "opacity-50 cursor-not-allowed"
                  )}
                >
                  {isSaving ? (
                    <><Loader2 className="w-4 h-4 animate-spin" />保存中...</>
                  ) : saveSuccess ? (
                    <><CheckCircle className="w-4 h-4" />已保存</>
                  ) : (
                    '保存'
                  )}
                </button>
              </div>
            </>
          )}
          </div>
      </div>
    </div>
  )
}

function AccountTab({ onClose }: { onClose: () => void }) {
  const { user, logout } = useAuthStore()
  const { addToast } = useToastStore()
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [saving, setSaving] = useState(false)

  const handleChangePassword = async () => {
    if (!newPassword || newPassword.length < 4) {
      addToast('error', '密码至少 4 个字符')
      return
    }
    if (newPassword !== confirmPassword) {
      addToast('error', '两次密码不一致')
      return
    }
    setSaving(true)
    try {
      await changePassword(newPassword)
      addToast('success', '密码已更新')
      setNewPassword('')
      setConfirmPassword('')
    } catch {
      addToast('error', '修改密码失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="px-6 py-5 space-y-5">
      <div className="flex items-center gap-3 px-4 py-3 rounded-xl bg-slate-50 dark:bg-slate-800/50">
        <div className="w-10 h-10 rounded-full bg-indigo-100 dark:bg-indigo-950/50 flex items-center justify-center">
          <User className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
        </div>
        <div>
          <p className="text-sm font-medium text-slate-800 dark:text-slate-100">{user?.username || 'local'}</p>
          <p className="text-xs text-slate-400">{user?.is_admin ? '管理员' : '普通用户'}</p>
        </div>
      </div>

      <div className="space-y-3">
        <label className="block text-sm font-medium text-slate-700 dark:text-slate-300">修改密码</label>
        <input
          type="password"
          value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)}
          placeholder="新密码"
          className="w-full px-4 py-2.5 text-sm rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 focus:outline-none focus:ring-2 focus:ring-indigo-500/40 transition-all"
        />
        <input
          type="password"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          placeholder="确认新密码"
          onKeyDown={(e) => e.key === 'Enter' && handleChangePassword()}
          className="w-full px-4 py-2.5 text-sm rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 focus:outline-none focus:ring-2 focus:ring-indigo-500/40 transition-all"
        />
        <button
          onClick={handleChangePassword}
          disabled={!newPassword || saving}
          className={cn(
            'w-full px-4 py-2.5 text-sm font-medium rounded-xl transition-all',
            'bg-slate-800 text-white hover:bg-slate-700 dark:bg-slate-200 dark:text-slate-900 dark:hover:bg-slate-300',
            (!newPassword || saving) && 'opacity-50 cursor-not-allowed'
          )}
        >
          {saving ? <Loader2 className="w-4 h-4 animate-spin mx-auto" /> : '更新密码'}
        </button>
      </div>

      <button
        onClick={() => { logout(); onClose() }}
        className="w-full flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-medium rounded-xl border border-red-200 dark:border-red-900/50 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/30 transition-all"
      >
        <LogOut className="w-4 h-4" />
        退出登录
      </button>
    </div>
  )
}

function AdminTab() {
  const { addToast } = useToastStore()
  const [users, setUsers] = useState<AuthUser[]>([])
  const [syncDevices, setSyncDevices] = useState<SyncDevice[]>([])
  const [newDeviceName, setNewDeviceName] = useState('我的 Mac')
  const [latestIssued, setLatestIssued] = useState<SyncDeviceTokenResponse | null>(null)
  const [inviteCode, setInviteCode] = useState('')
  const [editingCode, setEditingCode] = useState('')
  const [isEditingCode, setIsEditingCode] = useState(false)
  const [showRevokedDevices, setShowRevokedDevices] = useState(false)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [userList, code, devices] = await Promise.all([listUsers(), getInviteCode(), listSyncDevices()])
      setUsers(userList)
      setSyncDevices(devices)
      setInviteCode(code)
      setEditingCode(code)
    } catch {
      addToast('error', '加载管理信息失败')
    } finally {
      setLoading(false)
    }
  }, [addToast])

  useEffect(() => { load() }, [load])

  const handleDeleteUser = async (userId: string, username: string) => {
    if (!confirm(`确定删除用户 ${username}？其所有数据将保留在服务器上。`)) return
    try {
      await deleteUser(userId)
      setUsers((prev) => prev.filter((u) => u.id !== userId))
      addToast('success', `用户 ${username} 已删除`)
    } catch (e) {
      addToast('error', (e as Error).message)
    }
  }

  const handleSaveInviteCode = async () => {
    try {
      await updateInviteCode(editingCode)
      setInviteCode(editingCode)
      setIsEditingCode(false)
      addToast('success', '邀请码已更新')
    } catch {
      addToast('error', '更新邀请码失败')
    }
  }

  const handleCopyInviteCode = () => {
    navigator.clipboard.writeText(inviteCode).then(() => addToast('success', '已复制邀请码'))
  }

  const formatDateTime = (value: string) => {
    const date = new Date(value)
    return date.toLocaleString('zh-CN', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  const handleCreateSyncDevice = async () => {
    try {
      const created = await createSyncDevice(newDeviceName.trim() || 'iPaper Electron')
      setLatestIssued(created)
      setSyncDevices((prev) => [created, ...prev])
      addToast('success', '已生成新的设备同步凭证')
    } catch {
      addToast('error', '生成设备同步凭证失败')
    }
  }

  const handleCopyLatestToken = () => {
    if (!latestIssued) return
    navigator.clipboard.writeText(latestIssued.token).then(() => addToast('success', '已复制设备同步凭证'))
  }

  const handleRevokeSyncDevice = async (deviceId: string) => {
    if (!confirm('确定吊销这个设备的同步凭证吗？吊销后该设备需要重新绑定。')) return
    try {
      await revokeSyncDevice(deviceId)
      setSyncDevices((prev) => prev.map((device) => (
        device.device_id === deviceId
          ? { ...device, revoked_at: new Date().toISOString() }
          : device
      )))
      addToast('success', '设备同步凭证已吊销')
    } catch {
      addToast('error', '吊销设备同步凭证失败')
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="w-6 h-6 animate-spin text-indigo-500" />
      </div>
    )
  }

  const activeSyncDevices = syncDevices.filter((device) => !device.revoked_at)
  const revokedSyncDevices = syncDevices.filter((device) => device.revoked_at)

  return (
    <div className="px-6 py-5 space-y-5">
      {/* Invite code */}
      <div>
        <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
          <Key className="w-3.5 h-3.5 inline mr-1.5" />
          {env.isElectron ? '本地邀请码' : '云端邀请码'}
        </label>
        <p className="mb-2 text-xs text-slate-400 leading-relaxed">
          {env.isElectron
            ? '这里只修改当前这台本地 Electron 后端的注册邀请码，不会自动同步到云端。'
            : '这里修改的是当前云端后端的注册邀请码，会直接影响网页端注册。'}
        </p>
        {isEditingCode ? (
          <div className="flex gap-2">
            <input
              type="text"
              value={editingCode}
              onChange={(e) => setEditingCode(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSaveInviteCode()}
              className="flex-1 px-3 py-2 text-sm font-mono rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 focus:outline-none focus:ring-2 focus:ring-indigo-500/40 transition-all"
              autoFocus
            />
            <button
              onClick={handleSaveInviteCode}
              className="px-3 py-2 text-sm font-medium rounded-xl bg-indigo-500 text-white hover:bg-indigo-600 transition-all"
            >
              保存
            </button>
            <button
              onClick={() => { setEditingCode(inviteCode); setIsEditingCode(false) }}
              className="px-3 py-2 text-sm font-medium rounded-xl border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800 transition-all"
            >
              取消
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700">
            <code className="flex-1 text-sm font-mono text-slate-700 dark:text-slate-300">{inviteCode || '(未设置)'}</code>
            <button onClick={handleCopyInviteCode} className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-200/50 dark:hover:bg-slate-700/50 transition-all" title="复制">
              <Copy className="w-3.5 h-3.5" />
            </button>
            <button onClick={() => setIsEditingCode(true)} className="px-2.5 py-1 text-xs font-medium rounded-lg text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-950/30 transition-all">
              修改
            </button>
          </div>
        )}
      </div>

      {env.isWeb ? (
        <div>
          <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
            已连接的本地设备
          </label>
          <p className="mb-2 text-xs text-slate-400 leading-relaxed">
            给新的本地 Electron 生成一枚专用同步凭证，再粘贴到那台设备即可完成连接。它只用于同步，不影响网页登录。
          </p>
          <div className="flex gap-2 mb-3">
            <input
              type="text"
              value={newDeviceName}
              onChange={(e) => setNewDeviceName(e.target.value)}
              placeholder="设备名称，例如 办公室 MacBook"
              className="flex-1 px-3 py-2 text-sm rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 focus:outline-none focus:ring-2 focus:ring-indigo-500/40 transition-all"
            />
            <button
              onClick={handleCreateSyncDevice}
              className="px-3 py-2 text-sm font-medium rounded-xl bg-indigo-500 text-white hover:bg-indigo-600 transition-all whitespace-nowrap"
            >
              连接新设备
            </button>
          </div>
          {latestIssued && (
            <div className="mb-3 space-y-2 px-4 py-3 rounded-xl bg-emerald-50 dark:bg-emerald-950/20 border border-emerald-200 dark:border-emerald-900/50">
              <p className="text-xs text-emerald-700 dark:text-emerald-300">
                新设备凭证只会展示这一次，请立即复制到对应的本地 Electron。
              </p>
              <div className="flex items-center gap-2">
                <code className="flex-1 text-xs font-mono text-emerald-700 dark:text-emerald-300 break-all">{latestIssued.token}</code>
                <button
                  onClick={handleCopyLatestToken}
                  className="p-1.5 rounded-lg text-emerald-700 dark:text-emerald-300 hover:bg-emerald-100 dark:hover:bg-emerald-900/40 transition-all"
                  title="复制凭证"
                >
                  <Copy className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          )}
          <div className="space-y-3">
            {activeSyncDevices.length === 0 ? (
              <div className="px-4 py-3 rounded-xl bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700 text-xs text-slate-400">
                还没有连接任何本地设备。
              </div>
            ) : (
              <div className="space-y-2">
                {activeSyncDevices.map((device) => (
                  <div key={device.device_id} className="flex items-start gap-3 px-4 py-3 rounded-xl bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="text-sm font-medium text-slate-800 dark:text-slate-100 truncate">{device.device_name}</p>
                        <span className="inline-flex items-center rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-medium text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300">
                          已连接
                        </span>
                      </div>
                      <p className="text-xs text-slate-400 mt-1">连接于 {formatDateTime(device.created_at)}</p>
                      <p className="text-xs text-slate-400">
                        {device.last_used_at ? `最近同步 ${formatDateTime(device.last_used_at)}` : '尚未开始同步'}
                      </p>
                    </div>
                    <button
                      onClick={() => handleRevokeSyncDevice(device.device_id)}
                      className="p-1.5 rounded-lg text-slate-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30 transition-all"
                      title="断开此设备"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                ))}
              </div>
            )}

            {revokedSyncDevices.length > 0 && (
              <div className="rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden">
                <button
                  type="button"
                  onClick={() => setShowRevokedDevices((prev) => !prev)}
                  className="w-full flex items-center justify-between px-4 py-3 text-sm text-slate-600 dark:text-slate-300 bg-slate-50 dark:bg-slate-800/40 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                >
                  <span>历史记录（{revokedSyncDevices.length}）</span>
                  {showRevokedDevices ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                </button>
                {showRevokedDevices && (
                  <div className="p-3 space-y-2 bg-background">
                    {revokedSyncDevices.map((device) => (
                      <div key={device.device_id} className="flex items-start gap-3 px-4 py-3 rounded-xl bg-slate-50/70 dark:bg-slate-800/30 border border-slate-200 dark:border-slate-700/70">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <p className="text-sm font-medium text-slate-700 dark:text-slate-200 truncate">{device.device_name}</p>
                            <span className="inline-flex items-center rounded-full bg-slate-200 px-2 py-0.5 text-[11px] font-medium text-slate-600 dark:bg-slate-700 dark:text-slate-300">
                              已断开
                            </span>
                          </div>
                          <p className="text-xs text-slate-400 mt-1">曾连接于 {formatDateTime(device.created_at)}</p>
                          <p className="text-xs text-slate-400">断开于 {device.revoked_at ? formatDateTime(device.revoked_at) : '未知时间'}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="px-4 py-3 rounded-xl bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700 text-xs text-slate-400 leading-relaxed">
          设备同步凭证需要在云端网页端生成和吊销；本地 Electron 这里只负责消费那枚凭证。
        </div>
      )}

      {/* Users */}
      <div>
        <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
          用户列表（{users.length}）
        </label>
        <div className="space-y-2">
          {users.map((u) => (
            <div key={u.id} className="flex items-center gap-3 px-4 py-2.5 rounded-xl bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700">
              <div className="w-8 h-8 rounded-full bg-slate-200 dark:bg-slate-700 flex items-center justify-center">
                {u.is_admin ? <Shield className="w-4 h-4 text-indigo-500" /> : <User className="w-4 h-4 text-slate-400" />}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-slate-800 dark:text-slate-100 truncate">{u.username}</p>
                <p className="text-xs text-slate-400">{u.is_admin ? '管理员' : '普通用户'}</p>
              </div>
              {!u.is_admin && (
                <button
                  onClick={() => handleDeleteUser(u.id, u.username)}
                  className="p-1.5 rounded-lg text-slate-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30 transition-all"
                  title="删除用户"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
