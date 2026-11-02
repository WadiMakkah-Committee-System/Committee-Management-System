import { ExternalLink, Info, Loader2, Video } from 'lucide-react'
import { useTeamsJoinUrl } from '@/hooks/useMeetings'
import { useToast } from '@/components/ui/Toast'
import { extractErrorMessage } from '@/lib/utils'
import type { Meeting } from '@/types'

/**
 * الهدف:
 * المساحة الرئيسية بغرفة الاجتماع بعد الانتقال لـMicrosoft Teams (2026-11-02،
 * بديل MeetingStage.tsx الخاص بفيديو Agora). الصوت/الفيديو/مشاركة الشاشة/
 * التسجيل كلها داخل تيمز نفسه — هذه الغرفة تبقى مساحة إدارة الجلسة (الأجندة،
 * القرارات، المحادثة، رفع اليد...) بجانب نافذة تيمز.
 *
 * المسؤولية:
 * - زر "الانضمام عبر تيمز": يطلب الرابط من الباك-إند لحظة الضغط (فحص
 *   meetings.join هناك) ويفتحه بتبويب جديد — تيمز يعرض عادةً خيار فتحه
 *   بالتطبيق أو بالمتصفح.
 * - تنبيه لرئيس اللجنة بتشغيل التسجيل والتفريغ من داخل تيمز (بدونهما لا
 *   تُولَّد مسودة المحضر تلقائيًا بعد الاجتماع).
 * - حالة "غير مربوط بتيمز" (اجتماع قديم أو تكامل غير مهيّأ بالخادم).
 *
 * المدخلات:
 * - meeting: الاجتماع (has_teams_meeting يحدد الحالة).
 * - canRecord: هل المستخدم رئيس اللجنة/صاحب meetings.record_audio (لعرض تنبيه التسجيل فقط).
 *
 * التأثيرات الجانبية: GET /meetings/{id}/teams/join عند الضغط + فتح تبويب.
 * الأخطاء: تُعرض كـToast (403 بلا صلاحية، 409 انتهى/غير مربوط).
 */
export function TeamsMeetingStage({ meeting, canRecord }: { meeting: Meeting; canRecord: boolean }) {
  const joinMutation = useTeamsJoinUrl()
  const { showToast } = useToast()

  async function handleJoin() {
    // نفتح التبويب قبل انتظار الطلب: المتصفح يحجب window.open بعد await
    // (لم يعد "ناتجًا عن ضغطة المستخدم" مباشرة)، ثم نوجّهه للرابط عند وصوله.
    const tab = window.open('', '_blank')
    try {
      const { join_url } = await joinMutation.mutateAsync(meeting.meeting_id)
      if (tab) {
        tab.opener = null
        tab.location.href = join_url
      } else {
        window.location.assign(join_url)
      }
    } catch (err) {
      tab?.close()
      showToast(extractErrorMessage(err), 'error')
    }
  }

  if (!meeting.has_teams_meeting) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 rounded-lg bg-[#1b2338] p-6 text-center">
        <Info size={26} className="text-white/40" />
        <p className="max-w-sm text-sm text-white/70">
          هذا الاجتماع غير مربوط بـMicrosoft Teams، لذلك لا يتوفر رابط انضمام له.
        </p>
        <p className="max-w-sm text-xs text-white/40">
          يمكنك متابعة الأجندة والقرارات والمحادثة من اللوحة الجانبية.
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-5 rounded-lg bg-[#1b2338] p-6 text-center">
      <span className="flex h-16 w-16 items-center justify-center rounded-full bg-brand-primary/15 text-brand-accent">
        <Video size={30} />
      </span>
      <div className="flex flex-col gap-1.5">
        <h2 className="text-lg font-semibold text-white">الاجتماع يُعقد عبر Microsoft Teams</h2>
        <p className="max-w-md text-sm text-white/60">
          الصوت والفيديو ومشاركة الشاشة داخل تيمز. أبقِ هذه الصفحة مفتوحة لمتابعة الأجندة والقرارات والمحادثة.
        </p>
      </div>

      <button
        type="button"
        onClick={handleJoin}
        disabled={joinMutation.isPending}
        className="flex h-11 items-center gap-2 rounded-full bg-brand-primary px-6 text-sm font-semibold text-white transition-all hover:brightness-110 active:scale-95 disabled:opacity-60"
      >
        {joinMutation.isPending ? <Loader2 size={17} className="animate-spin" /> : <ExternalLink size={17} />}
        الانضمام عبر تيمز
      </button>

      {canRecord && (
        <div className="flex max-w-md items-start gap-2 rounded-md border border-warning/30 bg-warning-bg px-3 py-2 text-right text-[12px] text-warning">
          <Info size={14} className="mt-0.5 shrink-0" />
          <span>
            بصفتك رئيس اللجنة: شغّل <strong>التسجيل والتفريغ</strong> من داخل تيمز (المزيد ← التسجيل والتفريغ) — بدونهما
            لا يمكن توليد مسودة المحضر بعد الاجتماع.
          </span>
        </div>
      )}
    </div>
  )
}
