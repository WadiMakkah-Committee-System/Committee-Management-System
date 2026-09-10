import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as meetingsApi from '@/api/meetings'
import { fetchMeetingChatMessages } from '@/api/meetingChat'
import * as meetingRecordingApi from '@/api/meetingRecording'
import * as meetingExtractedItemsApi from '@/api/meetingExtractedItems'
import type {
  AssignAsDecisionPayload,
  AssignAsTaskPayload,
} from '@/api/meetingExtractedItems'
import type {
  MeetingAgendaItemCreatePayload,
  MeetingAgendaItemUpdatePayload,
  MeetingAttachmentKind,
  MeetingCreatePayload,
  MeetingUpdatePayload,
} from '@/types'

export const meetingsKeys = {
  all: ['meetings'] as const,
  detail: (meetingId: string) => ['meetings', meetingId] as const,
  attachments: (meetingId: string) => ['meetings', meetingId, 'attachments'] as const,
  chatHistory: (meetingId: string) => ['meetings', meetingId, 'chat-history'] as const,
  // مساحة Cache مستقلة كليًا عن meetingsKeys.detail أعلاه — قرار موثّق مع
  // لاما 2026-09-10: قسم "المحاضر" يجب ألا يعتمد على بيانات محمَّلة مسبقًا
  // من قسم "الاجتماعات" (ولا العكس) بأي شكل، حتى عبر مشاركة Cache صامتة —
  // كل قسم يسوي استعلامه المستقل بنفسه دايمًا، بصرف النظر عن مسار الدخول
  // (من قسم الاجتماعات مباشرة، أو من قسم المحاضر مباشرة). راجعي
  // useMeetingDetailForMinutes أدناه، المستخدَمة حصرًا من MeetingMinutesPage.
  minutesSectionDetail: (meetingId: string) => ['minutes-section', 'meeting', meetingId] as const,
}

/** تحميل تاريخ المحادثة مرة واحدة عند فتح لوحة "المحادثة" — الرسائل
 * الجديدة تصل بعدها عبر useMeetingRealtime (WebSocket)، لا Polling على
 * هذا الاستعلام (بلا refetchInterval عمدًا). */
export function useMeetingChatHistory(meetingId: string | undefined) {
  return useQuery({
    queryKey: meetingsKeys.chatHistory(meetingId ?? ''),
    queryFn: () => fetchMeetingChatMessages(meetingId as string),
    enabled: !!meetingId,
    staleTime: Infinity,
  })
}

export function useMeetings() {
  return useQuery({ queryKey: meetingsKeys.all, queryFn: meetingsApi.fetchMeetings })
}

/**
 * تعديل لاما 2026-09-06: إضافة refetchIntervalMs اختياري — تستخدمه غرفة
 * الاجتماع (MeetingRoom.tsx) فقط لاكتشاف انتهاء وقت الاجتماع
 * (status → finished بالباك-إند، تحويل كسول بلا Scheduler منفصل — راجعي
 * meeting_service.py::_maybe_transition_status) أثناء بقاء الغرفة مفتوحة،
 * بلا Polling على بقية استدعاءات هذا الـHook بالتطبيق (مثل
 * MeetingDetailPage.tsx التي تستدعيه بلا Options — كل استدعاء لهذا
 * الـHook هو Observer مستقل بخياراته الخاصة رغم مشاركة نفس queryKey/الـ
 * Cache، فلا يتأثر أي استدعاء آخر بهذا الخيار).
 */
export function useMeetingDetail(
  meetingId: string | undefined,
  options?: { refetchIntervalMs?: number },
) {
  return useQuery({
    queryKey: meetingsKeys.detail(meetingId ?? ''),
    queryFn: () => meetingsApi.fetchMeeting(meetingId as string),
    enabled: !!meetingId,
    refetchInterval: options?.refetchIntervalMs,
  })
}

/**
 * نسخة مستقلة من useMeetingDetail أعلاه، حصرًا لقسم "المحاضر"
 * (MeetingMinutesPage.tsx) — قرار موثّق مع لاما 2026-09-10: فصل تام بين
 * قسمي "الاجتماعات" و"المحاضر"، بلا أي اعتماد على Cache محمَّل مسبقًا من
 * الآخر. تستخدم queryKey مختلفة كليًا (meetingsKeys.minutesSectionDetail
 * بدل meetingsKeys.detail) فتُجبَر على طلب مستقل من الباك-إند بمجرد
 * الدخول لقسم المحاضر واختيار اجتماع، بصرف النظر هل زارت المستخدمة صفحة
 * تفاصيل الاجتماع بقسم "الاجتماعات" قبلها أو لا. دالة الجلب نفسها
 * (meetingsApi.fetchMeeting) نفس المستخدَمة بـuseMeetingDetail — الفرق
 * فقط بمساحة الـCache، لا بمصدر البيانات بالباك-إند.
 */
