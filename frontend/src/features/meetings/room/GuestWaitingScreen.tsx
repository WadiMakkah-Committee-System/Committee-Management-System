import { Hourglass, Loader2, LogOut, RotateCcw } from 'lucide-react'
import type { Meeting } from '@/types'
import type { TeamsEmbeddedCall } from './useTeamsEmbeddedCall'

/**
 * الهدف (قرار لاما 2026-11-03): شاشة انتظار كاملة للضيف (دخل المنصة بكلمة
 * المرور / بدون حساب Microsoft بالشركة) — ما يشوف الأجندة ولا المرفقات ولا
 * القرارات ولا المشاركين لين ينقبل بالاجتماع، وبعدها تفتح له الغرفة كاملة.
 *
 * ملاحظة: الإخفاء هنا بالواجهة (غرفة الاجتماع) — صلاحيات الاطلاع على بيانات
 * الاجتماع خارج الغرفة (صفحة التفاصيل) تبقى حسب أدوار المنصة كما هي.
 *
 * المدخلات: meeting، call (الحالة + start لإعادة المحاولة)، onLeave (تأكيد المغادرة).
 */
export function GuestWaitingScreen({
  meeting,
  call,
  onLeave,
}: {
  meeting: Meeting
  call: TeamsEmbeddedCall
  onLeave: () => void
}) {
  const failed = call.phase === 'error' || call.phase === 'ended'
  return (
    <div className="flex flex-1 items-center justify-center p-6">
      <div className="flex w-full max-w-md flex-col items-center gap-5 rounded-lg bg-[#1b2338] p-8 text-center">
        <span className="flex h-16 w-16 items-center justify-center rounded-full bg-warning-bg text-warning">
          {call.phase === 'lobby' ? <Hourglass size={28} /> : failed ? <RotateCcw size={28} /> : <Loader2 size={28} className="animate-spin" />}
        </span>
        <div className="flex flex-col gap-1.5">
          <p className="text-xs text-white/50">{meeting.title}</p>
          <h2 className="text-lg font-semibold text-white">
            {call.phase === 'lobby'
              ? 'بانتظار السماح بدخولك'
              : failed
                ? call.phase === 'ended'
                  ? 'غادرت الاجتماع'
                  : 'تعذّر الدخول للاجتماع'
                : 'جاري الاتصال بالاجتماع...'}
          </h2>
          <p className="text-sm text-white/60">
            {call.phase === 'lobby'
              ? 'بتدخل أول ما يسمح لك منظّم الاجتماع أو رئيس اللجنة. خلّك على هالصفحة.'
              : failed
                ? call.errorMessage || 'تقدر تحاول مرة ثانية.'
                : 'لو طلب المتصفح إذن الكاميرا والمايك، اسمح له.'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {failed && (
            <button
              type="button"
              onClick={() => void call.start(true)}
              className="flex h-10 items-center gap-2 rounded-full bg-brand-primary px-5 text-sm font-semibold text-white transition-all hover:brightness-110"
            >
              <RotateCcw size={15} />
              إعادة المحاولة
            </button>
          )}
          <button
            type="button"
            onClick={onLeave}
            className="flex h-10 items-center gap-2 rounded-full bg-white/10 px-5 text-sm font-medium text-white transition-colors hover:bg-white/20"
          >
            <LogOut size={15} />
            مغادرة
          </button>
        </div>
      </div>
    </div>
  )
}
