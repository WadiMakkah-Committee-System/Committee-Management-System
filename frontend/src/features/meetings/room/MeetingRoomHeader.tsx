import { useEffect, useState } from 'react'
import { ChevronDown, Link2, Share2, Users } from 'lucide-react'
import { Avatar } from '@/components/ui/Avatar'
import { useToast } from '@/components/ui/Toast'
import { MeetingStatusBadge } from '@/components/ui/StatusBadge'
import { useAuthStore } from '@/store/authStore'
import type { Meeting } from '@/types'

/**
 * رأس غرفة الاجتماع — إعادة تصميم 2026-09-06 لمطابقة الواجهة المرجعية
 * بالضبط: يمين = صاحبة الجلسة الحالية (بدل منشئ الاجتماع سابقًا)، وسط =
 * زر "مشاركة" بارز يعرض رابط الاجتماع الفعلي (وليس مجرد أيقونة صغيرة
 * كما كان)، يسار = عنوان الاجتماع + زر فتح لوحة "المشاركون" + الوقت
 * المنقضي + شارة الحالة + التاريخ. زر الإغلاق (X) المنفصل أُزيل عمدًا —
 * المرجع لا يعرضه؛ المغادرة تصير فقط عبر زر "مغادرة" البارز بشريط
 * التحكم السفلي أو "خروج" بالشريط الجانبي العام (MeetingRoomAppRail.tsx)
 * — كلاهما يفتح نفس نافذة تأكيد المغادرة الحقيقية أصلًا.
 */
export function MeetingRoomHeader({
  meeting,
  onOpenParticipants,
}: {
  meeting: Meeting
  onOpenParticipants: () => void
}) {
  const currentUser = useAuthStore((s) => s.user)
  const { showToast } = useToast()
  const [elapsed, setElapsed] = useState('')

  useEffect(() => {
    if (!meeting.started_at) return
    const started = new Date(meeting.started_at).getTime()
    const update = () => {
      const diff = Math.max(0, Date.now() - started)
      const totalSeconds = Math.floor(diff / 1000)
      const h = String(Math.floor(totalSeconds / 3600)).padStart(2, '0')
      const m = String(Math.floor((totalSeconds % 3600) / 60)).padStart(2, '0')
      const s = String(totalSeconds % 60).padStart(2, '0')
      setElapsed(`${h}:${m}:${s}`)
    }
    update()
    const interval = setInterval(update, 1000)
    return () => clearInterval(interval)
  }, [meeting.started_at])

  const meetingUrl = `${window.location.origin}/meetings/${meeting.meeting_id}`

  function copyLink() {
    navigator.clipboard
      .writeText(meetingUrl)
      .then(() => showToast('تم نسخ رابط الاجتماع'))
      .catch(() => showToast('تعذّر نسخ الرابط', 'error'))
  }

  const formattedDate = new Intl.DateTimeFormat('ar-SA-u-ca-gregory-nu-latn', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  }).format(new Date(meeting.scheduled_at))

  return (
    <header className="flex h-16 shrink-0 items-center justify-between gap-3 border-b border-border-default bg-bg-surface px-4">
      {/* يمين: صاحبة الجلسة الحالية */}
      <div className="flex shrink-0 items-center gap-2.5">
        <Avatar firstName={currentUser?.first_name ?? ''} lastName={currentUser?.last_name ?? ''} size={34} />
        <div className="hidden leading-tight sm:block">
          <p className="text-[13px] font-bold text-text-primary">
            {currentUser ? `${currentUser.first_name} ${currentUser.last_name}` : ''}
          </p>
          <p className="flex items-center gap-1 text-[11px] text-text-muted">
            {currentUser?.role?.name ?? 'عضو اللجنة'}
            <ChevronDown size={12} />
          </p>
        </div>
      </div>

      {/* وسط: رابط مشاركة الاجتماع */}
      <button
        type="button"
        onClick={copyLink}
        className="flex min-w-0 flex-1 items-center justify-center gap-2 rounded-full border border-border-default bg-bg-elevated px-4 py-2 text-[12px] text-text-secondary transition-colors hover:border-brand-primary hover:text-brand-primary"
      >
        <Share2 size={13} className="shrink-0" />
        <span className="shrink-0 font-semibold">مشاركة</span>
        <span className="h-4 w-px shrink-0 bg-border-default" />
        <Link2 size={13} className="shrink-0" />
        <span className="truncate font-mono">{meetingUrl}</span>
      </button>

      {/* يسار: عنوان الاجتماع وحالته */}
      <div className="flex shrink-0 items-center gap-3">
        <div className="text-right leading-tight">
          <p className="flex items-center justify-end gap-1.5 text-[13px] font-bold text-text-primary">
            <button
              type="button"
              onClick={onOpenParticipants}
              className="flex h-6 w-6 items-center justify-center rounded-full text-text-muted transition-colors hover:bg-bg-elevated hover:text-brand-primary"
              aria-label="المشاركون"
              title="المشاركون"
            >
              <Users size={14} />
            </button>
            <span className="truncate">{meeting.title}</span>
          </p>
          <div className="mt-0.5 flex items-center justify-end gap-2 text-[11px] text-text-muted">
            <span>{formattedDate}</span>
            <MeetingStatusBadge status={meeting.status} />
            {elapsed && <span className="font-mono">{elapsed}</span>}
          </div>
        </div>
      </div>
    </header>
  )
}
