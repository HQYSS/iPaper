import { create } from 'zustand'
import { getPreferencesOffline, updatePreferencesOffline } from '../services/offlineApi'

const PREFERENCES_CACHE_KEY = 'ipaper.preferences'

// Legacy localStorage keys for one-time migration
const LEGACY_KEYS = {
  recentPaperIds: 'ipaper.recentPaperIds',
  themeMode: 'ipaper.themeMode',
  chatPanelWidthRatio: 'ipaper.chatPanelWidthRatio',
  pdfScale: 'ipaper.pdfScale',
  pdfDimmingMode: 'ipaper.pdfDimmingMode',
  pdfOverlayOpacity: 'ipaper.pdfOverlayOpacity',
  pdfBrightness: 'ipaper.pdfBrightness',
  pdfReadingPositions: 'ipaper.pdfReadingPositions',
  pdfLangs: 'ipaper.pdfLangs',
} as const

interface Preferences {
  recentPaperIds: string[]
  themeMode: 'light' | 'dark' | 'system'
  chatPanelWidthRatio: number | null
  pdfScale: number | null
  pdfDimmingMode: 'off' | 'overlay' | 'brightness'
  pdfOverlayOpacity: number
  pdfBrightness: number
  pdfReadingPositions: Record<string, number>
  pdfLangs: Record<string, string>
}

const DEFAULT_PREFERENCES: Preferences = {
  recentPaperIds: [],
  themeMode: 'system',
  chatPanelWidthRatio: null,
  pdfScale: null,
  pdfDimmingMode: 'off',
  pdfOverlayOpacity: 0.12,
  pdfBrightness: 0.85,
  pdfReadingPositions: {},
  pdfLangs: {},
}

function readCachedPreferences(): Preferences {
  try {
    const raw = localStorage.getItem(PREFERENCES_CACHE_KEY)
    if (!raw) return { ...DEFAULT_PREFERENCES }
    return { ...DEFAULT_PREFERENCES, ...JSON.parse(raw) }
  } catch {
    return { ...DEFAULT_PREFERENCES }
  }
}

function writeCachedPreferences(prefs: Preferences) {
  localStorage.setItem(PREFERENCES_CACHE_KEY, JSON.stringify(prefs))
}

function collectLegacyPreferences(): Partial<Preferences> | null {
  const legacy: Partial<Preferences> = {}
  let hasAny = false

  try {
    const raw = localStorage.getItem(LEGACY_KEYS.recentPaperIds)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed)) {
        legacy.recentPaperIds = parsed.filter((v): v is string => typeof v === 'string')
        hasAny = true
      }
    }
  } catch { /* ignore */ }

  const themeRaw = localStorage.getItem(LEGACY_KEYS.themeMode)
  if (themeRaw === 'light' || themeRaw === 'dark' || themeRaw === 'system') {
    legacy.themeMode = themeRaw
    hasAny = true
  }

  const ratioRaw = localStorage.getItem(LEGACY_KEYS.chatPanelWidthRatio)
  if (ratioRaw) {
    const ratio = Number(ratioRaw)
    if (Number.isFinite(ratio) && ratio > 0) {
      legacy.chatPanelWidthRatio = ratio
      hasAny = true
    }
  }

  const scaleRaw = localStorage.getItem(LEGACY_KEYS.pdfScale)
  if (scaleRaw) {
    const scale = Number(scaleRaw)
    if (Number.isFinite(scale) && scale > 0) {
      legacy.pdfScale = scale
      hasAny = true
    }
  }

  const dimmingRaw = localStorage.getItem(LEGACY_KEYS.pdfDimmingMode)
  if (dimmingRaw === 'off' || dimmingRaw === 'overlay' || dimmingRaw === 'brightness') {
    legacy.pdfDimmingMode = dimmingRaw
    hasAny = true
  }

  const opacityRaw = localStorage.getItem(LEGACY_KEYS.pdfOverlayOpacity)
  if (opacityRaw) {
    const val = Number(opacityRaw)
    if (Number.isFinite(val)) {
      legacy.pdfOverlayOpacity = val
      hasAny = true
    }
  }

  const brightnessRaw = localStorage.getItem(LEGACY_KEYS.pdfBrightness)
  if (brightnessRaw) {
    const val = Number(brightnessRaw)
    if (Number.isFinite(val)) {
      legacy.pdfBrightness = val
      hasAny = true
    }
  }

  try {
    const raw = localStorage.getItem(LEGACY_KEYS.pdfReadingPositions)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        legacy.pdfReadingPositions = parsed
        hasAny = true
      }
    }
  } catch { /* ignore */ }

  try {
    const raw = localStorage.getItem(LEGACY_KEYS.pdfLangs)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        legacy.pdfLangs = parsed
        hasAny = true
      }
    }
  } catch { /* ignore */ }

  return hasAny ? legacy : null
}

