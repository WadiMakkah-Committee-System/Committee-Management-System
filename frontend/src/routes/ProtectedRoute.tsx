import { Navigate, Outlet } from 'react-router-dom'
import { useAuthStore } from '@/store/authStore'

interface ProtectedRouteProps {
  /**
   * يكفي أن يملك المستخدم واحدة على الأقل من هذه الصلاحيات للوصول — نفس
   * منطق require_permission في الباك-إند (core/dependencies.py)، عشان
   * قيود الفرونت تطابق قيود الـ API الفعلية بدل افتراض قائمة أدوار ثابتة.
   * لا يوجد تجاوز تلقائي لـsuper_admin (قرار موثّق من صاحبة المشروع
   * 2026-08-27) — المسار الآمن الوحيد المتبقّي هو superAdminOnly أدناه.
   */
  anyPermission?: string[]
  /** يقيّد الوصول بدور الجذر (is_super_admin) فقط — لشاشات إدارة الأدوار نفسها. */
  superAdminOnly?: boolean
}

export function ProtectedRoute({ anyPermission, superAdminOnly }: ProtectedRouteProps = {}) {
  const accessToken = useAuthStore((s) => s.accessToken)
  const user = useAuthStore((s) => s.user)

  if (!accessToken) {
    return <Navigate to="/login" replace />
  }

  if (user) {
    const isSuperAdmin = !!user.role?.is_super_admin
    if (superAdminOnly && !isSuperAdmin) {
      return <Navigate to="/profile" replace />
    }
    if (anyPermission && !anyPermission.some((code) => user.permissions.includes(code))) {
      return <Navigate to="/profile" replace />
    }
  }

  return <Outlet />
}
