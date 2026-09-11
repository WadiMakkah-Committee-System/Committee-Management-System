import { apiClient } from '@/lib/apiClient'
import type { MeetingMinutes, MinutesSection, MinutesTemplate, MinutesTemplateId } from '@/types'

/**
 * وحدة "المحاضر" (SRS §7) — تقابل app/api/v1/meetings.py (مسارات
 * /minutes/*)، راجعي رأس app/services/meeting_minutes_service.py
 * للتصميم الكامل. شاشة مستقلة (MeetingMinutesPage.tsx) داخل قسم
 * الاجتماعات، تُفتح من زر "محضر الاجتماع" بصفحة تفاصيل الاجتماع.
 */

export async function fetchMinutesTemplates(meetingId: string): Promise<MinutesTemplate[]> {
  const { data } = await apiClient.get<MinutesTemplate[]>(`/meetings/${meetingId}/minutes/templates`)
  return data
}

export async function fetchMeetingMinutes(meetingId: string): Promise<MeetingMinutes> {
  const { data } = await apiClient.get<MeetingMinutes>(`/meetings/${meetingId}/minutes`)
  return data
}

export async function selectMinutesTemplate(
  meetingId: string,
  templateId: MinutesTemplateId,
): Promise<MeetingMinutes> {
  const { data } = await apiClient.post<MeetingMinutes>(`/meetings/${meetingId}/minutes/template`, {
    template_id: templateId,
  })
  return data
}

export async function updateMinutesSections(
  meetingId: string,
  sections: MinutesSection[],
): Promise<MeetingMinutes> {
  const { data } = await apiClient.put<MeetingMinutes>(`/meetings/${meetingId}/minutes/sections`, {
    sections,
  })
  return data
}

export async function approveMinutesReview(meetingId: string, comment?: string): Promise<MeetingMinutes> {
  const { data } = await apiClient.post<MeetingMinutes>(`/meetings/${meetingId}/minutes/review/approve`, {
    comment: comment ?? null,
  })
  return data
}

export async function returnMinutesReview(meetingId: string, comment: string): Promise<MeetingMinutes> {
  const { data } = await apiClient.post<MeetingMinutes>(`/meetings/${meetingId}/minutes/review/return`, {
    comment,
  })
  return data
}

export async function approveMinutes(meetingId: string): Promise<MeetingMinutes> {
  const { data } = await apiClient.post<MeetingMinutes>(`/meetings/${meetingId}/minutes/approve`, {})
  return data
}

export async function returnMinutesForEdit(meetingId: string, comment: string): Promise<MeetingMinutes> {
  const { data } = await apiClient.post<MeetingMinutes>(`/meetings/${meetingId}/minutes/return`, {
    comment,
  })
  return data
}

export async function sendMinutesForSignature(meetingId: string): Promise<MeetingMinutes> {
  const { data } = await apiClient.post<MeetingMinutes>(`/meetings/${meetingId}/minutes/signature/send`, {})
  return data
}

export async function signMinutes(meetingId: string, signatureImage: string): Promise<MeetingMinutes> {
  const { data } = await apiClient.post<MeetingMinutes>(`/meetings/${meetingId}/minutes/sign`, {
    signature_image: signatureImage,
  })
  return data
}