export function useMeetingDetailForMinutes(meetingId: string | undefined) {
  return useQuery({
    queryKey: meetingsKeys.minutesSectionDetail(meetingId ?? ''),
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

export function useMeetingAttachments(meetingId: string | undefined, kind?: MeetingAttachmentKind) {
  return useQuery({
    queryKey: [...meetingsKeys.attachments(meetingId ?? ''), kind ?? 'all'] as const,
    queryFn: () => meetingsApi.fetchMeetingAttachments(meetingId as string, kind),
    enabled: !!meetingId,
  })
}

export function useUploadMeetingAttachment() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      meetingId,
      file,
      kind,
      title,
    }: {
      meetingId: string
      file: File
      kind: MeetingAttachmentKind
      title?: string
    }) => meetingsApi.uploadMeetingAttachment(meetingId, file, kind, title),
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
 * document_id هو نفسه معرّف الوثيقة بوحدة "إدارة الوثائق" — لكن التحميل
 * يمر عبر مسار مخصص بوحدة الاجتماعات (وليس GET /documents مباشرة) لأن
 * ذلك المسار العام يتطلب صلاحية documents.download المنفصلة التي لا
 * يملكها عضو اللجنة العادي غالبًا (راجعي api/meetings.ts).
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


// ============================== التسجيل الصوتي + المسودة (AI) ==============================
// راجعي رأس app/api/v1/meetings.py (قسم "التسجيل الصوتي + المسودة")
// وapi/meetingRecording.ts. 403 (لا صلاحية meetings.record_audio/
// draft.summarize/draft.view) و404 (لا تسجيل/مسودة بعد) حالتان طبيعيتان
// هنا — RecordingPanel.tsx يعاملهما كحالة عرض عادية، لا خطأ يوقف الواجهة.

export function useMeetingRecording(meetingId: string | undefined) {
  return useQuery({
    queryKey: ['meetings', meetingId ?? '', 'recording'] as const,
    queryFn: () => meetingRecordingApi.fetchMeetingRecording(meetingId as string),
    enabled: !!meetingId,
    retry: false,
  })
}

export function useUploadMeetingRecording() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      meetingId,
      file,
      durationSeconds,
    }: {
      meetingId: string
      file: File
      durationSeconds?: number
    }) => meetingRecordingApi.uploadMeetingRecording(meetingId, file, durationSeconds),
    onSuccess: (_data, variables) =>
      queryClient.invalidateQueries({ queryKey: ['meetings', variables.meetingId, 'recording'] }),
  })
}

/**
 * تنزيل ملف التسجيل الصوتي فعليًا (وليس فتح رابط) — نفس نمط
 * useDownloadMeetingAttachment أعلاه بالضبط. تُستخدم بقسم "التسجيل
 * والمسودة" بصفحة تفاصيل الاجتماع (MeetingDetailPage.tsx).
 */
export function useDownloadMeetingRecording() {
  return useMutation({
    mutationFn: async (meetingId: string) => {
      const { blob, fileName } = await meetingRecordingApi.fetchMeetingRecordingBlob(meetingId)
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

export function useMeetingDraft(meetingId: string | undefined) {
  return useQuery({
    queryKey: ['meetings', meetingId ?? '', 'draft'] as const,
    queryFn: () => meetingRecordingApi.fetchMeetingDraft(meetingId as string),
    enabled: !!meetingId,
    retry: false,
  })
}

export function useGenerateMeetingDraft() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (meetingId: string) => meetingRecordingApi.generateMeetingDraft(meetingId),
    onSuccess: (_data, meetingId) =>
      queryClient.invalidateQueries({ queryKey: ['meetings', meetingId, 'draft'] }),
  })
}

// ============================== البنود المستخرجة من الاجتماع ==============================
// راجعي رأس api/meetingExtractedItems.ts + app/services/meeting_service.py
// (قسم "البنود المستخرجة من الاجتماع") للتصميم الكامل.

function extractedItemsKey(meetingId: string) {
  return ['meetings', meetingId, 'extracted-items'] as const
}

export function useMeetingExtractedItems(meetingId: string | undefined) {
  return useQuery({
    queryKey: extractedItemsKey(meetingId ?? ''),
    queryFn: () => meetingExtractedItemsApi.fetchMeetingExtractedItems(meetingId as string),
    enabled: !!meetingId,
  })
}

export function useExtractMeetingItems() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (meetingId: string) => meetingExtractedItemsApi.extractMeetingItems(meetingId),
    onSuccess: (_data, meetingId) =>
      queryClient.invalidateQueries({ queryKey: extractedItemsKey(meetingId) }),
  })
}

export function useAddManualExtractedItem() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ meetingId, text }: { meetingId: string; text: string }) =>
      meetingExtractedItemsApi.addManualExtractedItem(meetingId, text),
    onSuccess: (_data, variables) =>
      queryClient.invalidateQueries({ queryKey: extractedItemsKey(variables.meetingId) }),
  })
}

export function useDeleteExtractedItem() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ meetingId, itemId }: { meetingId: string; itemId: string }) =>
      meetingExtractedItemsApi.deleteExtractedItem(meetingId, itemId),
    onSuccess: (_data, variables) =>
      queryClient.invalidateQueries({ queryKey: extractedItemsKey(variables.meetingId) }),
  })
}

export function useAssignExtractedItemAsTask() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      meetingId,
      itemId,
      payload,
    }: {
      meetingId: string
      itemId: string
      payload: AssignAsTaskPayload
    }) => meetingExtractedItemsApi.assignExtractedItemAsTask(meetingId, itemId, payload),
    onSuccess: (_data, variables) =>
      queryClient.invalidateQueries({ queryKey: extractedItemsKey(variables.meetingId) }),
  })
}

export function useAssignExtractedItemAsDecision() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      meetingId,
      itemId,
      payload,
    }: {
      meetingId: string
      itemId: string
      payload: AssignAsDecisionPayload
    }) => meetingExtractedItemsApi.assignExtractedItemAsDecision(meetingId, itemId, payload),
    onSuccess: (_data, variables) =>
      queryClient.invalidateQueries({ queryKey: extractedItemsKey(variables.meetingId) }),
  })
}
