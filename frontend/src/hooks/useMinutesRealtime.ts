import { useCallback, useEffect, useRef, useState } from 'react'
import { createMeetingSocket } from './useMeetingRealtime'
import type { Socket } from 'socket.io-client'
import type { MinutesSection } from '@/types'

export interface MinutesCollaborator {
  userId: string
  fullName: string
  sectionId: string | null
  at: number
}

/**
 * تحرير تعاوني لحظي للمحضر (FR-MIN-005) — Socket.IO (قرار لاما
 * 2026-09-10، بدّل WebSocket الخام — راجعي رأس useMeetingRealtime.ts
 * وapp/core/socketio_server.py بالباك-إند للتصميم الكامل). يعيد استخدام
 * نفس غرفة اجتماع Socket.IO (meeting:{meetingId} بالباك-إند) عبر
 * createMeetingSocket المُصدَّرة من useMeetingRealtime.ts، لكن باتصال
 * منفصل مخصَّص لصفحة المحضر (بدل ربطه بذاك الهوك المخصَّص لغرفة الاجتماع
 * الحيّة نفسها بكل حالتها — فصل بسيط بدل تحميله مسؤولية لا يحتاجها هنا،
 * نفس القرار القديم بالضبط). يستمع فقط minutes.editing/minutes.updated/
 * presence.left، يتجاهل بقية الأحداث.
 */
export function useMinutesRealtime(meetingId: string | undefined, sharedSocket?: Socket | null) {
  const [collaborators, setCollaborators] = useState<Record<string, MinutesCollaborator>>({})
  const [remoteSections, setRemoteSections] = useState<{ sections: MinutesSection[]; at: number } | null>(
    null,
  )
  const socketRef = useRef<Socket | null>(null)
  // sharedSocket (لوحة المحضر داخل غرفة الاجتماع — 2026-11-09): undefined ⇒
  // اتصال خاص بهذا الهوك (صفحة المحضر، السلوك القديم بلا تغيير). null/Socket ⇒
  // استخدام اتصال الغرفة نفسه (useMeetingRealtime().socket) بدل اتصال ثانٍ —
  // فتح/قفل اتصال ثانٍ يبث presence.joined/left للكل (راجعي
  // socketio_server.py::disconnect). null = اتصال الغرفة لم يُنشأ بعد.
  const usesShared = sharedSocket !== undefined

  useEffect(() => {
    if (!meetingId) return
    if (usesShared && !sharedSocket) return

    const socket = usesShared && sharedSocket ? sharedSocket : createMeetingSocket(meetingId)
    socketRef.current = socket

    const onDisconnect = (reason: string) => {
      console.info(`[useMinutesRealtime] Socket.IO disconnected — reason=${reason}`)
    }
    const onEditing = (payload: { user_id: string; full_name: string; section_id: string }) => {
      setCollaborators((prev) => ({
        ...prev,
        [payload.user_id]: {
          userId: payload.user_id,
          fullName: payload.full_name,
          sectionId: payload.section_id,
          at: Date.now(),
        },
      }))
    }
    const onUpdated = (payload: { sections: MinutesSection[] }) => {
      setRemoteSections({ sections: payload.sections, at: Date.now() })
    }
    const onLeft = (payload: { user_id: string }) => {
      setCollaborators((prev) => {
        const next = { ...prev }
        delete next[payload.user_id]
        return next
      })
    }

    socket.on('disconnect', onDisconnect)
    socket.on('minutes.editing', onEditing)
    socket.on('minutes.updated', onUpdated)
    socket.on('presence.left', onLeft)

    return () => {
      socket.off('disconnect', onDisconnect)
      socket.off('minutes.editing', onEditing)
      socket.off('minutes.updated', onUpdated)
      socket.off('presence.left', onLeft)
      // الاتصال المشترك ملك غرفة الاجتماع — لا نقطعه من هنا.
      if (!usesShared) socket.disconnect()
      socketRef.current = null
    }
  }, [meetingId, usesShared, sharedSocket])

  const send = useCallback((event: string, payload?: Record<string, unknown>) => {
    socketRef.current?.emit(event, payload)
  }, [])

  const announceEditing = useCallback(
    (sectionId: string) => send('minutes.editing', { section_id: sectionId }),
    [send],
  )
  const broadcastUpdate = useCallback(
    (sections: MinutesSection[]) => send('minutes.updated', { sections }),
    [send],
  )

  return {
    collaborators: Object.values(collaborators),
    remoteSections,
    announceEditing,
    broadcastUpdate,
  }
}
