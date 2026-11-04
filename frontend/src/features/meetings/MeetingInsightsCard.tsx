import { BarChart3, Clock, Users } from 'lucide-react'
import { Card } from '@/components/ui/Card'
import { useMeetingInsights } from '@/hooks/useMeetings'
import { cn } from '@/lib/utils'

/** مدة بالثواني ⇒ "1 س 05 د" / "12 د" / "أقل من دقيقة". */
function duration(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60)
  if (minutes < 1) return 'أقل من دقيقة'
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return h > 0 ? `${h} س ${String(m).padStart(2, '0')} د` : `${m} د`
}

/**
 * إحصائيات الاجتماع (قرار لاما 2026-11-03، البند 15): المدة، نسبة الحضور،
 * ووقت كل بند مقابل مؤقته. (2026-11-04: شِلنا "مدة كلام كل عضو" بطلب لاما — مو مهمة.)
 * مصادرها: الحضور التلقائي + الترجمة النصية + فترات مناقشة البنود.
 */
export function MeetingInsightsCard({ meetingId }: { meetingId: string }) {
  const { data, isLoading } = useMeetingInsights(meetingId)
  if (isLoading || !data) return null
  const nothing = data.duration_seconds === null && data.attended_members === 0 && data.agenda.length === 0
  if (nothing) return null

  const rate = data.total_members ? Math.round((data.attended_members / data.total_members) * 100) : 0

  return (
    <Card id="insights-section" className="scroll-mt-4 p-0">
      <div className="flex items-center gap-2 border-b border-border-default px-4 py-3">
        <BarChart3 size={15} />
        <h2 className="text-sm font-semibold text-text-primary">إحصائيات الاجتماع</h2>
      </div>
      <div className="flex flex-col gap-5 p-4">
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-md bg-bg-elevated p-3">
            <p className="flex items-center gap-1.5 text-[11px] text-text-muted">
              <Clock size={12} /> مدة الاجتماع
            </p>
            <p className="mt-1 text-lg font-bold text-text-primary">
              {data.duration_seconds !== null ? duration(data.duration_seconds) : '—'}
            </p>
          </div>
          <div className="rounded-md bg-bg-elevated p-3">
            <p className="flex items-center gap-1.5 text-[11px] text-text-muted">
              <Users size={12} /> نسبة الحضور
            </p>
            <p className="mt-1 text-lg font-bold text-text-primary">
              {rate}% <span className="text-xs font-normal text-text-muted">({data.attended_members} من {data.total_members})</span>
            </p>
          </div>
        </div>

        {data.agenda.length > 0 && (
          <div>
            <p className="mb-2 text-xs font-semibold text-text-secondary">وقت البنود</p>
            <ul className="flex flex-col gap-1.5">
              {data.agenda.map((a) => {
                const over = a.planned_seconds !== null && a.actual_seconds > a.planned_seconds
                return (
                  <li
                    key={a.agenda_item_id}
                    className="flex items-center justify-between gap-2 rounded-sm border border-border-default px-3 py-2 text-xs"
                  >
                    <span className="truncate text-text-primary">{a.title}</span>
                    <span className={cn('shrink-0', over ? 'font-semibold text-danger' : 'text-text-secondary')}>
                      {duration(a.actual_seconds)}
                      {a.planned_seconds !== null && ` / ${duration(a.planned_seconds)}`}
                    </span>
                  </li>
                )
              })}
            </ul>
          </div>
        )}
      </div>
    </Card>
  )
}
