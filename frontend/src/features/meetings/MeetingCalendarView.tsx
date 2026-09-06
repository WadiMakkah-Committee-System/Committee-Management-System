import { useCallback, useMemo, useState } from 'react'
import {
  Calendar as RBCalendar,
  dateFnsLocalizer,
  Views,
  type View,
  type NavigateAction,
  type EventPropGetter,
  type DayPropGetter,
} from 'react-big-calendar'
import { format, getDay, parse, startOfWeek } from 'date-fns'
import { arSA } from 'date-fns/locale'
import { ChevronRight, ChevronLeft, CalendarDays, ListTodo } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Meeting, MeetingStatus } from '@/types'
import 'react-big-calendar/lib/css/react-big-calendar.css'
import './meeting-calendar.css'

/**
 * عرض التقويم (Calendar View) لقسم الاجتماعات — مكوّن مستقل يُستخدم بجانب
 * العرض الزمني (Timeline/Agenda) بـMeetingsPage.tsx (مفتاح تبديل بينهما).
 *
 * اختيار المكتبة: react-big-calendar (بند #14 من طلب لاما — حرية اختيار
 * المكتبة مُفوَّضة لي بالكامل 2026-09-05). أسباب الاختيار (قارنّاها مع
 * FullCalendar وto.date/react-day-picker بمرحلة البحث):
 *   - دعم RTL فعلي (prop rtl + كلاس rbc-rtl بأكثر من 12 قاعدة CSS
 *     مخصَّصة بالمكتبة نفسها — تحقّقنا من الكود المصدري وليس فقط الوثائق).
 *   - يدعم React 19 (peerDependencies تسمح بـ^19) — لا Fork/Patch لازم.
 *   - localizer مبني على date-fns (مثبَّت بالمشروع أصلًا v4) — بدون
 *     Moment.js (Legacy) ولا Dependency ثقيلة إضافية.
 *   - مرونة تنسيق كاملة عبر eventPropGetter + components (نبني Toolbar
 *     وEvent مخصَّصين بالكامل من مكوّنات نظام التصميم — لا نعتمد شكلها
 *     الافتراضي إطلاقًا، فقط منطق التقويم/التنقّل/العروض).
 *   - مجاني تمامًا (MIT) ومناسب لمشروع مؤسسي بدون تكلفة ترخيص.
 *
 * لا تأثير على الباك-إند إطلاقًا — تُستهلك بيانات useMeetings() نفسها
 * المستخدمة أصلًا بالعرض الزمني، بدون أي API جديد.
 */

const locales = { 'ar-SA': arSA }

const localizer = dateFnsLocalizer({
  format,
  parse,
  startOfWeek: () => startOfWeek(new Date(), { weekStartsOn: 0 }),
  getDay,
  locales,
})

/** تحديث 2026-09-05 (ملاحظة لاما: "التقويم كله أبيض، اضف عليه ألوان يصير حياة") —
 * bg مبني على color-mix (لون الحالة الأساسي ممزوج بنسبة أعلى مع لون سطح
 * البطاقة) بدل توكِن status-*-bg الفاتح جدًا أصلًا — يعطي خلفية أحداث أوضح
 * وأكثر حيوية بكلا الوضعين (فاتح/داكن) دون كسر التباين، لأن النص يبقى
 * بلون الحالة (text) القوي نفسه فوق مزيج خفيف منه. */
/**
 * تحديث 2026-09-05 (ملاحظة لاما: مربعات الاجتماعات بالتقويم لونها "بعد"
 * خافت مقارنة بالبطاقات الأربع فوق): رفعنا نسبة color-mix من 14-16٪ إلى
 * 30٪ لخلفية أوضح وأقرب لحيوية بطاقات الإحصاء. آمن بكلا الوضعين لأن المزج
 * مع var(--bg-surface) (لون سطح الوضع الحالي نفسه، لا أبيض ثابت) يصحّح
 * اتجاه التباين تلقائيًا — وألوان الحالة (status-*-main) مصمَّمة أصلًا
 * كأزواج نص/خلفية آمنة (بعكس ألوان العلامة brand-* التي قيمتها الحرفية
 * ثابتة بالوضعين ولا تصلح كنص على خلفية داكنة — راجعي إصلاح rbc-header
 * بـmeeting-calendar.css لنفس السبب).
 */
