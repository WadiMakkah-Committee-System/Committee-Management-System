import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as notificationsApi from '@/api/notifications'

export const notificationsKeys = {
  all: ['notifications'] as const,
  // limit ضمن المفتاح: الجرس (معاينة قصيرة) وصفحة الإشعارات (صفحة كاملة) كانا
  // يتشاركان نفس الكاش، فتظهر صفحة الإشعارات أحيانًا بعدد عناصر المعاينة فقط.
  list: (unreadOnly: boolean, limit: number) => ['notifications', 'list', unreadOnly, limit] as const,
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

export function useNotifications(unreadOnly: boolean, limit = 50, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: notificationsKeys.list(unreadOnly, limit),
    queryFn: () => notificationsApi.fetchNotifications({ unreadOnly, limit }),
    enabled: options?.enabled ?? true,
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
