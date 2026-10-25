import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as tasksApi from '@/api/tasks'
import type { Task, TaskCreatePayload, TaskStatus, TaskUpdatePayload } from '@/types'
import { seedFromLists } from '@/lib/listCache'
import { applyOptimistic, patchEverywhere, removeFromLists, rollbackOptimistic } from '@/lib/optimistic'

export const tasksKeys = {
  all: ['tasks'] as const,
  detail: (taskId: string) => ['tasks', taskId] as const,
  activity: (taskId: string) => ['tasks', taskId, 'activity'] as const,
}

export function useTasks() {
  return useQuery({ queryKey: tasksKeys.all, queryFn: tasksApi.fetchTasks })
}

/**
 * تحميل مسبق لتفاصيل مهمة عند مرور الماوس على رابطها (تحسين أداء 2026-10-24) —
 * لو البيانات حديثة أصلًا بالكاش (staleTime) لا يُرسَل أي طلب.
 */
export function usePrefetchTask() {
  const queryClient = useQueryClient()
  return (taskId: string) =>
    queryClient.prefetchQuery({
      queryKey: tasksKeys.detail(taskId),
      queryFn: () => tasksApi.fetchTask(taskId),
      // لو العنصر بقائمة حديثة لا يُرسَل طلب (نفس seedFromLists بصفحة التفاصيل).
      ...seedFromLists<Task>(queryClient, tasksKeys.all, (t) => t.task_id === taskId, { exact: true }),
    })
}

export function useTaskDetail(taskId: string | undefined) {
  const queryClient = useQueryClient()
  return useQuery({
    queryKey: tasksKeys.detail(taskId ?? ''),
    queryFn: () => tasksApi.fetchTask(taskId as string),
    enabled: !!taskId,
  // يُعرض فورًا من القائمة إن كان فيها (نفس الشكل) — راجعي lib/listCache.ts.
    ...seedFromLists<Task>(queryClient, tasksKeys.all, (t) => t.task_id === taskId, { exact: true }),
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
    // تحديث متفائل: المهمة تختفي من القوائم فورًا، وترجع لو فشل الحذف.
    onMutate: (taskId) =>
      applyOptimistic(queryClient, [
        { queryKey: tasksKeys.all, update: removeFromLists<Task>((t) => t.task_id === taskId) },
      ]),
    onError: (_err, _taskId, snapshot) => rollbackOptimistic(queryClient, snapshot),
    onSettled: () => invalidateTaskQueries(queryClient),
  })
}

export function useUpdateTaskStatus() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ taskId, status }: { taskId: string; status: TaskStatus }) =>
      tasksApi.updateTaskStatus(taskId, status),
    // تحديث متفائل: الحالة الجديدة تظهر فورًا بالقائمة والتفاصيل.
    onMutate: ({ taskId, status }) =>
      applyOptimistic(queryClient, [
        {
          queryKey: tasksKeys.all,
          update: patchEverywhere<Task>((t) => t.task_id === taskId, (t) => ({ ...t, status })),
        },
      ]),
    onError: (_err, _vars, snapshot) => rollbackOptimistic(queryClient, snapshot),
    // رد السيرفر هو المهمة المحدَّثة كاملة — نضعه بالكاش مباشرة بدل طلب جلب إضافي للتفاصيل.
    onSuccess: (task) => queryClient.setQueryData(tasksKeys.detail(task.task_id), task),
    onSettled: (_data, _err, variables) => {
      queryClient.invalidateQueries({ queryKey: tasksKeys.all, exact: true })
      queryClient.invalidateQueries({ queryKey: tasksKeys.activity(variables.taskId) })
    },
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
