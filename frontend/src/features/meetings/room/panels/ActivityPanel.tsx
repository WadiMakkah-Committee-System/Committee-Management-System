import { Activity } from 'lucide-react'
import { EmptyState } from '@/components/ui/EmptyState'
import { formatTime } from '@/lib/utils'
import type { LiveActivityEvent } from '@/hooks/useMeetingRealtime'

/**
 * سجل نشاط حي — كل أحداثه عابرة (تصل عبر WebSocket ولا تُخزَّن بقاعدة
 * البيانات، راجعي hooks/useMeetingRealtime.ts)، فتبدأ فارغة عند كل دخول
 * جديد للغرفة (بخلاف تاريخ المحادثة اللي يُحمَّل من الخادم). هذا سلوك
 * مقصود لا عيب — "نشاط الجلسة الحالية" وليس سجل تدقيقي دائم.
 */
export function ActivityPanel({ events }: { events: LiveActivityEvent[] }) {
  if (events.length === 0) {
    return (
      <div className="p-4">
        <EmptyState
          icon={<Activity size={22} />}
          title="لا يوجد نشاط بعد"
          description="ستظهر هنا أحداث الاجتماع الحية أول بأول (انضمام، رفع يد، بدء مناقشة بند...)."
        />
      </div>
    )
  }

  return (
    <ul className="flex flex-col gap-3 p-3">
      {events.map((event) => (
        <li key={event.id} className="flex items-start gap-2.5">
          <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-brand-primary" />
          <div className="min-w-0">
            <p className="text-[12px] leading-relaxed text-text-primary">{event.text}</p>
            <p className="text-[10px] text-text-muted">{formatTime(event.at)}</p>
          </div>
        </li>
      ))}
    </ul>
  )
}
