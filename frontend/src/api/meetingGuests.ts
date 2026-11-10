import axios from 'axios'
import { API_BASE_URL, apiClient } from '@/lib/apiClient'
import type {
  GuestJoinRequestCreated,
  GuestRequestStatusResponse,
  MeetingGuestRequest,
  PublicMeetingInvite,
} from '@/types'

/**
 * دخول الضيوف للاجتماع برابط عام (migration 0047 — قرار لاما 2026-11-10).
 *
 * - لمن داخل الاجتماع (apiClient — مصادَق): رابط الضيوف وقاعة الانتظار.
 * - عامة (publicClient — بلا توكن ولا اعتراض 401/تجديد الجلسة): صفحة الدعوة
 *   وطلب الدخول ومتابعته. منفصلة عمدًا عن apiClient حتى لا يُرسل توكن عضو
 *   مسجّل الدخول بالخطأ ولا يُطرد عند 401.
 */

const publicClient = axios.create({ baseURL: API_BASE_URL })

// ============================== لمن داخل الاجتماع ==============================

export async function fetchGuestLink(meetingId: string): Promise<string> {
  const { data } = await apiClient.get<{ token: string }>(`/meetings/${meetingId}/guest-link`)
  return data.token
}

export async function rotateGuestLink(meetingId: string): Promise<string> {
  const { data } = await apiClient.post<{ token: string }>(`/meetings/${meetingId}/guest-link/rotate`)
  return data.token
}

export async function fetchGuestRequests(meetingId: string): Promise<MeetingGuestRequest[]> {
  const { data } = await apiClient.get<MeetingGuestRequest[]>(`/meetings/${meetingId}/guest-requests`)
  return data
}

export async function decideGuestRequest(
  meetingId: string,
  requestId: string,
  admit: boolean,
): Promise<MeetingGuestRequest> {
  const { data } = await apiClient.post<MeetingGuestRequest>(
    `/meetings/${meetingId}/guest-requests/${requestId}/${admit ? 'admit' : 'reject'}`,
  )
  return data
}

export function guestJoinUrl(token: string): string {
  return `${window.location.origin}/join/${token}`
}

// ============================== عامة (بدون تسجيل دخول) ==============================

export async function fetchPublicInvite(token: string): Promise<PublicMeetingInvite> {
  const { data } = await publicClient.get<PublicMeetingInvite>(`/public/meeting-invites/${encodeURIComponent(token)}`)
  return data
}

export async function createGuestRequest(token: string, displayName: string): Promise<GuestJoinRequestCreated> {
  const { data } = await publicClient.post<GuestJoinRequestCreated>(
    `/public/meeting-invites/${encodeURIComponent(token)}/requests`,
    { display_name: displayName },
  )
  return data
}

export async function fetchGuestRequestStatus(
  requestId: string,
  secret: string,
): Promise<GuestRequestStatusResponse> {
  const { data } = await publicClient.post<GuestRequestStatusResponse>(`/public/guest-requests/${requestId}/status`, {
    secret,
  })
  return data
}

export async function cancelGuestRequest(requestId: string, secret: string): Promise<void> {
  await publicClient.post(`/public/guest-requests/${requestId}/cancel`, { secret })
}
