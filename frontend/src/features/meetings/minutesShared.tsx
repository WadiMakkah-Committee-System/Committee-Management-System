import { Check, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { MeetingMinutesStage } from '@/types'

/**
 * الهدف:
 * عناصر مشتركة بين صفحة محضر اجتماع واحد (MeetingMinutesPage.tsx) وقائمة
 * "المحاضر" العامة (MinutesListPage.tsx) — آلة حالة المحضر بصريًا (شارة +
 * Timeline)، بدل تكرارها بالملفين. أُخرجت من MeetingMinutesPage.tsx بعد
 * إضافة MinutesListPage.tsx (طلب لاما: عنصر "المحاضر" بالقائمة الجانبية).
 */

/** يستخرج كود حالة HTTP من خطأ axios (أو undefined لو الشكل غير متوقَّع) —
 * مشتركة بين MinutesListPage.tsx وMeetingMinutesPage.tsx لتمييز 409
 * (الاجتماع لم ينتهِ بعد — حالة عمل طبيعية متوقَّعة من get_or_create_minutes
 * بالباك-إند) عن 403 (لا صلاحية فعليًا) عن أي خطأ شبكة/سيرفر حقيقي آخر،
 * بدل عرضهم كلهم برسالة عامة واحدة مضلِّلة ("خطأ اتصال بالخادم" لحالة
 * متوقَّعة تمامًا وليست خطأ إطلاقًا). إصلاح 2026-09-09 (بلاغ لاما: ضغطت
 * "متابعة الإجراء" على اجتماع لم ينتهِ بعد، طلعت رسالة "تعذّر تحميل
 * المحضر... خطأ اتصال بالخادم" رغم إن الباك-إند رد 409 بسرعة وبلا أي
 * تعليق فعلي — المشكلة كانت رسالة العرض فقط، لا اتصال حقيقي).
 */
export function errorStatusOf(error: unknown): number | null {
  if (typeof error === 'object' && error !== null && 'response' in error) {
    const status = (error as { response?: { status?: number } }).response?.status
    return typeof status === 'number' ? status : null
  }
  return null
}

export const STAGE_ORDER: MeetingMinutesStage[] = ['preparing', 'review', 'approval', 'signature', 'completed']

export type Tone = 'success' | 'warning' | 'danger' | 'info' | 'neutral'

export const STAGE_META: Record<MeetingMinutesStage, { label: string; tone: Tone }> = {
  none: { label: 'لم يبدأ', tone: 'neutral' },
  preparing: { label: 'قيد الإعداد', tone: 'info' },
  review: { label: 'قيد المراجعة', tone: 'warning' },
  approval: { label: 'بانتظار الاعتماد', tone: 'warning' },
  signature: { label: 'بانتظار التوقيع', tone: 'info' },
  completed: { label: 'مكتمل', tone: 'success' },
}

export const TONE_CLASSES: Record<Tone, string> = {
  success: 'bg-success-bg text-success border-success-border/30',
  warning: 'bg-warning-bg text-warning border-warning-border/30',
  danger: 'bg-danger-bg text-danger border-danger-border/30',
  info: 'bg-info-bg text-info border-info-border/30',
  neutral: 'bg-neutral-bg text-neutral border-neutral-border/30',
}

export function MinutesStageBadge({ stage }: { stage: MeetingMinutesStage }) {
  const meta = STAGE_META[stage]
  return (
    <span
      className={cn(
        'inline-flex w-fit items-center gap-1.5 rounded-xs border px-2 py-1 text-xs font-semibold',
        TONE_CLASSES[meta.tone],
      )}
    >
      {meta.label}
    </span>
  )
}

export function StageTimeline({ stage, compact = false }: { stage: MeetingMinutesStage; compact?: boolean }) {
  const started = stage !== 'none'
  const idx = STAGE_ORDER.indexOf(stage === 'none' ? 'preparing' : stage)
  return (
    <ol className={cn('flex w-full items-center', compact ? 'gap-1' : 'gap-2')}>
      {STAGE_ORDER.map((s, i) => {
        const done = started && i < idx
        const current = started && i === idx
        return (
          <li key={s} className="flex flex-1 items-center gap-2">
            <div className="flex flex-col items-center gap-1.5">
              <span
                className={cn(
                  'flex shrink-0 items-center justify-center rounded-full border font-semibold transition-colors',
                  compact ? 'h-5 w-5 text-[9px]' : 'h-7 w-7 text-[11px]',
                  done && 'border-success bg-success text-white',
                  current && 'border-brand-primary bg-brand-primary text-white',
                  !done && !current && 'border-border-default bg-bg-elevated text-text-muted',
                )}
              >
                {done ? (
                  <Check size={compact ? 10 : 14} />
                ) : current ? (
                  <Loader2 size={compact ? 10 : 14} className="animate-spin" />
                ) : (
                  i + 1
                )}
              </span>
              {!compact && (
                <span
                  className={cn(
                    'whitespace-nowrap text-[11px]',
                    current ? 'font-semibold text-text-primary' : 'text-text-muted',
                  )}
                >
                  {STAGE_META[s].label}
                </span>
              )}
            </div>
            {i < STAGE_ORDER.length - 1 && (
              <span className={cn('h-0.5 flex-1 rounded-full', done ? 'bg-success' : 'bg-border-default')} />
            )}
          </li>
        )
      })}
    </ol>
  )
}
