import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as notificationsApi from '@/api/notifications'
import type { NotificationPage } from '@/types'
import { applyOptimistic, rollbackOptimistic } from '@/lib/optimistic'

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
    // تحديث متفائل: الإشعار يصير مقروءًا والعداد ينقص فورًا (لو كان غير مقروء فعلًا).
    onMutate: (notificationId) => {
      let wasUnread = false
      return applyOptimistic(queryClient, [
        {
          queryKey: ['notifications', 'list'],
          update: (data) => {
            const page = data as NotificationPage
            return {
              ...page,
              items: page.items.map((n) => {
                if (n.notification_id !== notificationId || n.is_read) return n
                wasUnread = true
                return { ...n, is_read: true, read_at: new Date().toISOString() }
              }),
            }
          },
        },
        {
          queryKey: notificationsKeys.unreadCount,
          update: (count) => (wasUnread ? Math.max(0, (count as number) - 1) : count),
        },
      ])
    },
    onError: (_err, _id, snapshot) => rollbackOptimistic(queryClient, snapshot),
    onSettled: () => invalidateNotificationQueries(queryClient),
  })
}

export function useMarkAllNotificationsRead() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => notificationsApi.markAllNotificationsRead(),
    // تحديث متفائل: كل الإشعارات المعروضة تصير مقروءة والعداد صفر فورًا.
    onMutate: () => {
      const now = new Date().toISOString()
      return applyOptimistic(queryClient, [
        {
          queryKey: ['notifications', 'list'],
          update: (data) => {
            const page = data as NotificationPage
            return {
              ...page,
              items: page.items.map((n) => (n.is_read ? n : { ...n, is_read: true, read_at: now })),
            }
          },
        },
        { queryKey: notificationsKeys.unreadCount, update: () => 0 },
      ])
    },
    onError: (_err, _vars, snapshot) => rollbackOptimistic(queryClient, snapshot),
    onSettled: () => invalidateNotificationQueries(queryClient),
  })
}
