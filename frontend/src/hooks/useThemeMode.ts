import { useCallback, useEffect, useState } from 'react'

import { usePreferencesStore } from '@/stores/preferencesStore'

export type ThemeMode = 'light' | 'dark' | 'system'

export function applyThemeMode(themeMode: ThemeMode, prefersDark: boolean) {
  const shouldUseDark = themeMode === 'dark' || (themeMode === 'system' && prefersDark)
  document.documentElement.classList.toggle('dark', shouldUseDark)
}

/**
 * 主题模式 state + 副作用统一封装。
 * 桌面 / 平板 / 移动布局各自调用同一份，避免散落的 system 监听重复绑定。
 */
export function useThemeMode() {
  const getStoredTheme = usePreferencesStore((s) => s.getThemeMode)
  const setStoredTheme = usePreferencesStore((s) => s.setThemeMode)

  const [themeMode, setThemeMode] = useState<ThemeMode>(
    () => (getStoredTheme() as ThemeMode) || 'system'
  )

  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
    const updateTheme = () => applyThemeMode(themeMode, mediaQuery.matches)

    updateTheme()

    if (themeMode !== 'system') return

    mediaQuery.addEventListener('change', updateTheme)
    return () => mediaQuery.removeEventListener('change', updateTheme)
  }, [themeMode])

  const setMode = useCallback(
    (next: ThemeMode) => {
      setThemeMode(next)
      setStoredTheme(next)
      applyThemeMode(next, window.matchMedia('(prefers-color-scheme: dark)').matches)
    },
    [setStoredTheme]
  )

  return { themeMode, setThemeMode: setMode }
}
