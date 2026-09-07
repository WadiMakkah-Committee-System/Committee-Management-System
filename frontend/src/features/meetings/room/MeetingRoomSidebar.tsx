import { Activity, Paperclip, CalendarDays, Users, Vote } from 'lucide-react'
import { cn } from '@/lib/utils'

export type RoomPanelKey =
  | 'participants'
  | 'agenda'
  | 'decisions'
  | 'attachments'
  | 'chat'
  | 'activity'
  | 'ai'

/** تبويبات اللوحة الديناميكية فقط (بلا "المحادثة"/"الذكاء الاصطناعي" —
 * هاتان تُفتَحان الآن من مكان آخر: المحادثة من الشريط العام الداكن
 * MeetingRoomAppRail.tsx، ولوحة التسجيل+الذكاء الاصطناعي من زر "المزيد"
 * بشريط التحكم السفلي MeetingControls.tsx — تعديل لاما 2026-09-06
 * لمطابقة الواجهة المرجعية بالضبط: صف تبويبات أفقي صغير أعلى اللوحة
 * البيضاء، وليس شريطًا جانبيًا رأسيًا كما كان). ترتيب اليمين→اليسار
 * (RTL): المشاركون، النشاط، القرارات، الأجندة، المرفقات — مطابق لترتيب
 * المرجع بالضبط. */
const TAB_ITEMS: { key: RoomPanelKey; label: string; icon: typeof Users }[] = [
  { key: 'participants', label: 'المشاركون', icon: Users },
  { key: 'activity', label: 'النشاط', icon: Activity },
  { key: 'decisions', label: 'القرارات', icon: Vote },
  { key: 'agenda', label: 'الأجندة', icon: CalendarDays },
  { key: 'attachments', label: 'المرفقات', icon: Paperclip },
]

/** صف تبويبات اللوحة الديناميكية أعلى غرفة الاجتماع — تبويب واحد فقط نشط بأي وقت. */
export function MeetingRoomSidebar({
  active,
  onSelect,
  raisedHandCount,
}: {
  active: RoomPanelKey
  onSelect: (key: RoomPanelKey) => void
  raisedHandCount: number
}) {
  return (
    <nav className="flex shrink-0 items-center justify-between gap-1 border-b border-border-default bg-bg-surface px-2 py-2">
      {TAB_ITEMS.map(({ key, label, icon: Icon }) => {
        const isActive = active === key
        return (
          <button
            key={key}
            type="button"
            onClick={() => onSelect(key)}
            className={cn(
              'relative flex flex-1 flex-col items-center gap-1 rounded-md px-1 py-1.5 transition-colors',
              isActive
                ? 'bg-brand-primary text-white'
                : 'text-text-secondary hover:bg-bg-elevated hover:text-text-primary',
            )}
          >
            <span className="relative">
              <Icon size={17} />
              {key === 'participants' && raisedHandCount > 0 && (
                <span className="absolute -left-2 -top-1.5 flex h-3.5 min-w-3.5 items-center justify-center rounded-full bg-warning px-0.5 text-[8px] font-bold text-white">
                  {raisedHandCount}
                </span>
              )}
            </span>
            <span className="text-[9.5px] font-medium leading-tight">{label}</span>
          </button>
        )
      })}
    </nav>
  )
}
