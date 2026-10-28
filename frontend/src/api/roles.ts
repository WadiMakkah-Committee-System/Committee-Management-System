import { apiClient } from '@/lib/apiClient'
import type { Permission, Role, RoleCreatePayload, RoleOption, RoleUpdatePayload } from '@/types'

export async function fetchRoles(): Promise<Role[]> {
  const { data } = await apiClient.get<Role[]>('/roles')
  return data
}

/** أسماء الأدوار فقط (بدون الصلاحيات) — للقوائم المنسدلة والفلاتر. */
export async function fetchRoleOptions(): Promise<RoleOption[]> {
  const { data } = await apiClient.get<RoleOption[]>('/roles/options')
  return data
}

export async function fetchRole(roleId: string): Promise<Role> {
  const { data } = await apiClient.get<Role>(`/roles/${roleId}`)
  return data
}

export async function createRole(payload: RoleCreatePayload): Promise<Role> {
  const { data } = await apiClient.post<Role>('/roles', payload)
  return data
}

export async function updateRole(roleId: string, payload: RoleUpdatePayload): Promise<Role> {
  const { data } = await apiClient.patch<Role>(`/roles/${roleId}`, payload)
  return data
}

export async function deleteRole(roleId: string): Promise<void> {
  await apiClient.delete(`/roles/${roleId}`)
}

export async function fetchPermissions(): Promise<Permission[]> {
  const { data } = await apiClient.get<Permission[]>('/permissions')
  return data
}
