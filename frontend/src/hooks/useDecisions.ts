import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as decisionsApi from '@/api/decisions'
import type { DecisionCreatePayload, DecisionUpdatePayload, DecisionVoteChoice } from '@/types'

export const decisionsKeys = {
  all: ['decisions'] as const,
  detail: (decisionId: string) => ['decisions', decisionId] as const,
}

export function useDecisions() {
  return useQuery({ queryKey: decisionsKeys.all, queryFn: decisionsApi.fetchDecisions })
}

export function useDecisionDetail(decisionId: string | undefined) {
  return useQuery({
    queryKey: decisionsKeys.detail(decisionId ?? ''),
    queryFn: () => decisionsApi.fetchDecision(decisionId as string),
    enabled: !!decisionId,
  })
}

function invalidateDecisionQueries(
  queryClient: ReturnType<typeof useQueryClient>,
  decisionId?: string,
) {
  queryClient.invalidateQueries({ queryKey: decisionsKeys.all })
  if (decisionId) {
    queryClient.invalidateQueries({ queryKey: decisionsKeys.detail(decisionId) })
  }
}

export function useCreateDecision() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: DecisionCreatePayload) => decisionsApi.createDecision(payload),
    onSuccess: () => invalidateDecisionQueries(queryClient),
  })
}

export function useUpdateDecision() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      decisionId,
      payload,
    }: {
      decisionId: string
      payload: DecisionUpdatePayload
    }) => decisionsApi.updateDecision(decisionId, payload),
    onSuccess: (_data, variables) => invalidateDecisionQueries(queryClient, variables.decisionId),
  })
}

export function useDeleteDecision() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (decisionId: string) => decisionsApi.deleteDecision(decisionId),
    onSuccess: () => invalidateDecisionQueries(queryClient),
  })
}

export function useOpenVoting() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      decisionId,
      votingDeadline,
    }: {
      decisionId: string
      votingDeadline?: string | null
    }) => decisionsApi.openVoting(decisionId, votingDeadline),
    onSuccess: (_data, variables) => invalidateDecisionQueries(queryClient, variables.decisionId),
  })
}

export function useCastVote() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ decisionId, choice }: { decisionId: string; choice: DecisionVoteChoice }) =>
      decisionsApi.castVote(decisionId, choice),
    onSuccess: (_data, variables) => invalidateDecisionQueries(queryClient, variables.decisionId),
  })
}

export function useApproveDecision() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (decisionId: string) => decisionsApi.approveDecision(decisionId),
    onSuccess: (_data, decisionId) => invalidateDecisionQueries(queryClient, decisionId),
  })
}
