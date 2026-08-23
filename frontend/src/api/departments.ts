import { apiClient } from '@/lib/apiClient'
import type { Department, DepartmentCreatePayload, DepartmentDetail, DepartmentUpdatePayload } from '@/types'

export async function fetchDepartments(): Promise<Department[]> {
  const { data } = await apiClient.get<Department[]>('/departments')
  return data
}

export async function fetchDepartment(depId: string): Promise<DepartmentDetail> {
  const { data } = await apiClient.get<DepartmentDetail>(`/departments/${depId}`)
  return data
}

export async function createDepartment(payload: DepartmentCreatePayload): Promise<Department> {
  const { data } = await apiClient.post<Department>('/departments', payload)
  return data
}

export async function updateDepartment(
  depId: string,
  payload: DepartmentUpdatePayload,
): Promise<Department> {
  const { data } = await apiClient.patch<Department>(`/departments/${depId}`, payload)
  return data
}

export async function deleteDepartment(depId: string): Promise<void> {
  await apiClient.delete(`/departments/${depId}`)
}