function cleanupLegacyKeys() {
  for (const key of Object.values(LEGACY_KEYS)) {
    localStorage.removeItem(key)
  }
}

let debounceTimer: ReturnType<typeof setTimeout> | null = null

function isServerEmpty(data: Record<string, unknown>): boolean {
  return Object.keys(data).length === 0 ||
    Object.values(data).every((v) => v === null || v === undefined)
}

interface PreferencesStore {
  preferences: Preferences
  isLoaded: boolean

  loadPreferences: () => Promise<void>
  updatePreferences: (partial: Partial<Preferences>) => void

  getRecentPaperIds: () => string[]
  setRecentPaperIds: (ids: string[]) => void
  getThemeMode: () => string
  setThemeMode: (mode: string) => void
  getPdfScale: () => number | null
  setPdfScale: (scale: number) => void
  getPdfReadingPosition: (paperId: string, lang: string) => number | null
  setPdfReadingPosition: (paperId: string, lang: string, ratio: number) => void
  getPdfLang: (paperId: string) => string
  setPdfLang: (paperId: string, lang: string) => void
  getChatPanelWidthRatio: () => number | null
  setChatPanelWidthRatio: (ratio: number) => void
  getPdfDimmingMode: () => string
  setPdfDimmingMode: (mode: string) => void
  getPdfOverlayOpacity: () => number
  setPdfOverlayOpacity: (value: number) => void
  getPdfBrightness: () => number
  setPdfBrightness: (value: number) => void
}

export const usePreferencesStore = create<PreferencesStore>((set, get) => ({
  preferences: readCachedPreferences(),
  isLoaded: false,

  loadPreferences: async () => {
    try {
      const serverData = await getPreferencesOffline()

      if (isServerEmpty(serverData)) {
        const legacy = collectLegacyPreferences()
        if (legacy) {
          const merged = { ...DEFAULT_PREFERENCES, ...legacy }
          set({ preferences: merged, isLoaded: true })
          writeCachedPreferences(merged)
          cleanupLegacyKeys()
          updatePreferencesOffline(legacy as Record<string, unknown>).catch(() => {})
          return
        }
      }

      const merged: Preferences = { ...DEFAULT_PREFERENCES, ...serverData as Partial<Preferences> }
      set({ preferences: merged, isLoaded: true })
      writeCachedPreferences(merged)
      cleanupLegacyKeys()
    } catch {
      set({ isLoaded: true })
    }
  },

  updatePreferences: (partial) => {
    const next = { ...get().preferences, ...partial }
    set({ preferences: next })
    writeCachedPreferences(next)

    if (debounceTimer) clearTimeout(debounceTimer)
    debounceTimer = setTimeout(() => {
      updatePreferencesOffline(partial as Record<string, unknown>).catch(() => {})
    }, 500)
  },

  getRecentPaperIds: () => get().preferences.recentPaperIds,
  setRecentPaperIds: (ids) => get().updatePreferences({ recentPaperIds: ids }),

  getThemeMode: () => get().preferences.themeMode,
  setThemeMode: (mode) => get().updatePreferences({ themeMode: mode as Preferences['themeMode'] }),

  getPdfScale: () => get().preferences.pdfScale,
  setPdfScale: (scale) => get().updatePreferences({ pdfScale: scale }),

  getPdfReadingPosition: (paperId, lang) => {
    const key = `${paperId}:${lang}`
    return get().preferences.pdfReadingPositions[key] ?? null
  },
  setPdfReadingPosition: (paperId, lang, ratio) => {
    const key = `${paperId}:${lang}`
    const positions = { ...get().preferences.pdfReadingPositions, [key]: ratio }
    get().updatePreferences({ pdfReadingPositions: positions })
  },

  getPdfLang: (paperId) => get().preferences.pdfLangs[paperId] ?? 'en',
  setPdfLang: (paperId, lang) => {
    const langs = { ...get().preferences.pdfLangs }
    if (lang === 'en') {
      delete langs[paperId]
    } else {
      langs[paperId] = lang
    }
    get().updatePreferences({ pdfLangs: langs })
  },

  getChatPanelWidthRatio: () => get().preferences.chatPanelWidthRatio,
  setChatPanelWidthRatio: (ratio) => get().updatePreferences({ chatPanelWidthRatio: ratio }),

  getPdfDimmingMode: () => get().preferences.pdfDimmingMode,
  setPdfDimmingMode: (mode) => get().updatePreferences({ pdfDimmingMode: mode as Preferences['pdfDimmingMode'] }),

  getPdfOverlayOpacity: () => get().preferences.pdfOverlayOpacity,
  setPdfOverlayOpacity: (value) => get().updatePreferences({ pdfOverlayOpacity: value }),

  getPdfBrightness: () => get().preferences.pdfBrightness,
  setPdfBrightness: (value) => get().updatePreferences({ pdfBrightness: value }),
}))
