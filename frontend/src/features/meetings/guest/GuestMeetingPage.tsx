import { useState } from 'react'
import { Navigate } from 'react-router-dom'
import { CheckCircle2 } from 'lucide-react'
import { logout as logoutRequest } from '@/api/auth'
import { useAuthStore } from '@/store/authStore'
import { MeetingRoom } from '../MeetingRoom'
import wadiMakkahMark from '@/assets/wadi-makkah-mark.png'

/**
 * غرفة اجتماع الضيف (migration 0047): نفس MeetingRoom العادية، بدون إطار
 * المنصة (القائمة الجانبية/الشريط العلوي). عند المغادرة أو انتهاء الاجتماع
 * تُنهى جلسة الضيف وتظهر رسالة شكر — الضيف لا يملك أي صفحة أخرى بالمنصة.
 */
export function GuestMeetingPage() {
  const user = useAuthStore((s) => s.user)
  const accessToken = useAuthStore((s) => s.accessToken)
  const logout = useAuthStore((s) => s.logout)
  const [left, setLeft] = useState(false)

  if (left || (!accessToken && !user)) {
    return (
      <div className="flex min-h-svh flex-col items-center justify-center gap-4 bg-bg-app px-4 text-center">
        <img src={wadiMakkahMark} alt="شعار وادي مكة" className="h-12 w-auto" />
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-success-bg text-success">
          <CheckCircle2 size={26} />
        </div>
        <p className="text-lg font-bold text-text-primary">شكرًا لحضورك</p>
        <p className="max-w-sm text-sm text-text-secondary">
          غادرت الاجتماع. للانضمام مرة أخرى افتح رابط الدعوة نفسه.
        </p>
      </div>
    )
  }

  if (!user?.is_guest || !user.guest_meeting_id) return <Navigate to="/login" replace />

  return (
    <MeetingRoom
      meetingId={user.guest_meeting_id}
      meetingTitle=""
      onClose={() => {
        setLeft(true)
        // إلغاء الجلسة بالباك-إند أولًا (التوكن المحفوظ لا يعود صالحًا حتى لو
        // بقي الاجتماع قائمًا)، ثم مسح الحالة المحلية مهما كانت النتيجة.
        void logoutRequest()
          .catch(() => undefined)
          .finally(() => logout())
      }}
    />
  )
}
