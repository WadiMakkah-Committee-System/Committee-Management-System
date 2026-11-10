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

type InviteMeeting = Pick<
  Meeting,
  'meeting_id' | 'title' | 'scheduled_at' | 'scheduled_end_at' | 'mode' | 'location' | 'status' | 'has_teams_meeting'
>

/** هل يُتوقع لهذا الاجتماع رابط ضيوف (عن بُعد، Agora، لم ينتهِ)؟ */
export function expectsGuestLink(meeting: Pick<Meeting, 'mode' | 'status' | 'has_teams_meeting'>): boolean {
  return (
    meeting.mode === 'remote' &&
    !meeting.has_teams_meeting &&
    (meeting.status === 'upcoming' || meeting.status === 'ongoing')
  )
}

/**
 * رابط الدعوة: رابط الضيوف لاجتماع يُتوقع له (يرمي الخطأ لو تعذّر جلبه — لا
 * نستبدله بصمت برابط لا يفتحه إلا أعضاء المنصة — مراجعة PR #116)، وإلا رابط
 * صفحة الاجتماع.
 */
export async function resolveInviteUrl(meeting: Pick<Meeting, 'meeting_id' | 'mode' | 'status' | 'has_teams_meeting'>): Promise<string> {
  if (expectsGuestLink(meeting)) return guestJoinUrl(await fetchGuestLink(meeting.meeting_id))
  return meetingPageUrl(meeting.meeting_id)
}

/**
 * ينسخ نص الدعوة الكامل للحافظة. جلب رابط الضيوف طلب شبكة — وبعض المتصفحات
 * (Safari) ترفض الكتابة للحافظة لو انتهت "لحظة الضغط" قبلها. الحل: نبدأ
 * الكتابة فورًا داخل الضغطة بـClipboardItem يحمل Promise للنص، ونرجع لـwriteText
 * فقط لو المتصفح لا يدعم ذلك (مراجعة PR #116).
 */
export async function copyMeetingInvite(meeting: InviteMeeting, committeeName?: string | null): Promise<void> {
  const textPromise = resolveInviteUrl(meeting).then((url) => buildMeetingInvite(meeting, { committeeName, url }))
  if (typeof ClipboardItem !== 'undefined' && navigator.clipboard?.write) {
    try {
      await navigator.clipboard.write([
        new ClipboardItem({ 'text/plain': textPromise.then((t) => new Blob([t], { type: 'text/plain' })) }),
      ])
      return
    } catch (err) {
      // فشل جلب الرابط نفسه ⇒ نعيد الخطأ (لا نجرب writeText).
      await textPromise
      void err
    }
  }
  await navigator.clipboard.writeText(await textPromise)
}
