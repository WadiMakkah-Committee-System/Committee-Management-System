import { apiClient } from '@/lib/apiClient'
import type { DecisionClassification, MeetingExtractedItem } from '@/types'

/**
 * وحدة "البنود المستخرجة من الاجتماع" — تقابل app/api/v1/meetings.py
 * (مسارات /extracted-items/*)، راجعي رأس app/services/meeting_service.py
 * (قسم "البنود المستخرجة من الاجتماع") للتصميم الكامل. شاشة ترياج واحدة
 * بصفحة تفاصيل الاجتماع — راجعي MeetingDetailPage.tsx.
 */

export async function extractMeetingItems(meetingId: string): Promise<MeetingExtractedItem[]> {
  const { data } = await apiClient.post<MeetingExtractedItem[]>(
    `/meetings/${meetingId}/extracted-items/extract`,
  )
  return data
}

export async function fetchMeetingExtractedItems(
  meetingId: string,
): Promise<MeetingExtractedItem[]> {
  const { data } = await apiClient.get<MeetingExtractedItem[]>(
    `/meetings/${meetingId}/extracted-items`,
  )
  return data
}

export async function addManualExtractedItem(
  meetingId: string,
  text: string,
): Promise<MeetingExtractedItem> {
  const { data } = await apiClient.post<MeetingExtractedItem>(
    `/meetings/${meetingId}/extracted-items`,
    { text },
  )
  return data
}

export async function deleteExtractedItem(meetingId: string, itemId: string): Promise<void> {
  await apiClient.delete(`/meetings/${meetingId}/extracted-items/${itemId}`)
}

export interface AssignAsTaskPayload {
  title?: string
  start_date: string
  end_date: string
  assignee_user_id: string
}

export async function assignExtractedItemAsTask(
  meetingId: string,
  itemId: string,
  payload: AssignAsTaskPayload,
): Promise<MeetingExtractedItem> {
  const { data } = await apiClient.post<MeetingExtractedItem>(
    `/meetings/${meetingId}/extracted-items/${itemId}/assign-task`,
    payload,
  )
  return data
}

export interface AssignAsDecisionPayload {
  title?: string
  classification: DecisionClassification
  start_date: string
  end_date: string
}

export async function assignExtractedItemAsDecision(
  meetingId: string,
  itemId: string,
  payload: AssignAsDecisionPayload,
): Promise<MeetingExtractedItem> {
  const { data } = await apiClient.post<MeetingExtractedItem>(
    `/meetings/${meetingId}/extracted-items/${itemId}/assign-decision`,
    payload,
  )
  return data
}
