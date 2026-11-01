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

/** مستخدم أُنشئ من صف بملف الرفع (users.import). */
export interface ImportedUser {
  row: number
  user_id: string
  full_name: string
  email: string
  username: string
  department: string | null
  role: string | null
  is_department_manager: boolean
}

/** استجابة نجاح POST /users/import — بدون كلمات مرور (تُرسل لبريد كل مستخدم فقط). */
export interface UserImportResult {
  created_count: number
  users: ImportedUser[]
  departments_created: { name: string; code: string }[]
  emails_queued: number
}

/** خطأ بصف محدد بالملف (row = رقم الصف كما يظهر بالـExcel). */
export interface ImportRowError {
  row: number
  field: string | null
  message: string
}

/**
 * رفع ملف المستخدمين — POST /users/import (multipart، يتطلب users.import).
 * الكل أو لا شيء: عند وجود أي خطأ بالصفوف يرمي 400 بـ
 * detail = { message, errors: ImportRowError[] } ولا يُنشأ أحد.
 */
export async function importUsers(file: File): Promise<UserImportResult> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await apiClient.post<UserImportResult>('/users/import', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

/** تحميل نموذج Excel الفارغ بقوائم محدثة من النظام — GET /users/import/template. */
export async function fetchImportTemplate(): Promise<Blob> {
  const { data } = await apiClient.get<Blob>('/users/import/template', { responseType: 'blob' })
  return data
}
