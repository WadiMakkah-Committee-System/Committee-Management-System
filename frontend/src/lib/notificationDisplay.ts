import {
  CalendarDays,
  ClipboardList,
  Gavel,
  ListChecks,
  Users2,
  type LucideIcon,
} from 'lucide-react'
import type { Notification, NotificationEntityType } from '@/types'

/**
 * تمثيل العرض الموحَّد لأنواع/أحداث الإشعارات — يُستخدم بجرس الإشعارات
 * (Topbar) وصفحة "الإشعارات" الكاملة معًا، حتى لا يتكرر نفس التصنيف
 * بمكانين. الألوان (tone) نفس نظام شارات الحالة المستخدم بباقي المنصة
 * (info/success/warning/danger/neutral، راجعي index.css @theme) — بمعنى
 * دلالي (نتيجة الحدث)، وليس بمعنى بصري بحت.
 */

export const ENTITY_TYPE_LABELS: Record<NotificationEntityType, string> = {
  task: 'مهام',
  committee_request: 'طلبات اللجان',
  committee: 'اللجان',
  decision: 'القرارات',
  meeting: 'الاجتماعات',
}

export const ENTITY_TYPE_ICONS: Record<NotificationEntityType, LucideIcon> = {
  task: ListChecks,
  committee_request: ClipboardList,
  committee: Users2,
  decision: Gavel,
  meeting: CalendarDays,
}

export type NotificationTone = 'info' | 'success' | 'warning' | 'danger' | 'neutral'

/** لون كل event_type حسب طبيعته الدلالية — راجعي notify_* بـnotification_service.py لقائمة القيم الكاملة. */
const EVENT_TONE: Record<string, NotificationTone> = {
  task_created: 'info',
  task_reassigned: 'info',
  task_status_changed: 'info',
  committee_request_submitted: 'warning',
  committee_request_returned_to_admin: 'warning',
  committee_request_returned_to_office: 'warning',
  committee_request_escalated: 'warning',
  committee_request_approved: 'success',
  committee_request_rejected: 'danger',
  decision_created: 'info',
  decision_voting_opened: 'info',
  decision_approved: 'success',
  decision_rejected: 'danger',
  meeting_created: 'info',
  meeting_updated: 'info',
  meeting_cancelled: 'danger',
}

export function notificationTone(eventType: string): NotificationTone {
  return EVENT_TONE[eventType] ?? 'neutral'
}

export function notificationIcon(notification: Pick<Notification, 'related_entity_type'>): LucideIcon {
  return notification.related_entity_type ? ENTITY_TYPE_ICONS[notification.related_entity_type] : ListChecks
}

const TONE_TEXT_CLASSES: Record<NotificationTone, string> = {
  info: 'text-info',
  success: 'text-success',
  warning: 'text-warning',
  danger: 'text-danger',
  neutral: 'text-neutral',
}

const TONE_BORDER_R_CLASSES: Record<NotificationTone, string> = {
  info: 'border-r-info',
  success: 'border-r-success',
  warning: 'border-r-warning',
  danger: 'border-r-danger',
  neutral: 'border-r-neutral',
}

export function notificationToneTextClass(eventType: string): string {
  return TONE_TEXT_CLASSES[notificationTone(eventType)]
}

export function notificationToneBorderClass(eventType: string): string {
  return TONE_BORDER_R_CLASSES[notificationTone(eventType)]
}

/** المسار الذي يفتحه النقر على إشعار — null يعني عدم وجود صفحة تفاصيل يُنتقَل إليها. */
export function notificationLinkPath(notification: Notification): string | null {
  if (!notification.related_entity_id) return null
  switch (notification.related_entity_type) {
    case 'task':
      return `/tasks/${notification.related_entity_id}`
    case 'committee_request':
      return `/committees/requests/${notification.related_entity_id}`
    case 'committee':
      return `/committees/approved/${notification.related_entity_id}`
    case 'decision':
      return `/decisions/${notification.related_entity_id}`
    case 'meeting':
      return `/meetings/${notification.related_entity_id}`
    default:
      return null
  }
}
