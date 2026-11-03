import { Activity, DoorOpen, Paperclip, CalendarDays, Users, Vote } from 'lucide-react'
import { cn } from '@/lib/utils'

export type RoomPanelKey =
  | 'participants'
  | 'agenda'
  | 'decisions'
  | 'attachments'
  | 'chat'
  | 'activity'
  | 'lobby'

/** تبويبات اللوحة الديناميكية فقط (بلا "المحادثة" — تُفتَح من الشريط العام
 * الداكن MeetingRoomAppRail.tsx. لوحة "التسجيل + الذكاء الاصطناعي" أُزيلت
 * 2026-11-02: التسجيل صار داخل Microsoft Teams — تعديل لاما 2026-09-06
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

/** تبويب "الانتظار" (قرار لاما 2026-11-03) — يظهر فقط لمن يقدر يقبل المنتظرين
 * (داخل الاجتماع بحساب Microsoft)، أول التبويبات عشان ما يفوت. */
const LOBBY_TAB = { key: 'lobby' as const, label: 'الانتظار', icon: DoorOpen }

/** صف تبويبات اللوحة الديناميكية أعلى غرفة الاجتماع — تبويب واحد فقط نشط بأي وقت.
 * showLobby/lobbyCount: تبويب قاعة الانتظار ورقم المنتظرين عليه. */
export function MeetingRoomSidebar({
  active,
  onSelect,
  raisedHandCount,
  showLobby = false,
  lobbyCount = 0,
}: {
  active: RoomPanelKey
  onSelect: (key: RoomPanelKey) => void
  raisedHandCount: number
  showLobby?: boolean
  lobbyCount?: number
}) {
  const tabs = showLobby ? [LOBBY_TAB, ...TAB_ITEMS] : TAB_ITEMS
  return (
    <nav className="flex shrink-0 items-center justify-between gap-1 border-b border-border-default bg-bg-surface px-2 py-2">
      {tabs.map(({ key, label, icon: Icon }) => {
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
              {key === 'lobby' && lobbyCount > 0 && (
                <span className="absolute -left-2 -top-1.5 flex h-3.5 min-w-3.5 animate-pulse items-center justify-center rounded-full bg-danger px-0.5 text-[8px] font-bold text-white">
                  {lobbyCount}
                </span>
              )}
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
