import { apiClient } from '@/lib/apiClient'
import type {
  CommitteeFormationRequest,
  CommitteeFormationRequestCreatePayload,
  CommitteeFormationRequestUpdatePayload,
} from '@/types'

export async function fetchCommitteeRequests(): Promise<CommitteeFormationRequest[]> {
  const { data } = await apiClient.get<CommitteeFormationRequest[]>('/committee-requests')
  return data
}

export async function fetchCommitteeRequest(requestId: string): Promise<CommitteeFormationRequest> {
  const { data } = await apiClient.get<CommitteeFormationRequest>(`/committee-requests/${requestId}`)
  return data
}

export async function createCommitteeRequest(
  payload: CommitteeFormationRequestCreatePayload,
): Promise<CommitteeFormationRequest> {
  const { data } = await apiClient.post<CommitteeFormationRequest>('/committee-requests', payload)
  return data
}

export async function updateCommitteeRequest(
  requestId: string,
  payload: CommitteeFormationRequestUpdatePayload,
): Promise<CommitteeFormationRequest> {
  const { data } = await apiClient.patch<CommitteeFormationRequest>(
    `/committee-requests/${requestId}`,
    payload,
  )
  return data
}

/** RF-COM-300: إرسال الطلب من الادمن للمكتب التنفيذي (draft/returned → submitted). */
export async function submitCommitteeRequest(requestId: string): Promise<CommitteeFormationRequest> {
  const { data } = await apiClient.post<CommitteeFormationRequest>(
    `/committee-requests/${requestId}/submit`,
  )
  return data
}

/*
 * إجراءات القرار التالية (Phase 4 — واجهات المراجعة والاعتماد، حسب
 * ترقيم Lama الرسمي) — راجعي committee_service.py لتفاصيل RBAC/الحالات
 * الكاملة لكل مسار.
 */

/** المكتب التنفيذي يرجع الطلب لمقدّمه (الادمن) مع سبب إلزامي — غير نهائي (submitted/under_review → returned). */
export async function returnCommitteeRequestToAdmin(
  requestId: string,
  returnReason: string,
): Promise<CommitteeFormationRequest> {
  const { data } = await apiClient.post<CommitteeFormationRequest>(
    `/committee-requests/${requestId}/return-to-admin`,
    { return_reason: returnReason },
  )
  return data
}

/** الرئيس التنفيذي يرجع الطلب للمكتب التنفيذي مع سبب إلزامي — غير نهائي (pending_approval → under_review). */
export async function returnCommitteeRequestToOffice(
  requestId: string,
  returnReason: string,
): Promise<CommitteeFormationRequest> {
  const { data } = await apiClient.post<CommitteeFormationRequest>(
    `/committee-requests/${requestId}/return-to-office`,
    { return_reason: returnReason },
  )
  return data
}

/** RF-COM-400: المكتب التنفيذي يرفع الطلب للرئيس التنفيذي (submitted/under_review → pending_approval). */
export async function escalateCommitteeRequest(requestId: string): Promise<CommitteeFormationRequest> {
  const { data } = await apiClient.post<CommitteeFormationRequest>(
    `/committee-requests/${requestId}/escalate`,
  )
  return data
}

/** RF-COM-500: الرئيس التنفيذي يعتمد الطلب — نهائي، ينشئ اللجنة تلقائيًا (pending_approval → approved). */
export async function approveCommitteeRequest(requestId: string): Promise<CommitteeFormationRequest> {
  const { data } = await apiClient.post<CommitteeFormationRequest>(
    `/committee-requests/${requestId}/approve`,
  )
  return data
}

/** RF-COM-600: الرئيس التنفيذي يرفض الطلب نهائيًا مع سبب إلزامي (pending_approval → rejected). */
export async function rejectCommitteeRequest(
  requestId: string,
  rejectionReason: string,
): Promise<CommitteeFormationRequest> {
  const { data } = await apiClient.post<CommitteeFormationRequest>(
    `/committee-requests/${requestId}/reject`,
    { rejection_reason: rejectionReason },
  )
  return data
}
