import { Home, LogOut, MessageSquare, Video } from 'lucide-react'
import { cn } from '@/lib/utils'
import wadiMakkahMark from '@/assets/wadi-makkah-mark.png'

/**
 * الشريط الجانبي "العام" الداكن لغرفة الاجتماع — تعديل لاما 2026-09-06
 * لمطابقة واجهة الاجتماع المرجعية بالضبط: شعار الشركة (نفس ملف
 * wadi-makkah-mark.png المستخدم بـSidebar.tsx الرئيسي — "بألوان الشركة
 * وشعارها" كما طلبت) + تنقّل عام أعلى مستوى، منفصل تمامًا عن شريط
 * تبويبات لوحة الاجتماع الديناميكية (مشاركون/أجندة/قرارات/نشاط/مرفقات،
 * راجعي MeetingRoomSidebar.tsx).
 *
 * تعديل لاما 2026-09-06 (طلب صريح: "قسم الاشعارات ما يطلع بعدين موهو
 * نفسه النشاط؟" و"الاعدادات لما اضغطها ما تنضغط"): حُذف زرّا
 * "الإشعارات" و"الإعدادات" نهائيًا من هذا الشريط — "الإشعارات" غير
 * مبنية بأي مكان بالتطبيق أصلًا (نفس عنصر "قريبًا" بالـSidebar.tsx
 * الرئيسي)، ووجودها هنا بشارة نقطة حمراء وهمية كان مضلّلًا (توحي بإشعار
 * فعلي رغم عدم وجود شيء ينفتح عند الضغط)؛ و"النشاط" أصلًا موجود كتبويب
 * حقيقي بلوحة الاجتماع (MeetingRoomSidebar.tsx) ويغطي نفس الحاجة داخل
 * هذا الاجتماع تحديدًا. و"الإعدادات" لا يقابلها أي صفحة إطلاقًا بالتطبيق
 * (ولا حتى كعنصر "قريبًا" بالـSidebar الرئيسي) فلا مبرر لوجودها معطّلة
 * هنا. "الرئيسية" و"خروج" كلاهما يقودان فعليًا لنفس تدفق "مغادرة
 * الاجتماع" الحقيقي (تأكيد ثم إغلاق) — بلا لوحة تحكم رئيسية مبنية بعد
 * بهذا التطبيق أصلًا فلا معنى لتنقّل وهمي لصفحة غير موجودة.
 */
export function MeetingRoomAppRail({
  onExitClick,
  onChatClick,
  chatActive,
  hasUnreadChat,
}: {
  onExitClick: () => void
  onChatClick: () => void
  chatActive: boolean
  hasUnreadChat: boolean
}) {
  return (
    <nav className="flex w-[72px] shrink-0 flex-col items-center gap-1 bg-sidebar-bg py-4">
      <img src={wadiMakkahMark} alt="شعار وادي مكة" className="mb-3 h-8 w-auto shrink-0" />

      <RailButton icon={Home} label="الرئيسية" onClick={onExitClick} />
      <RailButton icon={Video} label="غرفة الاجتماع" active />
      <RailButton icon={MessageSquare} label="المحادثة" active={chatActive} badge={hasUnreadChat} onClick={onChatClick} />

      <div className="flex-1" />

      <RailButton icon={LogOut} label="خروج" onClick={onExitClick} />
    </nav>
  )
}

function RailButton({
  icon: Icon,
  label,
  active,
  badge,
  onClick,
}: {
  icon: typeof Home
  label: string
  active?: boolean
  badge?: boolean
  onClick?: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      className={cn(
        'flex w-[60px] flex-col items-center gap-1 rounded-md px-1.5 py-2 transition-colors',
        active ? 'bg-brand-primary text-white' : 'text-white/60 hover:bg-white/10 hover:text-white',
      )}
    >
      <span className="relative">
        <Icon size={19} />
        {badge && (
          <span className="absolute -left-1 -top-1 h-2 w-2 rounded-full border-2 border-sidebar-bg bg-danger" />
        )}
      </span>
      <span className="text-center text-[9.5px] leading-tight">{label}</span>
    </button>
  )
}
