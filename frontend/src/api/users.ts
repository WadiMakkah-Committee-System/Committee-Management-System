import { apiClient } from '@/lib/apiClient'
import type { User, UserCreatePayload, UserDetail, UserUpdatePayload } from '@/types'

export async function fetchMe(): Promise<UserDetail> {
  const { data } = await apiClient.get<UserDetail>('/users/me')
  return data
}

export async function fetchUsers(dep_id?: string): Promise<User[]> {
  const { data } = await apiClient.get<User[]>('/users', { params: dep_id ? { dep_id } : undefined })
  return data
}

export async function fetchUser(userId: string): Promise<UserDetail> {
  const { data } = await apiClient.get<UserDetail>(`/users/${userId}`)
  return data
}

export async function createUser(payload: UserCreatePayload): Promise<User> {
  const { data } = await apiClient.post<User>('/users', payload)
  return data
}

export async function updateUser(userId: string, payload: UserUpdatePayload): Promise<User> {
  const { data } = await apiClient.patch<User>(`/users/${userId}`, payload)
  return data
}

export async function deleteUser(userId: string): Promise<void> {
  await apiClient.delete(`/users/${userId}`)
}

export async function suspendUser(userId: string): Promise<User> {
  const { data } = await apiClient.post<User>(`/users/${userId}/suspend`)
  return data
}

export async function reactivateUser(userId: string): Promise<User> {
  const { data } = await apiClient.post<User>(`/users/${userId}/reactivate`)
  return data
}
