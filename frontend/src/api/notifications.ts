import { apiClient } from '@/lib/apiClient'
import type { Notification, NotificationPage } from '@/types'

/**
 * وحدة "الإشعارات" داخل النظام — تقابل app/api/v1/notifications.py
 * بالباك-إند. كل المسارات خاصة بإشعارات المستخدم الحالي فقط (راجعي
 * notification_service.py قسم "استعلامات المستخدم على إشعاراته").
 */

export async function fetchNotifications(
  params: { unreadOnly?: boolean; limit?: number; offset?: number } = {},
): Promise<NotificationPage> {
  const { data } = await apiClient.get<NotificationPage>('/notifications', {
    params: { unread_only: params.unreadOnly, limit: params.limit, offset: params.offset },
  })
  return data
}

export async function fetchUnreadCount(): Promise<number> {
  const { data } = await apiClient.get<{ unread_count: number }>('/notifications/unread-count')
  return data.unread_count
}

export async function markNotificationRead(notificationId: string): Promise<Notification> {
  const { data } = await apiClient.patch<Notification>(`/notifications/${notificationId}/read`)
  return data
}

export async function markAllNotificationsRead(): Promise<void> {
  await apiClient.post('/notifications/read-all')
}
