import { apiClient } from '@/lib/apiClient'
import { fileNameFromDisposition } from '@/lib/utils'
import type {
  Meeting,
  MeetingAgendaItem,
  MeetingAgendaItemCreatePayload,
  MeetingAgendaItemUpdatePayload,
  MeetingAttachment,
  MeetingAttachmentKind,
  MeetingCreatePayload,
  TeamsCallTokenResponse,
  TeamsJoinResponse,
  TeamsRecording,
  MeetingListItem,
  MeetingUpdatePayload,
} from '@/types'

/**
 * وحدة "إدارة الاجتماعات" — تقابل app/api/v1/meetings.py بالباك-إند.
 * التفويض هيكلي (دور اللجنة/النظام)، وليس صلاحية عامة ثابتة — راجعي
 * hooks/useMeetings.ts وMeetingsPage.tsx لتفصيل كيفية تحديد ذلك بالواجهة.
 */

export async function fetchMeetings(): Promise<MeetingListItem[]> {
  const { data } = await apiClient.get<MeetingListItem[]>('/meetings')
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

/**
 * POST /meetings/{id}/extend — تمديد وقت نهاية الاجتماع قبله أو أثناءه
 * (طلب لاما 2026-11-01). new_end_at بصيغة ISO. يرمي 400 لوقت غير صالح
 * (ليس بعد النهاية الحالية/خارج فترة اللجنة)، 403 بلا صلاحية، 409 لو انتهى.
 */
export async function extendMeeting(meetingId: string, newEndAt: string): Promise<Meeting> {
  const { data } = await apiClient.post<Meeting>(`/meetings/${meetingId}/extend`, { new_end_at: newEndAt })
  return data
}

/**
 * POST /meetings/with-attachments (multipart) — طلب لاما 2026-11-01: إنشاء
 * الاجتماع مع العرض التقديمي ومرفقاته ومرفقات كل بند بطلب واحد، فيُرسل بريد
 * "اجتماع جديد" واحد فيه كل الملفات (بدل بريد ثم رفع منفصل).
 * agendaFiles[i] = ملفات البند i بنفس ترتيب payload.agenda_items.
 * failed_files: ملفات تعذّر رفعها بعد إنشاء الاجتماع (الاجتماع يبقى).
 */
export async function createMeetingWithAttachments(
  payload: MeetingCreatePayload,
  files: { presentation: File | null; attachments: File[]; agendaFiles: File[][] },
): Promise<{ meeting: Meeting; failed_files: string[] }> {
  const form = new FormData()
  form.append('payload', JSON.stringify(payload))
  if (files.presentation) form.append('presentation', files.presentation)
  files.attachments.forEach((f) => form.append('attachments', f))
  files.agendaFiles.forEach((list, index) =>
    list.forEach((f) => {
      form.append('agenda_files', f)
      form.append('agenda_file_indexes', String(index))
    }),
  )
  const { data } = await apiClient.post<{ meeting: Meeting; failed_files: string[] }>(
    '/meetings/with-attachments',
    form,
    { headers: { 'Content-Type': 'multipart/form-data' } },
  )
  return data
}

/**
 * POST /meetings/{id}/agenda-items/{itemId}/attachments — إرفاق ملفات ببند
 * بعد إنشاء الاجتماع؛ يرسل بريد "مرفقات جديدة للبند" للمشاركين.
 */
export async function uploadAgendaItemAttachments(
  meetingId: string,
  agendaItemId: string,
  files: File[],
): Promise<MeetingAttachment[]> {
  const form = new FormData()
  files.forEach((f) => form.append('files', f))
  const { data } = await apiClient.post<MeetingAttachment[]>(
    `/meetings/${meetingId}/agenda-items/${agendaItemId}/attachments`,
    form,
    { headers: { 'Content-Type': 'multipart/form-data' } },
  )
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
 * رابط الانضمام لاجتماع Microsoft Teams (GET /meetings/{id}/teams/join).
 * الباك-إند يتحقق من meetings.join وأن الاجتماع عن بعد مربوط بتيمز ولم ينتهِ
 * (409 غير ذلك، 403 بلا صلاحية). يُطلب عند الضغط على "الانضمام" فقط — لا
 * يُخزَّن بالواجهة ولا يأتي ضمن تفاصيل الاجتماع.
 */
export async function getTeamsJoinUrl(meetingId: string): Promise<TeamsJoinResponse> {
  const { data } = await apiClient.get<TeamsJoinResponse>(`/meetings/${meetingId}/teams/join`)
  return data
}

/**
 * تجربة الانضمام المدمج (Azure Communication Services): توكن قصير العمر + رابط
 * اجتماع Teams + اسم العرض — نفس فحوص getTeamsJoinUrl بالباك-إند (meetings.join،
 * مربوط بتيمز، لم ينتهِ). 503 لو ACS غير مهيّأ بالخادم.
 */
export async function getTeamsCallToken(meetingId: string): Promise<TeamsCallTokenResponse> {
  const { data } = await apiClient.post<TeamsCallTokenResponse>(`/meetings/${meetingId}/teams/call-token`)
  return data
}

/**
 * تسجيلات Teams للاجتماع (meetings.record_audio) — قائمة فارغة لو لم يُسجَّل
 * الاجتماع، أو انتهت مدة احتفاظ تيمز بالتسجيل.
 */
export async function listTeamsRecordings(meetingId: string): Promise<TeamsRecording[]> {
  const { data } = await apiClient.get<TeamsRecording[]>(`/meetings/${meetingId}/teams/recordings`)
  return data
}

/**
 * محتوى تسجيل Teams كـBlob — عبر axios (Authorization header) لا رابط مباشر،
 * نفس نمط fetchMeetingRecordingBlob. الباك-إند يبث الملف من تيمز بلا تخزينه.
 */
export async function fetchTeamsRecordingBlob(
  meetingId: string,
  recordingId: string,
): Promise<{ blob: Blob; fileName: string }> {
  const response = await apiClient.get(
    `/meetings/${meetingId}/teams/recordings/${encodeURIComponent(recordingId)}/content`,
    { responseType: 'blob' },
  )
  const disposition = String(response.headers['content-disposition'] ?? '')
  const match = /filename="?([^"]+)"?/.exec(disposition)
  return { blob: response.data as Blob, fileName: match?.[1] ?? 'meeting-recording.mp4' }
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
  return { blob: response.data as Blob, fileName: fileNameFromDisposition(disposition, 'attachment') }
}
