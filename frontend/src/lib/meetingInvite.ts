import { fetchGuestLink, guestJoinUrl } from '@/api/meetingGuests'
import type { Meeting } from '@/types'

/**
 * نص "دعوة الاجتماع" الذي يُنسخ للمشاركة (طلب لاما 2026-11-10): عنوان الاجتماع
 * وتاريخه ووقته ومكانه ورابطه — جاهز للصق بواتساب أو الإيميل.
 *
 * الرابط: رابط الضيوف (/join/...) للاجتماع عن بُعد القائم — يدخل منه أي شخص
 * بدون حساب بعد قبوله (migration 0047). وإلا (حضوري/منتهٍ/بلا صلاحية) رابط
 * صفحة الاجتماع بالمنصة — راجعي resolveInviteUrl.
 */

const DATE_FMT = new Intl.DateTimeFormat('ar-SA-u-ca-gregory-nu-latn', {
  weekday: 'long',
  day: 'numeric',
  month: 'long',
  year: 'numeric',
  timeZone: 'Asia/Riyadh',
})

const TIME_FMT = new Intl.DateTimeFormat('ar-SA-u-ca-gregory-nu-latn', {
  hour: 'numeric',
  minute: '2-digit',
  timeZone: 'Asia/Riyadh',
})

export function meetingPageUrl(meetingId: string): string {
  return `${window.location.origin}/meetings/${meetingId}`
}

export function buildMeetingInvite(
  meeting: Pick<Meeting, 'meeting_id' | 'title' | 'scheduled_at' | 'scheduled_end_at' | 'mode' | 'location'>,
  options: { committeeName?: string | null; url?: string } = {},
): string {
  const start = new Date(meeting.scheduled_at)
  const time = meeting.scheduled_end_at
    ? `${TIME_FMT.format(start)} – ${TIME_FMT.format(new Date(meeting.scheduled_end_at))}`
    : TIME_FMT.format(start)

  const lines = [`دعوة لحضور اجتماع: ${meeting.title}`]
  if (options.committeeName) lines.push(`اللجنة: ${options.committeeName}`)
  lines.push(`📅 ${DATE_FMT.format(start)}`)
  lines.push(`🕐 ${time} (بتوقيت الرياض)`)
  if (meeting.mode === 'in_person') {
    lines.push(`📍 حضوري${meeting.location ? `: ${meeting.location}` : ''}`)
  } else {
    lines.push('💻 عن بُعد')
  }
  lines.push(`🔗 ${options.url ?? meetingPageUrl(meeting.meeting_id)}`)
  return lines.join('\n')
}

/** رابط الدعوة الأنسب: رابط الضيوف لو متاح، وإلا رابط صفحة الاجتماع. */
export async function resolveInviteUrl(
  meeting: Pick<Meeting, 'meeting_id' | 'mode' | 'status'>,
): Promise<string> {
  if (meeting.mode === 'remote' && (meeting.status === 'upcoming' || meeting.status === 'ongoing')) {
    try {
      return guestJoinUrl(await fetchGuestLink(meeting.meeting_id))
    } catch {
      // بلا صلاحية/غير متاح ⇒ رابط الصفحة.
    }
  }
  return meetingPageUrl(meeting.meeting_id)
}

/** ينسخ نص الدعوة الكامل للحافظة (برابط الضيوف لو متاح). */
export async function copyMeetingInvite(
  meeting: Pick<Meeting, 'meeting_id' | 'title' | 'scheduled_at' | 'scheduled_end_at' | 'mode' | 'location' | 'status'>,
  committeeName?: string | null,
): Promise<void> {
  const url = await resolveInviteUrl(meeting)
  await navigator.clipboard.writeText(buildMeetingInvite(meeting, { committeeName, url }))
}
