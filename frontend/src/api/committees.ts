import { apiClient } from '@/lib/apiClient'
import type { Committee, DepartmentMemberElsewhere } from '@/types'

/**
 * وحدة "اللجان المعتمدة" — سطح قراءة بسيط فقط (Phase 5، حسب ترقيم Lama
 * الرسمي)، يقابل committees_router بالباك-إند (committees.py). عرض فقط
 * حاليًا بقرار موثّق من Lama — لا إضافة/حذف أعضاء ولا تعديل بيانات لجنة
 * حتى إشعار آخر منها. راجعي project_memory:
 * phase2-committee-formation-requests.md للتفاصيل الكاملة.
 */

export async function fetchCommittees(): Promise<Committee[]> {
  const { data } = await apiClient.get<Committee[]>('/committees')
  return data
}

export async function fetchCommittee(committeeId: string): Promise<Committee> {
  const { data } = await apiClient.get<Committee>(`/committees/${committeeId}`)
  return data
}

/**
 * موظفو إدارة المستخدم الحالي المشاركون بلجان لا تتبع إدارتهم — مراجعة
 * لاما 2026-08-30 (الجولة الثالثة). search اختياري (تصفية نصية باسم
 * الموظف/اللجنة/الإدارة، تُطبَّق بالباك-إند).
 */
export async function fetchDepartmentMembersElsewhere(
  search?: string,
): Promise<DepartmentMemberElsewhere[]> {
  const { data } = await apiClient.get<DepartmentMemberElsewhere[]>(
    '/committees/department-members-elsewhere',
    { params: search ? { search } : undefined },
  )
  return data
}
