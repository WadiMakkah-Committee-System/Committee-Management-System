import { apiClient } from '@/lib/apiClient'
import type { MeetingDraft, MeetingRecording } from '@/types'

/**
 * وحدة "التسجيل الصوتي + المسودة" — تقابل app/api/v1/meetings.py
 * (راجعي رأس db/migrations/0025_meeting_recordings_and_drafts.sql
 * وapp/core/gemini_client.py للتصميم الكامل). راجعي RecordingPanel.tsx
 * لطريقة الاستخدام (MediaRecorder بالمتصفح → رفع الملف الناتج هنا).
 */

export async function uploadMeetingRecording(
  meetingId: string,
  file: File,
  durationSeconds?: number,
): Promise<MeetingRecording> {
  const formData = new FormData()
  formData.append('file', file)
  if (durationSeconds !== undefined) {
    formData.append('duration_seconds', String(Math.round(durationSeconds)))
  }
  const { data } = await apiClient.post<MeetingRecording>(
    `/meetings/${meetingId}/recording`,
    formData,
  )
  return data
}

/**
 * تنزيل ملف التسجيل الصوتي الفعلي — نفس نمط fetchMeetingAttachmentBlob
 * بـapi/meetings.ts بالضبط (Authorization Bearer بالـheader يتطلب المرور
 * عبر axios بـresponseType: 'blob'، لا <a href> مباشر). تعديل لاما
 * 2026-09-06: يظهر بقسم "التسجيل والمسودة" بصفحة تفاصيل الاجتماع بعد
 * انتهائه (MeetingDetailPage.tsx) — راجعي app/api/v1/meetings.py::
 * download_meeting_recording بالباك-إند.
 */
export async function fetchMeetingRecordingBlob(
  meetingId: string,
): Promise<{ blob: Blob; fileName: string }> {
  const response = await apiClient.get(`/meetings/${meetingId}/recording/download`, {
    responseType: 'blob',
  })
  const disposition = String(response.headers['content-disposition'] ?? '')
  const match = /filename="?([^"]+)"?/.exec(disposition)
  return { blob: response.data as Blob, fileName: match?.[1] ?? 'recording' }
}

export async function fetchMeetingRecording(meetingId: string): Promise<MeetingRecording | null> {
  try {
    const { data } = await apiClient.get<MeetingRecording>(`/meetings/${meetingId}/recording`)
    return data
  } catch (err: unknown) {
    if (isNotFound(err)) return null
    throw err
  }
}

export async function generateMeetingDraft(meetingId: string): Promise<MeetingDraft> {
  const { data } = await apiClient.post<MeetingDraft>(`/meetings/${meetingId}/draft`)
  return data
}

export async function fetchMeetingDraft(meetingId: string): Promise<MeetingDraft | null> {
  try {
    const { data } = await apiClient.get<MeetingDraft>(`/meetings/${meetingId}/draft`)
    return data
  } catch (err: unknown) {
    if (isNotFound(err)) return null
    throw err
  }
}

function isNotFound(err: unknown): boolean {
  return (
    typeof err === 'object' &&
    err !== null &&
    'response' in err &&
    (err as { response?: { status?: number } }).response?.status === 404
  )
}