const STATUS_COLOR: Record<MeetingStatus, { bg: string; border: string; text: string }> = {
  upcoming: {
    bg: 'color-mix(in srgb, var(--status-info-main) 30%, var(--bg-surface))',
    border: 'var(--status-info-main)',
    text: 'var(--status-info-main)',
  },
  ongoing: {
    bg: 'color-mix(in srgb, var(--status-success-main) 30%, var(--bg-surface))',
    border: 'var(--status-success-main)',
    text: 'var(--status-success-main)',
  },
  finished: {
    bg: 'color-mix(in srgb, var(--status-neutral-main) 26%, var(--bg-surface))',
    border: 'var(--status-neutral-main)',
    text: 'var(--status-neutral-main)',
  },
  recorded: {
    bg: 'color-mix(in srgb, var(--status-warning-main) 30%, var(--bg-surface))',
    border: 'var(--status-warning-main)',
    text: 'var(--status-warning-main)',
  },
}

/**
 * تحديث 2026-09-05 (٣) (ملاحظة لاما: "لون المربع كامل وقت الاجتماع مو بس
 * تحت الكلام" — تقصد خلية اليوم كاملة بعرض الشهر، لا شارة الحدث الصغيرة
 * فقط): نلوّن خلفية خلية اليوم كاملة عبر dayPropGetter لأي يوم فيه اجتماع
 * واحد أو أكثر، بنفس لون حالة الاجتماع لكن بمزيج أخف (تحته الشارة الملوّنة
 * الأقوى من STATUS_COLOR.bg أعلاه تبقى مميَّزة فوقه، بنفس الأسلوب المرئي
 * اللي كانت عليه خلية "اليوم" (rbc-today) أصلًا بـmeeting-calendar.css).
 */
const STATUS_DAY_BG: Record<MeetingStatus, string> = {
  upcoming: 'color-mix(in srgb, var(--status-info-main) 16%, var(--bg-surface))',
  ongoing: 'color-mix(in srgb, var(--status-success-main) 16%, var(--bg-surface))',
  finished: 'color-mix(in srgb, var(--status-neutral-main) 14%, var(--bg-surface))',
  recorded: 'color-mix(in srgb, var(--status-warning-main) 16%, var(--bg-surface))',
}

/** أولوية اختيار لون الخلية عند وجود أكثر من اجتماع بنفس اليوم بحالات
 *  مختلفة — الأولوية للأكثر أهمية/إلحاحًا (رقم أصغر = أولوية أعلى). */
const STATUS_PRIORITY: Record<MeetingStatus, number> = {
  ongoing: 0,
  upcoming: 1,
  recorded: 2,
  finished: 3,
}

interface CalendarEvent {
  id: string
  title: string
  start: Date
  end: Date
  meeting: Meeting
}

const MESSAGES = {
  date: 'التاريخ',
  time: 'الوقت',
  event: 'اجتماع',
  allDay: 'طوال اليوم',
  week: 'أسبوع',
  work_week: 'أيام العمل',
  day: 'يوم',
  month: 'شهر',
  previous: 'السابق',
  next: 'التالي',
  yesterday: 'أمس',
  tomorrow: 'غدًا',
  today: 'اليوم',
  agenda: 'جدول',
  noEventsInRange: 'لا توجد اجتماعات ضمن هذا النطاق الزمني',
  showMore: (count: number) => `+${count} أخرى`,
}

const VIEW_OPTIONS: { key: View; label: string }[] = [
  { key: Views.MONTH, label: 'شهر' },
  { key: Views.WEEK, label: 'أسبوع' },
  { key: Views.DAY, label: 'يوم' },
  { key: Views.AGENDA, label: 'جدول' },
]

