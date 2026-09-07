import { apiClient } from '@/lib/apiClient'
import type { MeetingChatMessage } from '@/types'

/**
 * تحميل تاريخ محادثة الاجتماع (REST، مرة واحدة عند فتح لوحة "المحادثة") —
 * الرسائل الجديدة بعدها تصل فوريًا عبر WebSocket، راجعي
 * hooks/useMeetingRealtime.ts وapp/api/v1/meetings.py::get_meeting_chat_messages.
 */
export async function fetchMeetingChatMessages(meetingId: string): Promise<MeetingChatMessage[]> {
  const { data } = await apiClient.get<MeetingChatMessage[]>(`/meetings/${meetingId}/chat/messages`)
  return data
}
