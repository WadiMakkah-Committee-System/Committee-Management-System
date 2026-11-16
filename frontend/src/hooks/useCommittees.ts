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

// =====================================================================
// تعديل عضوية اللجنة الدائمة + التمديد + سجل التغييرات (migration 0050).
// =====================================================================

export function useCommitteeCapabilities(committeeId: string | undefined) {
  return useQuery({
    queryKey: ['committees', committeeId ?? '', 'capabilities'],
    queryFn: () => committeesApi.fetchCommitteeCapabilities(committeeId as string),
    enabled: !!committeeId,
  })
}

export function useCommitteeChanges(committeeId: string | undefined, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: ['committees', committeeId ?? '', 'changes'],
    queryFn: () => committeesApi.fetchCommitteeChanges(committeeId as string),
    enabled: !!committeeId && (options?.enabled ?? true),
  })
}

export function useCommitteeMemberCandidates(committeeId: string | undefined, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: ['committees', committeeId ?? '', 'member-candidates'],
    queryFn: () => committeesApi.fetchCommitteeMemberCandidates(committeeId as string),
    enabled: !!committeeId && (options?.enabled ?? true),
  })
}

/** نوع عملية تعديل العضوية/الفترة — كلها تُرجع اللجنة المحدَّثة وتُبطل بياناتها وسجلها. */
export type CommitteeMembershipAction =
  | { kind: 'add'; userId: string; reason?: string }
  | { kind: 'remove'; userId: string; reason?: string }
  | { kind: 'chair'; userId: string }
  | { kind: 'secretary'; userId: string | null }
  | { kind: 'extend'; endDate: string; reason?: string }

export function useCommitteeMembershipAction(committeeId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (action: CommitteeMembershipAction) => {
      switch (action.kind) {
        case 'add':
          return committeesApi.addCommitteeMember(committeeId, action.userId, action.reason)
        case 'remove':
          return committeesApi.removeCommitteeMember(committeeId, action.userId, action.reason)
        case 'chair':
          return committeesApi.changeCommitteeChair(committeeId, action.userId)
        case 'secretary':
          return committeesApi.changeCommitteeSecretary(committeeId, action.userId)
        case 'extend':
          return committeesApi.extendCommittee(committeeId, action.endDate, action.reason)
      }
    },
    onSuccess: () => {
      // يبطل اللجنة وقائمتها وسجلها وصلاحياتها ومرشحيها (كلها تحت ['committees', ...]).
      queryClient.invalidateQueries({ queryKey: committeesKeys.all })
    },
  })
}
