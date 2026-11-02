import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { AuthMethod, UserDetail } from '@/types'

interface AuthState {
  accessToken: string | null
  refreshToken: string | null
  /** بيانات المستخدم الحالي، بما فيها صلاحياته الفعلية (permissions) — تُستخدم
   *  لإظهار/إخفاء عناصر التنقل والصفحات المقيّدة دون افتراض أدوار ثابتة. */
  user: UserDetail | null
  /** طريقة دخول الجلسة الحالية (null لجلسات قديمة قبل الميزة = تُعامل ككلمة مرور). */
  authMethod: AuthMethod | null
  setTokens: (accessToken: string, refreshToken: string) => void
  setAuthMethod: (method: AuthMethod) => void
  setUser: (user: UserDetail) => void
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
      authMethod: null,
      setTokens: (accessToken, refreshToken) => set({ accessToken, refreshToken }),
      setAuthMethod: (authMethod) => set({ authMethod }),
      setUser: (user) => set({ user }),
      logout: () => {
        set({ accessToken: null, refreshToken: null, user: null, authMethod: null })
        // يمسح جلسة Microsoft المحفوظة بهذا المتصفح مع كل خروج (يدوي أو انتهاء
        // جلسة)، حتى ما يدخل أحد بعده اجتماعًا بهوية المستخدم السابق.
        // استيراد ديناميكي: يتفادى حلقة استيراد (microsoftSignIn ← api ← apiClient ← هنا).
        void import('@/lib/microsoftSignIn').then((m) => m.signOutMicrosoft()).catch(() => {})
      },
    }),
    { name: 'wadi-makkah-auth' },
  ),
)
