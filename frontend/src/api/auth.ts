import { apiClient } from '@/lib/apiClient'
import type { LoginPayload, TokenResponse } from '@/types'

export async function login(payload: LoginPayload): Promise<TokenResponse> {
  const { data } = await apiClient.post<TokenResponse>('/auth/login', payload)
  return data
}

export async function logout(): Promise<void> {
  await apiClient.post('/auth/logout')
}

export async function changePassword(payload: {
  current_password: string
  new_password: string
}): Promise<void> {
  await apiClient.post('/auth/change-password', payload)
}
