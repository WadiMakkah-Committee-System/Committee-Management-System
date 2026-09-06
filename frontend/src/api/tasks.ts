import { apiClient } from '@/lib/apiClient'
import type {
  Task,
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
