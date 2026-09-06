import { apiClient } from '@/lib/apiClient'
import type {
  Meeting,
  MeetingAgendaItem,
  MeetingAgendaItemCreatePayload,
  MeetingAgendaItemUpdatePayload,
  MeetingAttachment,
  MeetingAttachmentKind,
  MeetingCreatePayload,
  MeetingJoinResponse,
  MeetingUpdatePayload,
} from '@/types'

/**
 * وحدة "إدارة الاجتماعات" — تقابل app/api/v1/meetings.py بالباك-إند.
 * التفويض هيكلي (دور اللجنة/النظام)، وليس صلاحية عامة ثابتة — راجعي
 * hooks/useMeetings.ts وMeetingsPage.tsx لتفصيل كيفية تحديد ذلك بالواجهة.
 */

export async function fetchMeetings(): Promise<Meeting[]> {
  const { data } = await apiClient.get<Meeting[]>('/meetings')
  return data
}

export async function fetchMeeting(meetingId: string): Promise<Meeting> {
  const { data } = await apiClient.get<Meeting>(`/meetings/${meetingId}`)
  return data
}

export async function createMeeting(payload: MeetingCreatePayload): Promise<Meeting> {
  const { data } = await apiClient.post<Meeting>('/meetings', payload)
  return data
}

export async function updateMeeting(
  meetingId: string,
  payload: MeetingUpdatePayload,
): Promise<Meeting> {
  const { data } = await apiClient.patch<Meeting>(`/meetings/${meetingId}`, payload)
  return data
}

export async function deleteMeeting(meetingId: string): Promise<void> {
  await apiClient.delete(`/meetings/${meetingId}`)
}

/**
 * الانضمام لغرفة فيديو الاجتماع (Agora) — يعيد بيانات دخول قصيرة العمر
 * (token صالح AGORA_TOKEN_TTL_SECONDS فقط، راجعي config.py بالباك-إند).
 * يفشل بـ400/403/404 لو الاجتماع ليس mode='remote'، أو انتهى، أو ماعندك
 * صلاحية meetings.join — راجعي MeetingRoom.tsx لكيفية عرض هذا الخطأ.
 */
export async function joinMeeting(meetingId: string): Promise<MeetingJoinResponse> {
  const { data } = await apiClient.post<MeetingJoinResponse>(`/meetings/${meetingId}/join`)
  return data
}

/**
 * مغادرة غرفة الفيديو — agora_uid اختياري (يحدد جلسة الحضور بالضبط لو
 * المستخدم فتح أكثر من تبويب/جهاز بنفس الوقت)، راجعي app/api/v1/meetings.py.
 */
export async function leaveMeeting(meetingId: string, agoraUid?: number): Promise<void> {
  await apiClient.post(`/meetings/${meetingId}/leave`, null, {
    params: agoraUid !== undefined ? { agora_uid: agoraUid } : undefined,
  })
}

export async function addAgendaItem(
  meetingId: string,
  payload: MeetingAgendaItemCreatePayload,
): Promise<MeetingAgendaItem> {
  const { data } = await apiClient.post<MeetingAgendaItem>(
    `/meetings/${meetingId}/agenda-items`,
    payload,
  )
  return data
}

export async function updateAgendaItem(
  agendaItemId: string,
  payload: MeetingAgendaItemUpdatePayload,
): Promise<MeetingAgendaItem> {
  const { data } = await apiClient.patch<MeetingAgendaItem>(
    `/meetings/agenda-items/${agendaItemId}`,
    payload,
  )
  return data
}

export async function deleteAgendaItem(agendaItemId: string): Promise<void> {
  await apiClient.delete(`/meetings/agenda-items/${agendaItemId}`)
}

/**
 * مرفقات الاجتماع — أول استخدام فعلي لـdocument_links بالباك-إند (راجعي
 * رأس db/migrations/0021). الرفع multipart/form-data (وليس JSON)، بنفس
 * منطق POST /documents. التحميل عبر fetchMeetingAttachmentBlob (وليس
 * <a href> مباشرة) لأن التنزيل يتطلب Authorization Bearer بالـheader —
 * راجعي useMeetings.ts. التحميل يمر عبر مسار مخصص بوحدة الاجتماعات
 * GET /meetings/{meetingId}/attachments/{documentId}/download (وليس
 * GET /documents/{documentId}/download العام) لأن ذلك المسار محمي
 * بصلاحية Role نظامية ثابتة (documents.download) لا يملكها عضو اللجنة
 * العادي غالبًا، بينما هنا يكفي meetings.attachments.view.
 */
export async function fetchMeetingAttachments(
  meetingId: string,
  kind?: MeetingAttachmentKind,
): Promise<MeetingAttachment[]> {
  const { data } = await apiClient.get<MeetingAttachment[]>(`/meetings/${meetingId}/attachments`, {
    params: kind ? { kind } : undefined,
  })
  return data
}

export async function uploadMeetingAttachment(
  meetingId: string,
  file: File,
  kind: MeetingAttachmentKind,
  title?: string,
): Promise<MeetingAttachment> {
  const form = new FormData()
  form.append('file', file)
  form.append('kind', kind)
  if (title) form.append('title', title)
  const { data } = await apiClient.post<MeetingAttachment>(
    `/meetings/${meetingId}/attachments`,
    form,
    { headers: { 'Content-Type': 'multipart/form-data' } },
  )
  return data
}

export async function deleteMeetingAttachment(
  meetingId: string,
  documentId: string,
): Promise<void> {
  await apiClient.delete(`/meetings/${meetingId}/attachments/${documentId}`)
}

export async function fetchMeetingAttachmentBlob(
  meetingId: string,
  documentId: string,
): Promise<{ blob: Blob; fileName: string }> {
  const response = await apiClient.get(
    `/meetings/${meetingId}/attachments/${documentId}/download`,
    { responseType: 'blob' },
  )
  const disposition = String(response.headers['content-disposition'] ?? '')
  const match = /filename="?([^"]+)"?/.exec(disposition)
  return { blob: response.data as Blob, fileName: match?.[1] ?? 'attachment' }
}
