import { useState, useEffect, useCallback } from 'react'
import { X, Eye, EyeOff, Settings, Loader2, CheckCircle, ExternalLink, Sun, Moon, Monitor, Globe, Shield, User, Trash2, Copy, LogOut, Key } from 'lucide-react'
import { getConfig, updateLLMConfig, updateHjfyCookie, listUsers, deleteUser, getInviteCode, updateInviteCode, changePassword, type AuthUser } from '../../services/api'
import { useAuthStore } from '../../stores/authStore'
import { useToastStore } from '../../stores/toastStore'
import { cn } from '../../lib/utils'

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
    if (!apiKey.trim()) return
    setIsSaving(true)
    setSaveSuccess(false)
    try {
      await updateLLMConfig({ api_key: apiKey.trim() })
      setIsConfigured(true)
      setSaveSuccess(true)
      setApiKey('')
      addToast('success', 'API Key 已保存')
      onConfigured?.()
      setTimeout(() => onClose(), 800)
    } catch {
      addToast('error', '保存失败，请重试')
    } finally {
      setIsSaving(false)
    }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm animate-in fade-in duration-200"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative w-full max-w-md mx-4 animate-in zoom-in-95 fade-in duration-200">
        <div className="bg-white dark:bg-slate-900 rounded-2xl shadow-2xl border border-slate-200/60 dark:border-slate-700/60 overflow-hidden">
          {/* Header */}
          <div className="relative px-6 pt-6 pb-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-500 flex items-center justify-center shadow-lg shadow-indigo-500/20">
                <Settings className="w-5 h-5 text-white" />
              </div>
              <div>
                <h2 className="text-lg font-semibold text-slate-800 dark:text-slate-100">设置</h2>
                <p className="text-xs text-slate-400 mt-0.5">配置 OpenRouter API 连接</p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="absolute right-4 top-4 p-2 rounded-xl text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:text-slate-300 dark:hover:bg-slate-800 transition-all"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Tab bar */}
          <div className="flex border-b border-slate-200 dark:border-slate-700 px-6 gap-1">
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
                <div className={cn(
                  "flex items-center gap-3 px-4 py-3 rounded-xl text-sm",
                  isConfigured
                    ? "bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-400"
                    : "bg-amber-50 dark:bg-amber-950/30 text-amber-700 dark:text-amber-400"
                )}>
                  <div className={cn(
                    "w-2 h-2 rounded-full",
                    isConfigured
                      ? "bg-emerald-500 shadow-sm shadow-emerald-500/50"
                      : "bg-amber-500 shadow-sm shadow-amber-500/50 animate-pulse"
                  )} />
                  {isConfigured ? 'API Key 已配置' : '需要配置 API Key'}
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
                  disabled={!apiKey.trim() || isSaving}
                  className={cn(
                    "flex-1 px-4 py-2.5 text-sm font-medium rounded-xl flex items-center justify-center gap-2 transition-all",
                    saveSuccess
                      ? "bg-emerald-500 text-white"
                      : "bg-gradient-to-r from-indigo-500 to-purple-500 text-white hover:from-indigo-600 hover:to-purple-600 shadow-sm shadow-indigo-500/20",
                    (!apiKey.trim() || isSaving) && "opacity-50 cursor-not-allowed"
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
  const [inviteCode, setInviteCode] = useState('')
  const [editingCode, setEditingCode] = useState('')
  const [isEditingCode, setIsEditingCode] = useState(false)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [userList, code] = await Promise.all([listUsers(), getInviteCode()])
      setUsers(userList)
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

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="w-6 h-6 animate-spin text-indigo-500" />
      </div>
    )
  }

  return (
    <div className="px-6 py-5 space-y-5">
      {/* Invite code */}
      <div>
        <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
          <Key className="w-3.5 h-3.5 inline mr-1.5" />
          邀请码
        </label>
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
