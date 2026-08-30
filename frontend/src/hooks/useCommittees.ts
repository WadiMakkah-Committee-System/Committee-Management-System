import { useQuery } from '@tanstack/react-query'
import * as committeesApi from '@/api/committees'

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
