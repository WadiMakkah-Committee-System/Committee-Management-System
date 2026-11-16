import { apiClient } from '@/lib/apiClient'
import type {
  Committee,
  CommitteeCapabilities,
  CommitteeChange,
  DepartmentMemberElsewhere,
  ProposedMember,
} from '@/types'

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

export interface CommitteeDatesUpdatePayload {
  start_date?: string
  end_date?: string
}

/**
 * تعديل فترة عمل لجنة معتمدة (start_date/end_date فقط) — قرار صاحبة
 * المشروع 2026-09-13 ("قاعدة فترة اللجنة"، نقض جزئي لقرار "بيانات اللجنة
 * مقفلة نهائيًا"). متاح فقط لمن يملك committees.update (المكتب التنفيذي
 * حاليًا — راجعي backend/db/migrations/0032_committee_dates_update_grant.sql).
 */
export async function updateCommitteeDates(
  committeeId: string,
  payload: CommitteeDatesUpdatePayload,
): Promise<Committee> {
  const { data } = await apiClient.patch<Committee>(`/committees/${committeeId}`, payload)
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

// =====================================================================
// تعديل عضوية اللجنة الدائمة + تمديد الفترة + سجل التغييرات (migration 0050
// — طلب لاما 2026-11-16). الصلاحيات تُفحص بالباك-إند.
// =====================================================================

export async function fetchCommitteeCapabilities(committeeId: string): Promise<CommitteeCapabilities> {
  const { data } = await apiClient.get<CommitteeCapabilities>(`/committees/${committeeId}/capabilities`)
  return data
}

export async function fetchCommitteeChanges(committeeId: string): Promise<CommitteeChange[]> {
  const { data } = await apiClient.get<CommitteeChange[]>(`/committees/${committeeId}/changes`)
  return data
}

export async function fetchCommitteeMemberCandidates(committeeId: string): Promise<ProposedMember[]> {
  const { data } = await apiClient.get<ProposedMember[]>(`/committees/${committeeId}/member-candidates`)
  return data
}

export async function addCommitteeMember(committeeId: string, userId: string, reason?: string): Promise<Committee> {
  const { data } = await apiClient.post<Committee>(`/committees/${committeeId}/members`, { user_id: userId, reason })
  return data
}

export async function removeCommitteeMember(committeeId: string, userId: string, reason?: string): Promise<Committee> {
  const { data } = await apiClient.post<Committee>(`/committees/${committeeId}/members/${userId}/remove`, { reason })
  return data
}

export async function changeCommitteeChair(committeeId: string, userId: string): Promise<Committee> {
  const { data } = await apiClient.put<Committee>(`/committees/${committeeId}/chair`, { user_id: userId })
  return data
}

export async function changeCommitteeSecretary(committeeId: string, userId: string | null): Promise<Committee> {
  const { data } = await apiClient.put<Committee>(`/committees/${committeeId}/secretary`, { user_id: userId })
  return data
}

export async function extendCommittee(committeeId: string, endDate: string, reason?: string): Promise<Committee> {
  const { data } = await apiClient.post<Committee>(`/committees/${committeeId}/extend`, {
    end_date: endDate,
    reason,
  })
  return data
}
