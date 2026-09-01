import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as meetingsApi from '@/api/meetings'
import type {
  MeetingAgendaItemCreatePayload,
  MeetingAgendaItemUpdatePayload,
  MeetingCreatePayload,
  MeetingUpdatePayload,
} from '@/types'

export const meetingsKeys = {
  all: ['meetings'] as const,
  detail: (meetingId: string) => ['meetings', meetingId] as const,
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
