import { create } from 'zustand'
import {
  loginApi,
  registerApi,
  getMe,
  getAuthToken,
  setAuthToken,
  clearAuthToken,
  type AuthUser,
} from '../services/api'

interface AuthStore {
  token: string | null
  user: AuthUser | null
  isAuthenticated: boolean
  isLoading: boolean

  login: (username: string, password: string) => Promise<void>
  register: (username: string, password: string, inviteCode: string) => Promise<void>
  logout: () => void
  checkAuth: () => Promise<boolean>
}

export const useAuthStore = create<AuthStore>((set) => ({
  token: getAuthToken(),
  user: null,
  isAuthenticated: false,
  isLoading: false,

  login: async (username, password) => {
    set({ isLoading: true })
    try {
      const res = await loginApi(username, password)
      setAuthToken(res.access_token)
      set({
        token: res.access_token,
        user: res.user,
        isAuthenticated: true,
        isLoading: false,
      })
    } catch (error) {
      set({ isLoading: false })
      throw error
    }
  },

  register: async (username, password, inviteCode) => {
    set({ isLoading: true })
    try {
      const res = await registerApi(username, password, inviteCode)
      setAuthToken(res.access_token)
      set({
        token: res.access_token,
        user: res.user,
        isAuthenticated: true,
        isLoading: false,
      })
    } catch (error) {
      set({ isLoading: false })
      throw error
    }
  },

  logout: () => {
    clearAuthToken()
    set({ token: null, user: null, isAuthenticated: false })
  },

  checkAuth: async () => {
    const token = getAuthToken()
    try {
      const user = await getMe()
      set({ token, user, isAuthenticated: true })
      return true
    } catch {
      if (token) clearAuthToken()
      set({ token: null, user: null, isAuthenticated: false })
      return false
    }
  },
}))
