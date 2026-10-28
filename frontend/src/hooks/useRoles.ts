import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as rolesApi from '@/api/roles'
import type { RoleCreatePayload, RoleUpdatePayload } from '@/types'
import { REFERENCE_STALE_TIME } from '@/hooks/useCommittees'

export const rolesKeys = {
  all: ['roles'] as const,
  // تحت ['roles'] عمدًا: أي invalidate لـrolesKeys.all بعد إنشاء/تعديل دور
  // يُبطل قائمة الخيارات الخفيفة أيضًا.
  options: ['roles', 'options'] as const,
  permissions: ['permissions'] as const,
}

export function useRoles(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: rolesKeys.all,
    queryFn: rolesApi.fetchRoles,
    enabled: options?.enabled ?? true,
  })
}

/**
 * الهدف: قائمة أدوار خفيفة (اسم ونوع فقط) للقوائم المنسدلة والفلاتر — صفحة
 * المستخدمين ونموذج المستخدم. تحسين أداء 2026-10-28: بدل useRoles() اللي
 * تجلب كل دور بكل صلاحياته (≈80 كيلوبايت) لعرض أسماء الأدوار فقط.
 */
export function useRoleOptions(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: rolesKeys.options,
    queryFn: rolesApi.fetchRoleOptions,
    staleTime: REFERENCE_STALE_TIME,
    enabled: options?.enabled ?? true,
  })
}

export function usePermissionsCatalog(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: rolesKeys.permissions,
    queryFn: rolesApi.fetchPermissions,
    staleTime: REFERENCE_STALE_TIME, // بيانات مرجعية — راجعي useCommittees.ts
    enabled: options?.enabled ?? true,
  })
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
