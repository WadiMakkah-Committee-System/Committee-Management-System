import { useEffect, useRef } from 'react'
import { attendanceHeartbeat, leaveAttendance, startAttendance } from '@/api/meetings'
import { useAuthStore } from '@/store/authStore'

const HEARTBEAT_MS = 60_000

/**
 * الحضور التلقائي (migration 0043 — قرار لاما 2026-11-03): يسجّل جلسة حضور
 * لحظة ما يكون العضو داخل الاجتماع فعليًا (connected=true — بعد القبول من
 * الانتظار)، ونبضة كل دقيقة، وخروج لما يطلع أو تنقفل الصفحة.
 *
 * المدخلات: meetingId، connected (من useTeamsEmbeddedCall: phase === 'connected').
 * التأثيرات الجانبية: طلبات للباك-إند فقط — فشلها صامت (الحضور ما يعطّل الاجتماع).
 */
export function useMeetingAttendance(meetingId: string, connected: boolean) {
  const sessionRef = useRef<string | null>(null)

  useEffect(() => {
    if (!connected) return
    let cancelled = false

    const begin = async () => {
      try {
        const { attendance_id } = await startAttendance(meetingId)
        if (cancelled) {
          leaveAttendance(meetingId, attendance_id, useAuthStore.getState().accessToken)
          return
        }
        sessionRef.current = attendance_id
      } catch {
        /* الحضور تحسين — فشله ما يوقف الاجتماع */
      }
    }

    const leave = () => {
      const id = sessionRef.current
      sessionRef.current = null
      if (id) leaveAttendance(meetingId, id, useAuthStore.getState().accessToken)
    }

    void begin()
    const timer = setInterval(async () => {
      const id = sessionRef.current
      if (!id) return void begin()
      try {
        const { active } = await attendanceHeartbeat(meetingId, id)
        if (!active) {
          sessionRef.current = null
          await begin()
        }
      } catch {
        /* نبضة فاشلة (نت ضعيف) — نحاول بالنبضة الجاية */
      }
    }, HEARTBEAT_MS)
    window.addEventListener('pagehide', leave)

    return () => {
      cancelled = true
      clearInterval(timer)
      window.removeEventListener('pagehide', leave)
      leave()
    }
  }, [meetingId, connected])
}
