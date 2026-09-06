import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as meetingsApi from '@/api/meetings'
import type {
  MeetingAgendaItemCreatePayload,
  MeetingAgendaItemUpdatePayload,
  MeetingAttachmentLinkRole,
  MeetingCreatePayload,
  MeetingUpdatePayload,
} from '@/types'

export const meetingsKeys = {
  all: ['meetings'] as const,
  detail: (meetingId: string) => ['meetings', meetingId] as const,
  attachments: (meetingId: string) => ['meetings', meetingId, 'attachments'] as const,
}

export function useMeetings() {
  return useQuery({ queryKey: meetingsKeys.all, queryFn: meetingsApi.fetchMeetings })
}

export function useMeetingDetail(meetingId: string | undefined) {
  return useQuery({
    queryKey: meetingsKeys.detail(meetingId ?? ''),
    queryFn: () => meetingsApi.fetchMeeting(meetingId as string),
    enabled: !!meetingId,
  })
}

function invalidateMeetingQueries(queryClient: ReturnType<typeof useQueryClient>, meetingId?: string) {
  queryClient.invalidateQueries({ queryKey: meetingsKeys.all })
  if (meetingId) {
    queryClient.invalidateQueries({ queryKey: meetingsKeys.detail(meetingId) })
  }
}

export function useCreateMeeting() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: MeetingCreatePayload) => meetingsApi.createMeeting(payload),
    onSuccess: () => invalidateMeetingQueries(queryClient),
  })
}

export function useUpdateMeeting() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ meetingId, payload }: { meetingId: string; payload: MeetingUpdatePayload }) =>
      meetingsApi.updateMeeting(meetingId, payload),
    onSuccess: (_data, variables) => invalidateMeetingQueries(queryClient, variables.meetingId),
  })
}

export function useDeleteMeeting() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (meetingId: string) => meetingsApi.deleteMeeting(meetingId),
    onSuccess: () => invalidateMeetingQueries(queryClient),
  })
}

/**
 * الانضمام لغرفة الفيديو — بلا onSuccess عام هنا (الاستدعاء داخل
 * MeetingRoom.tsx نفسه، فور فتح الغرفة)؛ نعيد تحديث تفاصيل الاجتماع بعد
 * أول انضمام لأن الباك-إند يضبط started_at (معلوماتي فقط، راجعي
 * migration 0022) — يفيد بتحديث واجهات أخرى تعرض نفس الاجتماع.
 */
export function useJoinMeeting() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (meetingId: string) => meetingsApi.joinMeeting(meetingId),
    onSuccess: (_data, meetingId) => invalidateMeetingQueries(queryClient, meetingId),
  })
}

export function useLeaveMeeting() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ meetingId, agoraUid }: { meetingId: string; agoraUid?: number }) =>
      meetingsApi.leaveMeeting(meetingId, agoraUid),
    onSuccess: (_data, variables) => invalidateMeetingQueries(queryClient, variables.meetingId),
  })
}

export function useAddAgendaItem() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      meetingId,
      payload,
    }: {
      meetingId: string
      payload: MeetingAgendaItemCreatePayload
    }) => meetingsApi.addAgendaItem(meetingId, payload),
    onSuccess: (_data, variables) => invalidateMeetingQueries(queryClient, variables.meetingId),
  })
}

export function useUpdateAgendaItem() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      agendaItemId,
      payload,
    }: {
      agendaItemId: string
      payload: MeetingAgendaItemUpdatePayload
      meetingId: string
    }) => meetingsApi.updateAgendaItem(agendaItemId, payload),
    onSuccess: (_data, variables) => invalidateMeetingQueries(queryClient, variables.meetingId),
  })
}

export function useDeleteAgendaItem() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ agendaItemId }: { agendaItemId: string; meetingId: string }) =>
      meetingsApi.deleteAgendaItem(agendaItemId),
    onSuccess: (_data, variables) => invalidateMeetingQueries(queryClient, variables.meetingId),
  })
}

// ============================== مرفقات الاجتماع ==============================

export function useMeetingAttachments(meetingId: string | undefined) {
  return useQuery({
    queryKey: meetingsKeys.attachments(meetingId ?? ''),
    queryFn: () => meetingsApi.fetchMeetingAttachments(meetingId as string),
    enabled: !!meetingId,
  })
}

export function useUploadMeetingAttachment() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      meetingId,
      file,
      linkRole,
    }: {
      meetingId: string
      file: File
      linkRole: MeetingAttachmentLinkRole
    }) => meetingsApi.uploadMeetingAttachment(meetingId, file, linkRole),
    onSuccess: (_data, variables) =>
      queryClient.invalidateQueries({ queryKey: meetingsKeys.attachments(variables.meetingId) }),
  })
}

export function useDeleteMeetingAttachment() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ meetingId, documentId }: { meetingId: string; documentId: string }) =>
      meetingsApi.deleteMeetingAttachment(meetingId, documentId),
    onSuccess: (_data, variables) =>
      queryClient.invalidateQueries({ queryKey: meetingsKeys.attachments(variables.meetingId) }),
  })
}

/**
 * تحميل ملف مرفق فعليًا (وليس فتح رابط مباشر) — التنزيل يتطلب
 * Authorization Bearer بالـheader (نفس منطق تحميل الوثائق العامة)، فيمر
 * عبر axios (fetchMeetingAttachmentBlob) ثم يُنزَّل بـobject URL مؤقت.
 */
export function useDownloadMeetingAttachment() {
  return useMutation({
    mutationFn: async ({ meetingId, documentId }: { meetingId: string; documentId: string }) => {
      const { blob, fileName } = await meetingsApi.fetchMeetingAttachmentBlob(meetingId, documentId)
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

/**
 * فتح المرفق للمعاينة بتبويب جديد (وليس تنزيله إجباريًا) — بخلاف
 * useDownloadMeetingAttachment أعلاه اللي يفرض Save-As دائمًا عبر
 * السمة download بالوسم <a>. المتصفح نفسه يقرر: يعرض الملف مباشرة لو
 * نوعه مدعوم بالعرض المدمج (PDF/صورة...)، أو ينزّله لو نوعه غير قابل
 * للعرض (مثال: docx) — هذا سلوك المتصفح الطبيعي، مو تحكّم منا.
 *
 * فتح النافذة يصير فورًا synchronous (window.open('', '_blank')) قبل أي
 * await — لو انتظرنا وصول الـblob أولًا ثم فتحنا النافذة، أغلب المتصفحات
 * تحجبها كـPopup لأنها لم تعد مرتبطة مباشرة بحدث نقرة المستخدم (User
 * Gesture). بعدين نحوّل مكانها (location.href) لرابط الـblob لما يجهز.
 */
export function useOpenMeetingAttachment() {
  return useMutation({
    mutationFn: async ({ meetingId, documentId }: { meetingId: string; documentId: string }) => {
      const previewWindow = window.open('', '_blank')
      try {
        const { blob } = await meetingsApi.fetchMeetingAttachmentBlob(meetingId, documentId)
        const url = URL.createObjectURL(blob)
        if (previewWindow) {
          previewWindow.location.href = url
        } else {
          // نادر: المتصفح حجب حتى النافذة الفارغة — محاولة أخيرة مباشرة.
          window.open(url, '_blank')
        }
        // تأخير التحرير (Revoke) لضمان انتهاء التبويب الجديد من تحميل
        // الملف فعليًا قبل ما يفقد رابط الـblob صلاحيته.
        window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
      } catch (err) {
        previewWindow?.close()
        throw err
      }
    },
  })
}
