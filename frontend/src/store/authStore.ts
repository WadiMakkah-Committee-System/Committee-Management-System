import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { User } from '@/types'

interface AuthState {
  accessToken: string | null
  refreshToken: string | null
  user: User | null
  setTokens: (accessToken: string, refreshToken: string) => void
  setUser: (user: User) => void
  logout: () => void
}

/**
 * الحالة العامة للمصادقة — تُخزَّن في localStorage عشان الجلسة تبقى بعد
 * تحديث الصفحة. التوكن نفسه لا يمنح صلاحيات فعلية بدون تحقق الباك-إند من
 * الدور في كل طلب (RBAC حقيقي في الـ API، وليس في الفرونت — CLAUDE.md).
 */
export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      refreshToken: null,
      user: null,
      setTokens: (accessToken, refreshToken) => set({ accessToken, refreshToken }),
      setUser: (user) => set({ user }),
      logout: () => set({ accessToken: null, refreshToken: null, user: null }),
    }),
    { name: 'wadi-makkah-auth' },
  ),
)
