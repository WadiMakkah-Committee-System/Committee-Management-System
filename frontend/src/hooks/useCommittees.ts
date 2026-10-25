import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as committeesApi from '@/api/committees'
import type { CommitteeDatesUpdatePayload } from '@/api/committees'
import type { Committee } from '@/types'
import { seedFromLists } from '@/lib/listCache'

export const committeesKeys = {
  all: ['committees'] as const,
  detail: (committeeId: string) => ['committees', committeeId] as const,
}

/** بيانات مرجعية نادرًا ما تتغيّر — تبقى حديثة 5 دقائق بالتنقل بين الصفحات
 * (أي تعديل من داخل النظام يُبطلها فورًا كالسابق). تحسين أداء 2026-10-25. */
export const REFERENCE_STALE_TIME = 5 * 60_000

export function useCommittees() {
  return useQuery({
    queryKey: committeesKeys.all,
    queryFn: committeesApi.fetchCommittees,
    staleTime: REFERENCE_STALE_TIME,
  })
}

export function useCommitteeDetail(committeeId: string | undefined) {
  const queryClient = useQueryClient()
  return useQuery({
    queryKey: committeesKeys.detail(committeeId ?? ''),
    queryFn: () => committeesApi.fetchCommittee(committeeId as string),
    enabled: !!committeeId,
    staleTime: REFERENCE_STALE_TIME,
    // قائمة اللجان ترجع نفس شكل التفاصيل (CommitteeOut) — صفحات الاجتماع/القرار/
    // المهمة تحتاج لجنة العنصر، وغالبًا القائمة محمَّلة أصلًا (راجعي lib/listCache.ts).
    ...seedFromLists<Committee>(queryClient, committeesKeys.all, (c) => c.committee_id === committeeId, {
      exact: true,
    }),
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
