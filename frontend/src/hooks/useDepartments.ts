import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as departmentsApi from '@/api/departments'
import type { DepartmentCreatePayload, DepartmentUpdatePayload } from '@/types'

export const departmentsKeys = {
  all: ['departments'] as const,
}

export function useDepartments() {
  return useQuery({ queryKey: departmentsKeys.all, queryFn: departmentsApi.fetchDepartments })
}

export function useCreateDepartment() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: DepartmentCreatePayload) => departmentsApi.createDepartment(payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: departmentsKeys.all }),
  })
}

export function useUpdateDepartment() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ depId, payload }: { depId: string; payload: DepartmentUpdatePayload }) =>
      departmentsApi.updateDepartment(depId, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: departmentsKeys.all }),
  })
}

export function useDeleteDepartment() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (depId: string) => departmentsApi.deleteDepartment(depId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: departmentsKeys.all }),
  })
}
