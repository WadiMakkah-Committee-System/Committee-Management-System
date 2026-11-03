import { apiClient } from '@/lib/apiClient'
import { fileNameFromDisposition } from '@/lib/utils'
import type {
  Decision,
  DecisionAttachment,
  DecisionCreatePayload,
  DecisionOpenVotingPayload,
  DecisionUpdatePayload,
} from '@/types'

/**
 * وحدة "إدارة القرارات" — تقابل app/api/v1/decisions.py بالباك-إند.
 * القرارات المستقلة فقط (بدون قرارات مستخرجة من اجتماع بالذكاء
 * الاصطناعي — تُبنى لاحقًا). التفويض هيكلي (دور اللجنة/النظام)، وليس
 * صلاحية عامة ثابتة — راجعي hooks/useDecisions.ts وDecisionsPage.tsx.
 */

export async function fetchDecisions(meetingId?: string): Promise<Decision[]> {
  const { data } = await apiClient.get<Decision[]>('/decisions', {
    params: meetingId ? { meeting_id: meetingId } : undefined,
  })
  return data
}

export async function fetchDecision(decisionId: string): Promise<Decision> {
  const { data } = await apiClient.get<Decision>(`/decisions/${decisionId}`)
  return data
}

export async function createDecision(payload: DecisionCreatePayload): Promise<Decision> {
  const { data } = await apiClient.post<Decision>('/decisions', payload)
  return data
}

export async function updateDecision(
  decisionId: string,
  payload: DecisionUpdatePayload,
): Promise<Decision> {
  const { data } = await apiClient.patch<Decision>(`/decisions/${decisionId}`, payload)
  return data
}

export async function deleteDecision(decisionId: string): Promise<void> {
  await apiClient.delete(`/decisions/${decisionId}`)
}

/** الخيارات ثابتة (موافق / غير موافق / ممتنع) ويُنشئها الباك-إند — راجعي DecisionOpenVotingPayload بـtypes/index.ts. */
export async function openVoting(
  decisionId: string,
  payload: DecisionOpenVotingPayload,
): Promise<Decision> {
  const { data } = await apiClient.post<Decision>(`/decisions/${decisionId}/open-voting`, payload)
  return data
}

/** reason إلزامي فقط عند اختيار خيار "ممتنع" الثابت (option.is_abstain) — يُتحقَّق منه بالباك-إند. */
export async function castVote(
  decisionId: string,
  optionId: string,
  reason?: string,
): Promise<Decision> {
  const { data } = await apiClient.post<Decision>(`/decisions/${decisionId}/vote`, {
    option_id: optionId,
    reason: reason ?? null,
  })
  return data
}

export async function approveDecision(decisionId: string): Promise<Decision> {
  const { data } = await apiClient.post<Decision>(`/decisions/${decisionId}/approve`)
  return data
}

/**
 * مرفق اختياري بالقرار (طلب صاحبة المشروع 2026-11-01) — رئيسة اللجنة
 * عادةً فور الإنشاء. نفس نمط مرفقات الاجتماعات تمامًا (multipart، وتحميل
 * عبر Blob لأن التنزيل يتطلب Authorization Bearer بالـheader).
 */
export async function fetchDecisionAttachments(decisionId: string): Promise<DecisionAttachment[]> {
  const { data } = await apiClient.get<DecisionAttachment[]>(`/decisions/${decisionId}/attachments`)
  return data
}

export async function uploadDecisionAttachment(
  decisionId: string,
  file: File,
): Promise<DecisionAttachment> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await apiClient.post<DecisionAttachment>(
    `/decisions/${decisionId}/attachments`,
    form,
    { headers: { 'Content-Type': 'multipart/form-data' } },
  )
  return data
}

export async function fetchDecisionAttachmentBlob(
  decisionId: string,
  documentId: string,
): Promise<{ blob: Blob; fileName: string }> {
  const response = await apiClient.get(
    `/decisions/${decisionId}/attachments/${documentId}/download`,
    { responseType: 'blob' },
  )
  // fileNameFromDisposition (وليس استخراج يدوي ساذج): الباك-إند يرسل
  // filename*=UTF-8'' للاسم العربي الفعلي (إصلاح 2026-11-02 بعد خلل
  // UnicodeEncodeError بالرأس) — نفس أسلوب تحميل مرفقات الاجتماعات/المحضر.
  const disposition = String(response.headers['content-disposition'] ?? '')
  return { blob: response.data as Blob, fileName: fileNameFromDisposition(disposition, 'attachment') }
}
