import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as minutesApi from '@/api/meetingMinutes'
import type { MinutesSection, MinutesTemplateId } from '@/types'

/** راجعي رأس api/meetingMinutes.ts — نفس نمط مفاتيح الاستعلام المستخدَم
 * لبقية موارد الاجتماع الفرعية (draft/recording) بـuseMeetings.ts. */
const minutesKey = (meetingId: string) => ['meetings', meetingId, 'minutes'] as const
const templatesKey = (meetingId: string) => ['meetings', meetingId, 'minutes', 'templates'] as const

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

function useMinutesMutation<TArgs extends { meetingId: string }, TResult>(
  fn: (args: TArgs) => Promise<TResult>,
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: minutesKey(variables.meetingId) })
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

export function useSendMinutesToReview() {
  return useMinutesMutation((args: { meetingId: string; reviewerUserIds: string[] }) =>
    minutesApi.sendMinutesToReview(args.meetingId, args.reviewerUserIds),
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
