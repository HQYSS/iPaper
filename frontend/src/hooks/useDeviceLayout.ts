import { useEffect, useState } from 'react'

import { detectDeviceLayout, detectIsTouchDevice } from '@/services/env'
import type { DeviceLayout } from '@/services/env'

/**
 * 响应式订阅视口变化，返回当前设备布局类型。
 * 旋转屏幕、调整窗口大小都会触发重渲染。
 */
export function useDeviceLayout(): DeviceLayout {
  const [layout, setLayout] = useState<DeviceLayout>(() => detectDeviceLayout())

  useEffect(() => {
    const update = () => setLayout(detectDeviceLayout())

    window.addEventListener('resize', update)
    window.addEventListener('orientationchange', update)
    return () => {
      window.removeEventListener('resize', update)
      window.removeEventListener('orientationchange', update)
    }
  }, [])

  return layout
}

/** 是否触屏设备（首次渲染后稳定不变）。 */
export function useIsTouchDevice(): boolean {
  const [isTouch] = useState<boolean>(() => detectIsTouchDevice())
  return isTouch
}

/**
 * 视口当前朝向：竖屏 'portrait' / 横屏 'landscape'。
 * iPhone 在 PWA standalone 模式下应被 manifest 强制 portrait，
 * iPad 通常仍可自由旋转，UI 需要据此调整布局。
 */
export type ViewportOrientation = 'portrait' | 'landscape'

export function useViewportOrientation(): ViewportOrientation {
  const [orientation, setOrientation] = useState<ViewportOrientation>(() =>
    window.innerWidth >= window.innerHeight ? 'landscape' : 'portrait'
  )

  useEffect(() => {
    const update = () =>
      setOrientation(window.innerWidth >= window.innerHeight ? 'landscape' : 'portrait')

    window.addEventListener('resize', update)
    window.addEventListener('orientationchange', update)
    return () => {
      window.removeEventListener('resize', update)
      window.removeEventListener('orientationchange', update)
    }
  }, [])

  return orientation
}

/**
 * 同步 visualViewport（即"实际可见区"）高度到 CSS 变量 --visual-vh。
 * iOS Safari 在虚拟键盘弹起时不会改 window.innerHeight，但 visualViewport.height
 * 会准确收缩。组件可以用 height: var(--visual-vh) 替代 100dvh，确保 input 永远在
 * 键盘上方。
 *
 * 在 App 顶层调用一次即可（向 :root 写 CSS 变量）。
 */
export function useVisualViewportHeight() {
  useEffect(() => {
    if (typeof window === 'undefined' || !window.visualViewport) return
    const vv = window.visualViewport

    const update = () => {
      document.documentElement.style.setProperty('--visual-vh', `${vv.height}px`)
    }

    update()
    vv.addEventListener('resize', update)
    vv.addEventListener('scroll', update)
    return () => {
      vv.removeEventListener('resize', update)
      vv.removeEventListener('scroll', update)
    }
  }, [])
}
