import { useMutation, useQuery } from '@tanstack/react-query'
import * as api from '@/api/committeeAttachments'

/**
 * تصنيف "مرفقات اللجنة" — استعلام لكل مستوى، مفعَّل فقط لما مستواه مفتوح
 * فعليًا (enabled)، فلا يُرسَل أي طلب لمستوى لم يطلبه المستخدم.
 * staleTime دقيقة: الرجوع والتقدم بين المستويات لا يعيد الطلب نفسه.
 */
const STALE = 60_000

export const committeeAttachmentsKeys = {
  committees: ['committee-attachments', 'committees'] as const,
  meetings: (committeeId: string) => ['committee-attachments', 'meetings', committeeId] as const,
  bundle: (meetingId: string) => ['committee-attachments', 'bundle', meetingId] as const,
}

export function useAttachmentCommittees(enabled: boolean) {
  return useQuery({
    queryKey: committeeAttachmentsKeys.committees,
    queryFn: api.fetchAttachmentCommittees,
    enabled,
    staleTime: STALE,
  })
}

export function useAttachmentCommitteeMeetings(committeeId: string | null) {
  return useQuery({
    queryKey: committeeAttachmentsKeys.meetings(committeeId ?? ''),
    queryFn: () => api.fetchAttachmentCommitteeMeetings(committeeId!),
    enabled: !!committeeId,
    staleTime: STALE,
  })
}

export function useAttachmentMeetingBundle(meetingId: string | null) {
  return useQuery({
    queryKey: committeeAttachmentsKeys.bundle(meetingId ?? ''),
    queryFn: () => api.fetchAttachmentMeetingBundle(meetingId!),
    enabled: !!meetingId,
    staleTime: STALE,
  })
}

/** تنزيل المحضر PDF (نفس آلية تنزيل مرفقات الاجتماع — Blob ثم رابط مؤقت). */
export function useDownloadMinutesPdf() {
  return useMutation({
    mutationFn: async (meetingId: string) => {
      const { blob, fileName } = await api.fetchMinutesPdfBlob(meetingId)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = fileName
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    },
  })
}
