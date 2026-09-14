import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as minutesApi from '@/api/meetingMinutes'
import type { MinutesSection, MinutesTemplateId } from '@/types'

/** راجعي رأس api/meetingMinutes.ts — نفس نمط مفاتيح الاستعلام المستخدَم
 * لبقية موارد الاجتماع الفرعية (draft/recording) بـuseMeetings.ts. */
const minutesKey = (meetingId: string) => ['meetings', meetingId, 'minutes'] as const
const templatesKey = (meetingId: string) => ['meetings', meetingId, 'minutes', 'templates'] as const
/** مساحة Cache مستقلة عن minutesKey أعلاه — مفتاحها المخصص (وليس
 * minutesKey نفسه) عمدًا: راجعي useMeetingMinutesDetail أدناه. */
const minutesDetailKey = (meetingId: string) => ['meetings', meetingId, 'minutes', 'detail'] as const

export function useMeetingMinutes(meetingId: string | undefined) {
  return useQuery({
    queryKey: minutesKey(meetingId ?? ''),
    queryFn: () => minutesApi.fetchMeetingMinutes(meetingId ?? ''),
    enabled: !!meetingId,
  })
}

export function useMinutesTemplates(meetingId: string | undefined) {
  return useQuery({
    queryKey: templatesKey(meetingId ?? ''),
    queryFn: () => minutesApi.fetchMinutesTemplates(meetingId ?? ''),
    enabled: !!meetingId,
  })
}

/**
 * إصلاح أداء (التوصية الثانية بتقرير أداء لاما 2026-09-14 — راجعي رأس
 * api/meetingMinutes.ts::fetchMeetingMinutesDetail): تستبدل حصرًا بصفحة
 * "محضر الاجتماع" (MeetingMinutesPage.tsx) خمسة استعلامات منفصلة كانت
 * تُستخدَم معًا (useMeetingDetailForMinutes + useCommitteeDetail +
 * useMeetingMinutes + useMinutesTemplates + useMeetingExtractedItems)
 * باستعلام واحد فقط. useMinutesMutation أدناه (تُستخدَم حصرًا لطفرات
 * المحضر — اختيار قالب/تعديل أقسام/مراجعة/اعتماد/توقيع، كلها من هذي
 * الصفحة فقط) تُبطِل مساحة الـCache هذي أيضًا بجانب minutesKey القديمة،
 * عبر invalidateMinutesDetail أدناه — وإلا تبقى الصفحة تعرض بيانات قديمة
 * بعد أي إجراء ناجح.
 */
export function useMeetingMinutesDetail(meetingId: string | undefined) {
  return useQuery({
    queryKey: minutesDetailKey(meetingId ?? ''),
    queryFn: () => minutesApi.fetchMeetingMinutesDetail(meetingId ?? ''),
    enabled: !!meetingId,
  })
}

function invalidateMinutesDetail(queryClient: ReturnType<typeof useQueryClient>, meetingId: string) {
  queryClient.invalidateQueries({ queryKey: minutesDetailKey(meetingId) })
}

function useMinutesMutation<TArgs extends { meetingId: string }, TResult>(
  fn: (args: TArgs) => Promise<TResult>,
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: minutesKey(variables.meetingId) })
      // بعد توحيد صفحة "محضر الاجتماع" على useMeetingMinutesDetail (راجعي
      // أعلاه) — هذي كل طفرات المحضر (اختيار قالب/تعديل أقسام/مراجعة/
      // اعتماد/توقيع) لازم تُبطِل استعلام التفاصيل الموحَّد أيضًا، وإلا
      // تبقى الصفحة تعرض بيانات قديمة بعد أي إجراء رغم نجاحه فعليًا
      // بالباك-إند (minutesKey أعلاه لم يعد يُستخدَم بهذي الصفحة إطلاقًا).
      invalidateMinutesDetail(queryClient, variables.meetingId)
    },
  })
}

export function useSelectMinutesTemplate() {
  return useMinutesMutation((args: { meetingId: string; templateId: MinutesTemplateId }) =>
    minutesApi.selectMinutesTemplate(args.meetingId, args.templateId),
  )
}

export function useUpdateMinutesSections() {
  return useMinutesMutation((args: { meetingId: string; sections: MinutesSection[] }) =>
    minutesApi.updateMinutesSections(args.meetingId, args.sections),
  )
}

export function useApproveMinutesReview() {
  return useMinutesMutation((args: { meetingId: string; comment?: string }) =>
    minutesApi.approveMinutesReview(args.meetingId, args.comment),
  )
}

export function useReturnMinutesReview() {
  return useMinutesMutation((args: { meetingId: string; comment: string }) =>
    minutesApi.returnMinutesReview(args.meetingId, args.comment),
  )
}

export function useApproveMinutes() {
  return useMinutesMutation((args: { meetingId: string }) => minutesApi.approveMinutes(args.meetingId))
}

export function useReturnMinutesForEdit() {
  return useMinutesMutation((args: { meetingId: string; comment: string }) =>
    minutesApi.returnMinutesForEdit(args.meetingId, args.comment),
  )
}

export function useSendMinutesForSignature() {
  return useMinutesMutation((args: { meetingId: string }) =>
    minutesApi.sendMinutesForSignature(args.meetingId),
  )
}

export function useSignMinutes() {
  return useMinutesMutation((args: { meetingId: string; signatureImage: string }) =>
    minutesApi.signMinutes(args.meetingId, args.signatureImage),
  )
}
