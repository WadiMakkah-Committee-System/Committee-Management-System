import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as decisionsApi from '@/api/decisions'
import type {
  Decision,
  DecisionCreatePayload,
  DecisionOpenVotingPayload,
  DecisionUpdatePayload,
} from '@/types'
import { useAuthStore } from '@/store/authStore'
import { applyOptimistic, patchEverywhere, removeFromLists, rollbackOptimistic } from '@/lib/optimistic'

export const decisionsKeys = {
  all: ['decisions'] as const,
  byMeeting: (meetingId: string) => ['decisions', 'meeting', meetingId] as const,
  detail: (decisionId: string) => ['decisions', decisionId] as const,
}

export function useDecisions() {
  return useQuery({ queryKey: decisionsKeys.all, queryFn: () => decisionsApi.fetchDecisions() })
}

/** قرارات اجتماع واحد فقط — تستخدمها لوحة "القرارات" داخل غرفة الاجتماع (DecisionsPanel). */
export function useMeetingDecisions(meetingId: string | undefined) {
  return useQuery({
    queryKey: decisionsKeys.byMeeting(meetingId ?? ''),
    queryFn: () => decisionsApi.fetchDecisions(meetingId),
    enabled: !!meetingId,
  })
}

/** تحميل مسبق لتفاصيل قرار عند مرور الماوس على رابطه (تحسين أداء 2026-10-24). */
export function usePrefetchDecision() {
  const queryClient = useQueryClient()
  return (decisionId: string) =>
    queryClient.prefetchQuery({
      queryKey: decisionsKeys.detail(decisionId),
      queryFn: () => decisionsApi.fetchDecision(decisionId),
    })
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
  queryClient.invalidateQueries({ queryKey: ['decisions', 'meeting'] })
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
    // تحديث متفائل: القرار يختفي من كل القوائم (العامة وقوائم الاجتماعات) فورًا.
    onMutate: (decisionId) =>
      applyOptimistic(queryClient, [
        { queryKey: ['decisions'], update: removeFromLists<Decision>((d) => d.decision_id === decisionId) },
      ]),
    onError: (_err, _decisionId, snapshot) => rollbackOptimistic(queryClient, snapshot),
    onSettled: () => invalidateDecisionQueries(queryClient),
  })
}

export function useOpenVoting() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      decisionId,
      payload,
    }: {
      decisionId: string
      payload: DecisionOpenVotingPayload
    }) => decisionsApi.openVoting(decisionId, payload),
    onSuccess: (_data, variables) => invalidateDecisionQueries(queryClient, variables.decisionId),
  })
}

export function useCastVote() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ decisionId, optionId }: { decisionId: string; optionId: string }) =>
      decisionsApi.castVote(decisionId, optionId),
    // تحديث متفائل: صوت المستخدم الحالي يظهر على الخيار المختار فورًا (يستبدل
    // صوته السابق إن وُجد) — بالتفاصيل وبكل القوائم (منها لوحة القرارات
    // داخل غرفة الاجتماع).
    onMutate: ({ decisionId, optionId }) => {
      const me = useAuthStore.getState().user
      if (!me) return undefined
      return applyOptimistic(queryClient, [
        {
          queryKey: ['decisions'],
          update: patchEverywhere<Decision>(
            (d) => d.decision_id === decisionId,
            (d) => {
              const option = d.vote_options.find((o) => o.option_id === optionId)
              if (!option) return d
              const voter = {
                user_id: me.user_id,
                first_name: me.first_name,
                middle_name: me.middle_name,
                last_name: me.last_name,
                email: me.email,
              }
              return {
                ...d,
                votes: [
                  ...d.votes.filter((v) => v.voter.user_id !== me.user_id),
                  { voter, option, voted_at: new Date().toISOString() },
                ],
              }
            },
          ),
        },
      ])
    },
    onError: (_err, _vars, snapshot) => rollbackOptimistic(queryClient, snapshot),
    // رد السيرفر هو القرار المحدَّث كاملًا (قد يكون أُغلق التصويت أو رُفض
    // القرار تلقائيًا بهذا الصوت) — نضعه بالكاش مباشرة ثم نعيد مزامنة القوائم.
    onSuccess: (decision) => queryClient.setQueryData(decisionsKeys.detail(decision.decision_id), decision),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: decisionsKeys.all, exact: true })
      queryClient.invalidateQueries({ queryKey: ['decisions', 'meeting'] })
    },
  })
}

export function useApproveDecision() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (decisionId: string) => decisionsApi.approveDecision(decisionId),
    onSuccess: (_data, decisionId) => invalidateDecisionQueries(queryClient, decisionId),
  })
}
