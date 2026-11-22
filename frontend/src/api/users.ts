import { apiClient } from '@/lib/apiClient'
import type { User, UserCreatePayload, UserDetail, UserUpdatePayload } from '@/types'

export async function fetchMe(): Promise<UserDetail> {
  const { data } = await apiClient.get<UserDetail>('/users/me')
  return data
}

/**
 * تبديل الدور الحالي للمستخدم نفسه — POST /users/me/active-role (تعدد الأدوار،
 * migration 0046). الباك-إند يقبل فقط دورًا من أدوار المستخدم المسندة، ويرجّع
 * بياناته الكاملة بعد التبديل (نفس شكل /users/me) فتتحدّث الصلاحيات مباشرة.
 */
export async function switchActiveRole(roleId: string): Promise<UserDetail> {
  const { data } = await apiClient.post<UserDetail>('/users/me/active-role', { role_id: roleId })
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
  /** parent_name: الإدارة الأم للإدارة الجديدة (null = بالمستوى الأعلى) — migration 0052. */
  departments_created: { name: string; code: string; parent_name: string | null }[]
  /** مسميات وظيفية أُضيفت تلقائيًا لأنها لم تكن موجودة. */
  job_titles_created: string[]
  emails_queued: number
  /** عدد التعيينات (إدارة + دور) — قد يزيد على عدد المستخدمين. */
  assignments_count: number
}

/** معاينة الرفع قبل التأكيد — POST /users/import/preview (لا يُكتب شيء). */
export interface UserImportPreview {
  users_count: number
  assignments_count: number
  users: {
    row: number
    full_name: string
    email: string
    primary_department: string | null
    assignments: { department: string | null; role: string | null }[]
  }[]
  departments_to_create: { name: string; parent_name: string | null }[]
  job_titles_to_create: string[]
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

/**
 * معاينة ملف المستخدمين — POST /users/import/preview: نفس تحقق الرفع بالكامل
 * (ونفس شكل أخطاء 400)، ويرجع ملخص ما سيُنشأ بلا أي كتابة.
 */
export async function previewImportUsers(file: File): Promise<UserImportPreview> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await apiClient.post<UserImportPreview>('/users/import/preview', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

/** تحميل نموذج Excel الفارغ بقوائم محدثة من النظام — GET /users/import/template. */
export async function fetchImportTemplate(): Promise<Blob> {
  const { data } = await apiClient.get<Blob>('/users/import/template', { responseType: 'blob' })
  return data
}
