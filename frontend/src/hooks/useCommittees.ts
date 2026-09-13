import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as committeesApi from '@/api/committees'
import type { CommitteeDatesUpdatePayload } from '@/api/committees'

export const committeesKeys = {
  all: ['committees'] as const,
  detail: (committeeId: string) => ['committees', committeeId] as const,
}

export function useCommittees() {
  return useQuery({ queryKey: committeesKeys.all, queryFn: committeesApi.fetchCommittees })
}

export function useCommitteeDetail(committeeId: string | undefined) {
  return useQuery({
    queryKey: committeesKeys.detail(committeeId ?? ''),
    queryFn: () => committeesApi.fetchCommittee(committeeId as string),
    enabled: !!committeeId,
  })
}

/**
 * تعديل فترة عمل لجنة معتمدة (start_date/end_date فقط) — راجعي
 * committeesApi.updateCommitteeDates. يُبطِل قائمة اللجان وتفاصيل هذه
 * اللجنة تحديدًا عند النجاح (نفس نمط بقية الـmutations بالمشروع).
 */
export function useUpdateCommitteeDates(committeeId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: CommitteeDatesUpdatePayload) =>
      committeesApi.updateCommitteeDates(committeeId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: committeesKeys.all })
      queryClient.invalidateQueries({ queryKey: committeesKeys.detail(committeeId) })
    },
  })
}

/**
 * قسم "موظفو إدارتي بلجان أخرى" — يُفعَّل فقط لمستخدم له إدارة (dep_id)،
 * الباك-إند نفسه يرجع قائمة فارغة بدونها، لكن ما داعي لطلب شبكة أصلًا.
 */
export function useDepartmentMembersElsewhere(search: string, enabled: boolean) {
  return useQuery({
    queryKey: ['committees', 'department-members-elsewhere', search] as const,
    queryFn: () => committeesApi.fetchDepartmentMembersElsewhere(search || undefined),
    enabled,
  })
}
