import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as tasksApi from '@/api/tasks'
import type { TaskCreatePayload, TaskStatus, TaskUpdatePayload } from '@/types'

export const tasksKeys = {
  all: ['tasks'] as const,
  detail: (taskId: string) => ['tasks', taskId] as const,
  activity: (taskId: string) => ['tasks', taskId, 'activity'] as const,
}

export function useTasks() {
  return useQuery({ queryKey: tasksKeys.all, queryFn: tasksApi.fetchTasks })
}

export function useTaskDetail(taskId: string | undefined) {
  return useQuery({
    queryKey: tasksKeys.detail(taskId ?? ''),
    queryFn: () => tasksApi.fetchTask(taskId as string),
    enabled: !!taskId,
  })
}

/** مسار المهمة الموحَّد (إعادة إسناد + تغييرات حالة/أولوية/بيانات) — راجعي app/services/task_service.get_task_activity بالباك-إند. */
export function useTaskActivity(taskId: string | undefined) {
  return useQuery({
    queryKey: tasksKeys.activity(taskId ?? ''),
    queryFn: () => tasksApi.fetchTaskActivity(taskId as string),
    enabled: !!taskId,
  })
}

function invalidateTaskQueries(queryClient: ReturnType<typeof useQueryClient>, taskId?: string) {
  queryClient.invalidateQueries({ queryKey: tasksKeys.all })
  if (taskId) {
    queryClient.invalidateQueries({ queryKey: tasksKeys.detail(taskId) })
    queryClient.invalidateQueries({ queryKey: tasksKeys.activity(taskId) })
  }
}

export function useCreateTask() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: TaskCreatePayload) => tasksApi.createTask(payload),
    onSuccess: () => invalidateTaskQueries(queryClient),
  })
}

export function useUpdateTask() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ taskId, payload }: { taskId: string; payload: TaskUpdatePayload }) =>
      tasksApi.updateTask(taskId, payload),
    onSuccess: (_data, variables) => invalidateTaskQueries(queryClient, variables.taskId),
  })
}

export function useDeleteTask() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (taskId: string) => tasksApi.deleteTask(taskId),
    onSuccess: () => invalidateTaskQueries(queryClient),
  })
}

export function useUpdateTaskStatus() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ taskId, status }: { taskId: string; status: TaskStatus }) =>
      tasksApi.updateTaskStatus(taskId, status),
    onSuccess: (_data, variables) => invalidateTaskQueries(queryClient, variables.taskId),
  })
}

export function useReassignTask() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ taskId, assigneeUserId }: { taskId: string; assigneeUserId: string }) =>
      tasksApi.reassignTask(taskId, { assignee_user_id: assigneeUserId }),
    onSuccess: (_data, variables) => invalidateTaskQueries(queryClient, variables.taskId),
  })
}
