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
    // بلاغ لاما 2026-09-01: عضو لجنة (رئيس/عضو) قد يملك وصولًا فعليًا
    // لصفحة "اللجان المعتمدة" عبر عضوية اللجنة نفسها فقط، بدون أي صلاحية
    // committees.view على مستوى System Role (permissions العامة أدناه لا
    // تعكس هذا إطلاقًا) — راجعي has_committee_membership_access بـ
    // types/index.ts وcommittee_service.user_has_committee_role_view_access
    // بالباك-إند لتفاصيل الحساب الكامل.
    const hasCommitteeMembershipBypass =
      !!anyPermission?.includes('committees.view') && user.has_committee_membership_access
    // قرار توحيد سلوك القائمة الجانبية بين "اللجان" و"الاجتماعات"
    // (2026-09-01): نفس فكرة الالتفافة أعلاه بالضبط لمسار /meetings —
    // راجعي has_any_committee_membership بـtypes/index.ts وSidebar.tsx.
    const hasMeetingsMembershipBypass =
      !!anyPermission?.includes('meetings.view') && user.has_any_committee_membership
    // نفس المبدأ لمسار /decisions.
    const hasDecisionsMembershipBypass =
      !!anyPermission?.includes('decisions.view') && user.has_any_committee_membership
    if (
      anyPermission &&
      !anyPermission.some((code) => user.permissions.includes(code)) &&
      !hasCommitteeMembershipBypass &&
      !hasMeetingsMembershipBypass &&
      !hasDecisionsMembershipBypass
    ) {
      return <Navigate to="/profile" replace />
    }
  }

  return <Outlet />
}
