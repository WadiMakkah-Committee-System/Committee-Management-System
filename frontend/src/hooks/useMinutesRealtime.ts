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
export function useMinutesRealtime(meetingId: string | undefined) {
  const [collaborators, setCollaborators] = useState<Record<string, MinutesCollaborator>>({})
  const [remoteSections, setRemoteSections] = useState<{ sections: MinutesSection[]; at: number } | null>(
    null,
  )
  const socketRef = useRef<Socket | null>(null)

  useEffect(() => {
    if (!meetingId) return

    const socket = createMeetingSocket(meetingId)
    socketRef.current = socket

    socket.on('disconnect', (reason) => {
      console.info(`[useMinutesRealtime] Socket.IO disconnected — reason=${reason}`)
    })

    socket.on(
      'minutes.editing',
      (payload: { user_id: string; full_name: string; section_id: string }) => {
        setCollaborators((prev) => ({
          ...prev,
          [payload.user_id]: {
            userId: payload.user_id,
            fullName: payload.full_name,
            sectionId: payload.section_id,
            at: Date.now(),
          },
        }))
      },
    )

    socket.on('minutes.updated', (payload: { sections: MinutesSection[] }) => {
      setRemoteSections({ sections: payload.sections, at: Date.now() })
    })

    socket.on('presence.left', (payload: { user_id: string }) => {
      setCollaborators((prev) => {
        const next = { ...prev }
        delete next[payload.user_id]
        return next
      })
    })

    return () => {
      socket.disconnect()
      socketRef.current = null
    }
  }, [meetingId])

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
