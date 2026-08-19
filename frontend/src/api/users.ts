import { apiClient } from '@/lib/apiClient'
import type { User, UserCreatePayload, UserUpdatePayload } from '@/types'

export async function fetchMe(): Promise<User> {
  const { data } = await apiClient.get<User>('/users/me')
  return data
}

export async function fetchUsers(): Promise<User[]> {
  const { data } = await apiClient.get<User[]>('/users')
  return data
}

export async function fetchUser(userId: string): Promise<User> {
  const { data } = await apiClient.get<User>(`/users/${userId}`)
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
