import { apiClient } from '@/lib/apiClient'
import type {
  Meeting,
  MeetingAgendaItem,
  MeetingAgendaItemCreatePayload,
  MeetingAgendaItemUpdatePayload,
  MeetingCreatePayload,
  MeetingUpdatePayload,
} from '@/types'

/**
 * وحدة "إدارة الاجتماعات" — تقابل app/api/v1/meetings.py بالباك-إند.
 * بدون Teams/AI في هذا الـPhase (راجعي رأس meeting_service.py بالباك-إند
 * للقرار الموثّق). التفويض هنا هيكلي (رئيس اللجنة)، وليس صلاحية عامة —
 * راجعي hooks/useMeetings.ts وMeetingsPage.tsx لتفصيل كيفية تحديد ذلك
 * بالواجهة.
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
