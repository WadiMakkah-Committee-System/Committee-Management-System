import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as rolesApi from '@/api/roles'
import type { RoleCreatePayload, RoleUpdatePayload } from '@/types'

export const rolesKeys = {
  all: ['roles'] as const,
  permissions: ['permissions'] as const,
}

export function useRoles() {
  return useQuery({ queryKey: rolesKeys.all, queryFn: rolesApi.fetchRoles })
}

export function usePermissionsCatalog() {
  return useQuery({ queryKey: rolesKeys.permissions, queryFn: rolesApi.fetchPermissions })
}

export function useCreateRole() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: RoleCreatePayload) => rolesApi.createRole(payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: rolesKeys.all }),
  })
}

export function useUpdateRole() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ roleId, payload }: { roleId: string; payload: RoleUpdatePayload }) =>
      rolesApi.updateRole(roleId, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: rolesKeys.all }),
  })
}

export function useDeleteRole() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (roleId: string) => rolesApi.deleteRole(roleId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: rolesKeys.all }),
  })
}
