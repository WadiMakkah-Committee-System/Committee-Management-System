import { UserCheck } from 'lucide-react'
import { Card } from '@/components/ui/Card'
import { Avatar } from '@/components/ui/Avatar'
import { useMeetingAttendance } from '@/hooks/useMeetings'

const timeFormat = new Intl.DateTimeFormat('ar-SA', { hour: 'numeric', minute: '2-digit' })

/** مدة بالثواني ⇒ "1 س 05 د" أو "12 د" أو "أقل من دقيقة". */
function formatDuration(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60)
  if (minutes < 1) return 'أقل من دقيقة'
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return h > 0 ? `${h} س ${String(m).padStart(2, '0')} د` : `${m} د`
}

/**
 * جدول الحضور التلقائي (migration 0043 — قرار لاما 2026-11-03): لكل عضو دخل
 * الاجتماع من المنصة — أول دخول، آخر خروج (أو "داخل الآن")، إجمالي المدة،
 * وعدد مرات الدخول. يُسجَّل تلقائيًا من غرفة الاجتماع بدون أي إدخال يدوي.
 * ملاحظة: اللي دخل من تطبيق Teams مباشرة (مو من المنصة) ما يظهر هنا.
 */
export function MeetingAttendanceCard({ meetingId }: { meetingId: string }) {
  const { data: rows, isLoading } = useMeetingAttendance(meetingId)

  return (
    <Card id="attendance-section" className="scroll-mt-4 p-0">
      <div className="flex items-center justify-between border-b border-border-default px-4 py-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-text-primary">
          <UserCheck size={15} />
          الحضور
        </h2>
        {rows && rows.length > 0 && <span className="text-xs text-text-muted">{rows.length} حاضر</span>}
      </div>
      <div className="p-4">
        {isLoading ? (
          <p className="py-4 text-center text-xs text-text-muted">جارِ التحميل...</p>
        ) : !rows?.length ? (
          <p className="py-4 text-center text-xs text-text-muted">
            ما فيه حضور مسجّل بعد — يُسجَّل تلقائيًا لما يدخل الأعضاء الاجتماع من المنصة.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-start text-xs">
              <thead>
                <tr className="border-b border-border-default text-text-muted">
                  <th className="py-2 text-start font-medium">العضو</th>
                  <th className="py-2 text-start font-medium">أول دخول</th>
                  <th className="py-2 text-start font-medium">آخر خروج</th>
                  <th className="py-2 text-start font-medium">المدة</th>
                  <th className="py-2 text-start font-medium">مرات الدخول</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.user.user_id} className="border-b border-border-default/60 last:border-0">
                    <td className="py-2">
                      <span className="flex items-center gap-2 font-medium text-text-primary">
                        <Avatar firstName={r.user.first_name} lastName={r.user.last_name} size={22} />
                        {r.user.first_name} {r.user.last_name}
                      </span>
                    </td>
                    <td className="py-2 text-text-secondary">{timeFormat.format(new Date(r.first_joined_at))}</td>
                    <td className="py-2 text-text-secondary">
                      {r.last_left_at ? (
                        timeFormat.format(new Date(r.last_left_at))
                      ) : (
                        <span className="font-semibold text-status-success-main">داخل الآن</span>
                      )}
                    </td>
                    <td className="py-2 font-medium text-text-primary">{formatDuration(r.total_seconds)}</td>
                    <td className="py-2 text-text-secondary">{r.sessions}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Card>
  )
}
