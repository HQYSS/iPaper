/**
 * 统一环境判断
 *
 * 所有组件/Store 通过此模块读取运行环境，不再散落 window.electronAPI 等判断。
 *
 * 视口/设备相关判断同时提供两种使用方式：
 * - env.isMobileLayout / env.isTabletLayout / env.isDesktopLayout：瞬时取值，
 *   适合一次性判断（不会随旋转/缩放自动更新）。
 * - useDeviceLayout() hook：响应式订阅 resize / orientationchange，
 *   组件渲染需要随视口变化更新时使用。
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

export const MOBILE_BREAKPOINT = 768
export const TABLET_BREAKPOINT = 1024

export type DeviceLayout = 'mobile' | 'tablet' | 'desktop'

export function detectDeviceLayout(
  width: number = window.innerWidth,
  height: number = window.innerHeight
): DeviceLayout {
  // 用"短边"判断手机 vs 平板：iPhone 横屏 (844x390) 短边仍是 390，应当走移动布局；
  // iPad 横屏 (1024x768) 短边 768，按宽度仍归为桌面/平板，行为符合预期。
  const shortEdge = Math.min(width, height)
  if (shortEdge < MOBILE_BREAKPOINT) return 'mobile'
  if (width < TABLET_BREAKPOINT) return 'tablet'
  return 'desktop'
}

export function detectIsTouchDevice(): boolean {
  if (typeof window === 'undefined') return false
  return (
    'ontouchstart' in window ||
    (typeof navigator !== 'undefined' && navigator.maxTouchPoints > 0)
  )
}

export function detectIsStandalonePwa(): boolean {
  if (typeof window === 'undefined') return false
  // iOS Safari 用 navigator.standalone；其他浏览器用 display-mode 媒体查询
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const iosStandalone = !!(navigator as any).standalone
  const mqStandalone =
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(display-mode: standalone)').matches
  return iosStandalone || mqStandalone
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

  get isTouchDevice() {
    return detectIsTouchDevice()
  },

  get isMobileLayout() {
    return detectDeviceLayout() === 'mobile'
  },

  get isTabletLayout() {
    return detectDeviceLayout() === 'tablet'
  },

  get isDesktopLayout() {
    return detectDeviceLayout() === 'desktop'
  },

  get isStandalonePwa() {
    return detectIsStandalonePwa()
  },
}
