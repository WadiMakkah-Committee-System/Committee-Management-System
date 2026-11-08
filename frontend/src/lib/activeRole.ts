import type { AxiosError } from 'axios'

/**
 * الهدف: ثوابت "الدور الحالي" المشتركة بين طبقة الاتصال (apiClient) وبقية
 * الواجهة — تعدد الأدوار، migration 0046.
 *
 * - ACTIVE_ROLE_HEADER: رأس ترسل فيه الواجهة معرّف الدور الحالي اللي تعرضه.
 *   يطابق ACTIVE_ROLE_HEADER بـbackend/app/core/dependencies.py. لا يمنح أي
 *   صلاحية — الباك-إند يقارنه فقط بالدور الحالي الفعلي بقاعدة البيانات.
 * - ACTIVE_ROLE_CHANGED_CODE: رمز استجابة 409 لما يختلف الاثنان (بدّل
 *   المستخدم دوره من تبويب آخر).
 * - ACTIVE_ROLE_CHANGED_EVENT: حدث window يطلقه apiClient عند ذلك الرد،
 *   ويستقبله useActiveRoleSync (AppShell) فيعيد تحميل بيانات المستخدم.
 *   حدث بدل استدعاء مباشر لأن apiClient خارج شجرة React (بلا QueryClient).
 */
export const ACTIVE_ROLE_HEADER = 'X-Active-Role'
export const ACTIVE_ROLE_CHANGED_CODE = 'active_role_changed'
export const ACTIVE_ROLE_CHANGED_EVENT = 'wadi:active-role-changed'

/** هل الخطأ هو 409 "تغيّر دورك الحالي من نافذة أخرى"؟ */
export function isActiveRoleChangedError(error: AxiosError): boolean {
  if (error.response?.status !== 409) return false
  const detail = (error.response.data as { detail?: unknown } | undefined)?.detail
  return (
    typeof detail === 'object' &&
    detail !== null &&
    (detail as { code?: unknown }).code === ACTIVE_ROLE_CHANGED_CODE
  )
}
