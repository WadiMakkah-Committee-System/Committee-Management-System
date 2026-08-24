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
 * إجراءات القرار (return-to-admin, return-to-office, escalate, approve,
 * reject) متعمَّدة الاستبعاد من هذا الملف حاليًا — واجهاتها تخص Phase 4
 * (واجهات المراجعة والاعتماد) حسب ترقيم Lama الرسمي، وليست جزءًا من Phase 3
 * (إنشاء/عرض/تعديل/إرسال الطلب فقط). الـ Endpoints نفسها جاهزة بالفعل في
 * الباك-إند (committees.py) وتُضاف هنا عند بناء تلك المرحلة.
 */
