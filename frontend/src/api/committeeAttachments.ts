import { apiClient } from '@/lib/apiClient'
import { fileNameFromDisposition } from '@/lib/utils'
import type {
  CommitteeAttachmentsCommittee,
  CommitteeAttachmentsMeeting,
  CommitteeAttachmentsMeetingBundle,
} from '@/types'

/**
 * تصنيف "مرفقات اللجنة" بصفحة الوثائق (2026-11-01). كل دالة مستوى واحد،
 * تُستدعى فقط لما المستخدم يفتح ذاك المستوى (لا جلب مسبق لأي مستوى تالٍ).
 */

/** المستوى الأول: لجاني (الاسم + منتهية/جارية فقط). */
export async function fetchAttachmentCommittees(): Promise<CommitteeAttachmentsCommittee[]> {
  const { data } = await apiClient.get<CommitteeAttachmentsCommittee[]>('/documents/committee-attachments/committees')
  return data
}

/** بعد اختيار "مرفقات الاجتماعات": أسماء اجتماعات اللجنة فقط. */
export async function fetchAttachmentCommitteeMeetings(committeeId: string): Promise<CommitteeAttachmentsMeeting[]> {
  const { data } = await apiClient.get<CommitteeAttachmentsMeeting[]>(
    `/documents/committee-attachments/committees/${committeeId}/meetings`,
  )
  return data
}

/** بعد اختيار اجتماع: مرفقاته + حالة محضره. */
export async function fetchAttachmentMeetingBundle(meetingId: string): Promise<CommitteeAttachmentsMeetingBundle> {
  const { data } = await apiClient.get<CommitteeAttachmentsMeetingBundle>(
    `/documents/committee-attachments/meetings/${meetingId}`,
  )
  return data
}

/** المحضر PDF — يُولَّد بالباك-إند لحظة الطلب فقط (عند الضغط على تحميل/فتح). */
export async function fetchMinutesPdfBlob(meetingId: string): Promise<{ blob: Blob; fileName: string }> {
  const response = await apiClient.get(`/meetings/${meetingId}/minutes/pdf`, {
    responseType: 'blob',
  })
  const disposition = String(response.headers['content-disposition'] ?? '')
  return {
    blob: response.data as Blob,
    fileName: fileNameFromDisposition(disposition, 'minutes.pdf'),
  }
}
