/**
 * 统一环境判断
 *
 * 所有组件/Store 通过此模块读取运行环境，不再散落 window.electronAPI 等判断。
 */

declare global {
  interface Window {
    electronAPI?: {
      platform: string
      versions: Record<string, string>
      isElectron: boolean
    }
  }
}

export const env = {
  get isElectron() {
    return !!window.electronAPI?.isElectron
  },

  get isWeb() {
    return !window.electronAPI?.isElectron
  },

  get isCursor() {
    return new URLSearchParams(window.location.search).has('cursor')
  },

  get isOnline() {
    return navigator.onLine
  },

  get platform() {
    return window.electronAPI?.platform ?? 'web'
  },
}
