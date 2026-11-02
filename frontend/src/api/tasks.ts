import { apiClient } from '@/lib/apiClient'
import type {
  Task,
  TaskActivityEntry,
  TaskAttachment,
  TaskCreatePayload,
  TaskReassignPayload,
  TaskStatus,
  TaskUpdatePayload,
} from '@/types'

/**
 * وحدة "إدارة المهام" — تقابل app/api/v1/tasks.py بالباك-إند. إنشاء
 * مباشر من واجهة المهام فقط (بدون مهام مستخرجة من اجتماع بالذكاء
 * الاصطناعي — تُبنى لاحقًا)، مسؤول واحد فقط لكل مهمة. التفويض هيكلي
 * (دور اللجنة/النظام) بالإضافة لتقييد على مستوى الكائن نفسه للعرض
 * وتحديث الحالة — راجعي hooks/useTasks.ts وTasksPage.tsx.
 */

export async function fetchTasks(): Promise<Task[]> {
  const { data } = await apiClient.get<Task[]>('/tasks')
  return data
}

export async function fetchTask(taskId: string): Promise<Task> {
  const { data } = await apiClient.get<Task>(`/tasks/${taskId}`)
  return data
}

export async function fetchTaskActivity(taskId: string): Promise<TaskActivityEntry[]> {
  const { data } = await apiClient.get<TaskActivityEntry[]>(`/tasks/${taskId}/activity`)
  return data
}

export async function createTask(payload: TaskCreatePayload): Promise<Task> {
  const { data } = await apiClient.post<Task>('/tasks', payload)
  return data
}

export async function updateTask(taskId: string, payload: TaskUpdatePayload): Promise<Task> {
  const { data } = await apiClient.patch<Task>(`/tasks/${taskId}`, payload)
  return data
}

export async function deleteTask(taskId: string): Promise<void> {
  await apiClient.delete(`/tasks/${taskId}`)
}

export async function updateTaskStatus(taskId: string, status: TaskStatus): Promise<Task> {
  const { data } = await apiClient.post<Task>(`/tasks/${taskId}/status`, { status })
  return data
}

export async function reassignTask(
  taskId: string,
  payload: TaskReassignPayload,
): Promise<Task> {
  const { data } = await apiClient.post<Task>(`/tasks/${taskId}/reassign`, payload)
  return data
}

/**
 * مرفقات المهمة (طلب صاحبة المشروع 2026-11-01) — رئيسة اللجنة تقدر ترفق
 * ملفًا اختياريًا عند الإنشاء، والمسؤول عن المهمة يرفع/يعدّل/يحذف أكثر
 * من ملف لاحقًا. نفس نمط مرفقات الاجتماعات تمامًا.
 */
export async function fetchTaskAttachments(taskId: string): Promise<TaskAttachment[]> {
  const { data } = await apiClient.get<TaskAttachment[]>(`/tasks/${taskId}/attachments`)
  return data
}

export async function uploadTaskAttachment(taskId: string, file: File): Promise<TaskAttachment> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await apiClient.post<TaskAttachment>(
    `/tasks/${taskId}/attachments`,
    form,
    { headers: { 'Content-Type': 'multipart/form-data' } },
  )
  return data
}

export async function deleteTaskAttachment(taskId: string, documentId: string): Promise<void> {
  await apiClient.delete(`/tasks/${taskId}/attachments/${documentId}`)
}

export async function fetchTaskAttachmentBlob(
  taskId: string,
  documentId: string,
): Promise<{ blob: Blob; fileName: string }> {
  const response = await apiClient.get(
    `/tasks/${taskId}/attachments/${documentId}/download`,
    { responseType: 'blob' },
  )
  const disposition = String(response.headers['content-disposition'] ?? '')
  const match = /filename="?([^"]+)"?/.exec(disposition)
  return { blob: response.data as Blob, fileName: match?.[1] ?? 'attachment' }
}
