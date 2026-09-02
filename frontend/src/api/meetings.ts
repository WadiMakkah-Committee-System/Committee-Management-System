import { apiClient } from '@/lib/apiClient'
import type {
  Meeting,
  MeetingAgendaItem,
  MeetingAgendaItemCreatePayload,
  MeetingAgendaItemUpdatePayload,
  MeetingAttachment,
  MeetingAttachmentKind,
  MeetingCreatePayload,
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
 * رفع مرفق/عرض تقديمي — multipart/form-data (وليس JSON) لأن الملف الفعلي
 * يمر عبر الـBackend إلى Supabase Storage، بنفس نمط رفع الوثائق العادي.
 */
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

export async function fetchMeetingAttachments(
  meetingId: string,
  kind?: MeetingAttachmentKind,
): Promise<MeetingAttachment[]> {
  const { data } = await apiClient.get<MeetingAttachment[]>(`/meetings/${meetingId}/attachments`, {
    params: kind ? { kind } : undefined,
  })
  return data
}

export async function deleteMeetingAttachment(
  meetingId: string,
  documentId: string,
): Promise<void> {
  await apiClient.delete(`/meetings/${meetingId}/attachments/${documentId}`)
}
