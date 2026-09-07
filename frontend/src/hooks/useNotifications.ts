import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as notificationsApi from '@/api/notifications'

export const notificationsKeys = {
  all: ['notifications'] as const,
  list: (unreadOnly: boolean) => ['notifications', 'list', unreadOnly] as const,
  unreadCount: ['notifications', 'unread-count'] as const,
}

/** عدّاد الجرس بالـTopbar — يستطلع كل 30 ثانية عشان يبقى العداد قريب من اللحظي بدون WebSocket. */
export function useUnreadCount() {
  return useQuery({
    queryKey: notificationsKeys.unreadCount,
    queryFn: notificationsApi.fetchUnreadCount,
    refetchInterval: 30_000,
  })
}

export function useNotifications(unreadOnly: boolean, limit = 50) {
  return useQuery({
    queryKey: notificationsKeys.list(unreadOnly),
    queryFn: () => notificationsApi.fetchNotifications({ unreadOnly, limit }),
  })
}

function invalidateNotificationQueries(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: notificationsKeys.all })
}

export function useMarkNotificationRead() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (notificationId: string) => notificationsApi.markNotificationRead(notificationId),
    onSuccess: () => invalidateNotificationQueries(queryClient),
  })
}

export function useMarkAllNotificationsRead() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => notificationsApi.markAllNotificationsRead(),
    onSuccess: () => invalidateNotificationQueries(queryClient),
  })
}