function CalendarToolbar({
  label,
  view,
  onNavigate,
  onView,
}: {
  label: string
  view: View
  onNavigate: (action: NavigateAction) => void
  onView: (view: View) => void
}) {
  return (
    <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-2">
        <button
          onClick={() => onNavigate('PREV')}
          className="rounded-sm p-1.5 text-text-secondary transition-colors hover:bg-bg-elevated hover:text-text-primary"
          aria-label="السابق"
        >
          <ChevronRight size={16} />
        </button>
        <button
          onClick={() => onNavigate('TODAY')}
          className="rounded-sm border border-border-default px-2.5 py-1 text-xs font-semibold text-text-secondary transition-colors hover:bg-bg-elevated hover:text-text-primary"
        >
          اليوم
        </button>
        <button
          onClick={() => onNavigate('NEXT')}
          className="rounded-sm p-1.5 text-text-secondary transition-colors hover:bg-bg-elevated hover:text-text-primary"
          aria-label="التالي"
        >
          <ChevronLeft size={16} />
        </button>
        <span className="mr-1 text-sm font-bold text-text-primary">{label}</span>
      </div>

      <div className="flex w-fit items-center gap-0.5 rounded-sm border border-border-default bg-bg-app p-0.5">
        {VIEW_OPTIONS.map((opt) => (
          <button
            key={opt.key}
            onClick={() => onView(opt.key)}
            className={cn(
              'rounded-xs px-2.5 py-1 text-xs font-semibold transition-colors',
              view === opt.key
                ? 'bg-brand-primary text-white shadow-sm'
                : 'text-text-secondary hover:text-text-primary',
            )}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  )
}

function CalendarEventContent({ event }: { event: CalendarEvent }) {
  const tone = STATUS_COLOR[event.meeting.status]
  return (
    <span className="flex items-center gap-1 truncate">
      <span
        className="h-1.5 w-1.5 shrink-0 rounded-full"
        style={{ backgroundColor: tone.text }}
      />
      <span className="truncate">{event.title}</span>
    </span>
  )
}

export function MeetingCalendarView({
  meetings,
  onSelectMeeting,
}: {
  meetings: Meeting[]
  onSelectMeeting: (meeting: Meeting) => void
}) {
  const [view, setView] = useState<View>(Views.MONTH)
  const [date, setDate] = useState(new Date())

  const events = useMemo<CalendarEvent[]>(
    () =>
      meetings.map((m) => {
        const start = new Date(m.scheduled_at)
        const end = m.scheduled_end_at
          ? new Date(m.scheduled_end_at)
          : new Date(start.getTime() + 30 * 60 * 1000)
        return { id: m.meeting_id, title: m.title, start, end, meeting: m }
      }),
    [meetings],
  )

  /** خريطة يوم -> حالة الاجتماع الأولى بالأولوية (لتلوين خلية اليوم كاملة
   *  بـdayPropGetter أدناه). مفتاحها yyyy-MM-dd محلي (لا UTC) لتطابق تمامًا
   *  الخلية اللي يرسمها react-big-calendar لنفس اليوم. */
  const dayColorMap = useMemo(() => {
    const map = new Map<string, MeetingStatus>()
    for (const event of events) {
      const key = format(event.start, 'yyyy-MM-dd')
      const existing = map.get(key)
      if (!existing || STATUS_PRIORITY[event.meeting.status] < STATUS_PRIORITY[existing]) {
        map.set(key, event.meeting.status)
      }
    }
    return map
  }, [events])

  const dayPropGetter = useCallback<DayPropGetter>(
    (date) => {
      const status = dayColorMap.get(format(date, 'yyyy-MM-dd'))
      if (!status) return {}
      return { style: { backgroundColor: STATUS_DAY_BG[status] } }
    },
    [dayColorMap],
  )

  const eventPropGetter = useCallback<EventPropGetter<CalendarEvent>>((event) => {
    const tone = STATUS_COLOR[event.meeting.status]
    return {
      style: {
        backgroundColor: tone.bg,
        borderColor: tone.border,
        color: tone.text,
      },
    }
  }, [])

  return (
    <div className="wm-calendar rounded-md border border-border-default bg-bg-surface p-3">
      <RBCalendar
        localizer={localizer}
        culture="ar-SA"
        rtl
        events={events}
        date={date}
        onNavigate={setDate}
        view={view}
        onView={setView}
        views={[Views.MONTH, Views.WEEK, Views.DAY, Views.AGENDA]}
        startAccessor="start"
        endAccessor="end"
        popup
        messages={MESSAGES}
        style={{ height: 640 }}
        onSelectEvent={(event) => onSelectMeeting(event.meeting)}
        eventPropGetter={eventPropGetter}
        dayPropGetter={dayPropGetter}
        components={{
          toolbar: CalendarToolbar,
          event: CalendarEventContent,
          agenda: {
            event: CalendarEventContent,
          },
        }}
      />

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-border-default pt-2.5 text-xs text-text-secondary">
        <span className="flex items-center gap-1.5 font-semibold text-text-muted">
          <CalendarDays size={13} /> دلالة الألوان:
        </span>
        {(
          [
            ['upcoming', 'قادم'],
            ['ongoing', 'جارف'],
            ['finished', 'منتهٍ'],
          ] as [MeetingStatus, string][]
        ).map(([status, label]) => (
          <span key={status} className="flex items-center gap-1.5">
            <span
              className="h-2 w-2 rounded-full"
              style={{ backgroundColor: STATUS_COLOR[status].text }}
            />
            {label}
          </span>
        ))}
        <span className="mr-auto flex items-center gap-1.5 text-text-muted">
          <ListTodo size={12} /> اضغط أي اجتماع لعرض تفاصيله
        </span>
      </div>
    </div>
  )
}
