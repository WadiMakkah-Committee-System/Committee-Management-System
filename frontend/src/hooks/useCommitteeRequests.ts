import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as committeeRequestsApi from '@/api/committeeRequests'
import type { CommitteeFormationRequestCreatePayload, CommitteeFormationRequestUpdatePayload } from '@/types'

export const committeeRequestsKeys = {
  all: ['committee-requests'] as const,
  detail: (requestId: string) => ['committee-requests', requestId] as const,
}

export function useCommitteeRequests() {
  return useQuery({
    queryKey: committeeRequestsKeys.all,
    queryFn: committeeRequestsApi.fetchCommitteeRequests,
  })
}

export function useCommitteeRequestDetail(requestId: string | undefined) {
  return useQuery({
    queryKey: committeeRequestsKeys.detail(requestId ?? ''),
    queryFn: () => committeeRequestsApi.fetchCommitteeRequest(requestId as string),
    enabled: !!requestId,
  })
}

function invalidateCommitteeRequestQueries(
  queryClient: ReturnType<typeof useQueryClient>,
  requestId?: string,
) {
  queryClient.invalidateQueries({ queryKey: committeeRequestsKeys.all })
  if (requestId) {
    queryClient.invalidateQueries({ queryKey: committeeRequestsKeys.detail(requestId) })
  }
}

export function useCreateCommitteeRequest() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: CommitteeFormationRequestCreatePayload) =>
      committeeRequestsApi.createCommitteeRequest(payload),
    onSuccess: () => invalidateCommitteeRequestQueries(queryClient),
  })
}

export function useUpdateCommitteeRequest() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      requestId,
      payload,
    }: {
      requestId: string
      payload: CommitteeFormationRequestUpdatePayload
    }) => committeeRequestsApi.updateCommitteeRequest(requestId, payload),
    onSuccess: (_data, variables) => invalidateCommitteeRequestQueries(queryClient, variables.requestId),
  })
}

export function useSubmitCommitteeRequest() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (requestId: string) => committeeRequestsApi.submitCommitteeRequest(requestId),
    onSuccess: (_data, requestId) => invalidateCommitteeRequestQueries(queryClient, requestId),
  })
}
