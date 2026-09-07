import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bell } from 'lucide-react'
import {
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useNotifications,
} from '@/hooks/useNotifications'
import {
  ENTITY_TYPE_LABELS,
  notificationIcon,
  notificationLinkPath,
  notificationToneBorderClass,
  notificationToneTextClass,
} from '@/lib/notificationDisplay'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { CardSkeleton } from '@/components/ui/Skeleton'
import { cn, formatRelativeTime, relativeDayGroupLabel } from '@/lib/utils'
import type { Notification, NotificationEntityType } from '@/types'

const DAY_ORDER = ['اليوم', 'أمس', 'الأسبوع الماضي', 'أقدم']
const PAGE_LIMIT = 100

/**
 * صفحة "الإشعارات" الكاملة — تصميم معتمد من صاحبة المشروع (2026-09-07،
 * النسخة الثالثة من التصميم المقترح): نمط "صندوق بريد" (Bold لغير
 * المقروء بدل تلوين خلفية كامل، خط جانبي رفيع بلون نوع الحدث)، مع عمود
 * فلترة حسب الوحدة (مهام/طلبات لجان/قرارات/اجتماعات) وتجميع بالوقت
 * النسبي (اليوم/أمس/الأسبوع الماضي/أقدم). الفلترة والتجميع كلاهما من
 * جانب العميل فوق أول PAGE_LIMIT إشعار المحمَّلة (حجم كافٍ عمليًا لحجم
 * إشعارات مستخدم واحد — بدون تعقيد صفحات متعددة بهذه المرحلة).
 */
export function NotificationsPage() {
  const navigate = useNavigate()
  const [tab, setTab] = useState<'all' | 'unread'>('all')
  const [entityFilter, setEntityFilter] = useState<NotificationEntityType | 'all'>('all')

  const { data: page, isLoading, isError, refetch } = useNotifications(tab === 'unread', PAGE_LIMIT)
  const markRead = useMarkNotificationRead()
  const markAllRead = useMarkAllNotificationsRead()

  const items = page?.items ?? []

  const entityCounts = useMemo(() => {
    const counts: Partial<Record<NotificationEntityType, number>> = {}
    for (const n of items) {
      if (!n.related_entity_type) continue
      counts[n.related_entity_type] = (counts[n.related_entity_type] ?? 0) + 1
    }
    return counts
  }, [items])

  const filtered = useMemo(() => {
    if (entityFilter === 'all') return items
    return items.filter((n) => n.related_entity_type === entityFilter)
  }, [items, entityFilter])

  const grouped = useMemo(() => {
    const groups = new Map<string, Notification[]>()
    for (const n of filtered) {
      const key = relativeDayGroupLabel(n.created_at)
      if (!groups.has(key)) groups.set(key, [])
      groups.get(key)!.push(n)
    }
    return DAY_ORDER.map((label) => [label, groups.get(label) ?? []] as const).filter(
      ([, list]) => list.length > 0,
    )
  }, [filtered])

  function handleItemClick(notification: Notification) {
    if (!notification.is_read) markRead.mutate(notification.notification_id)
    const path = notificationLinkPath(notification)
    if (path) navigate(path)
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <h1 className="text-xl font-bold text-text-primary">الإشعارات</h1>
          <p className="mt-1 text-sm text-text-muted">
            {page ? (
              <>
                <span className="font-semibold text-brand-primary">
                  {items.filter((n) => !n.is_read).length}
                </span>{' '}
                غير مقروءة من أصل {page.total}
              </>
            ) : (
              'إشعاراتك بكل وحدات النظام في مكان واحد'
            )}
          </p>
        </div>
        {!!items.some((n) => !n.is_read) && (
          <button
            onClick={() => markAllRead.mutate()}
            disabled={markAllRead.isPending}
            className="rounded-sm border border-border-default bg-bg-surface px-3.5 py-2 text-xs font-semibold text-text-secondary transition-colors hover:bg-bg-elevated disabled:opacity-50"
          >
            تعليم الكل كمقروء
          </button>
        )}
      </div>

      {isLoading ? (
        <div className="flex flex-col gap-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <CardSkeleton key={i} />
          ))}
        </div>
      ) : isError ? (
        <ErrorState onRetry={() => refetch()} />
      ) : (
        <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-[1fr_13rem]">
          <div className="overflow-hidden rounded-sm border border-border-default bg-bg-surface">
            <div className="flex items-center gap-1 border-b border-border-default p-2">
              <button
                onClick={() => setTab('all')}
                className={cn(
                  'rounded-sm px-3.5 py-1.5 text-xs font-semibold transition-colors',
                  tab === 'all' ? 'bg-info-bg text-info' : 'text-text-muted hover:text-text-primary',
                )}
              >
                الكل
              </button>
              <button
                onClick={() => setTab('unread')}
                className={cn(
                  'rounded-sm px-3.5 py-1.5 text-xs font-semibold transition-colors',
                  tab === 'unread' ? 'bg-info-bg text-info' : 'text-text-muted hover:text-text-primary',
                )}
              >
                غير مقروءة
              </button>
            </div>

            {filtered.length === 0 ? (
              <EmptyState
                icon={<Bell size={26} />}
                title={tab === 'unread' ? 'لا توجد إشعارات غير مقروءة' : 'لا توجد إشعارات بعد'}
                description="ستظهر هنا إشعاراتك عند حدوث أي تحديث يخصّك"
              />
            ) : (
              grouped.map(([label, list]) => (
                <div key={label}>
                  <p className="bg-bg-app px-4 py-2 text-[11px] font-bold text-text-muted">{label}</p>
                  {list.map((notification) => {
                    const Icon = notificationIcon(notification)
                    return (
                      <button
                        key={notification.notification_id}
                        onClick={() => handleItemClick(notification)}
                        className={cn(
                          'flex w-full items-start gap-3.5 border-b border-border-default px-4 py-3.5 text-right transition-colors last:border-b-0 hover:bg-bg-app',
                          !notification.is_read && 'border-r-2 bg-bg-app',
                          !notification.is_read && notificationToneBorderClass(notification.event_type),
                        )}
                      >
                        <span
                          className={cn(
                            'mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-sm border border-border-default bg-bg-surface',
                            notificationToneTextClass(notification.event_type),
                          )}
                        >
                          <Icon size={14} />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="flex items-baseline justify-between gap-2">
                            <span
                              className={cn(
                                'text-sm text-text-primary',
                                !notification.is_read && 'font-bold',
                              )}
                            >
                              {notification.title}
                            </span>
                            <span className="shrink-0 text-[11px] text-text-muted">
                              {formatRelativeTime(notification.created_at)}
                            </span>
                          </span>
                          {notification.body && (
                            <span className="mt-1 block text-xs leading-relaxed text-text-secondary">
                              {notification.body}
                            </span>
                          )}
                          {notification.related_entity_type && (
                            <span
                              className={cn(
                                'mt-1.5 block text-[11px] font-semibold',
                                notificationToneTextClass(notification.event_type),
                              )}
                            >
                              {ENTITY_TYPE_LABELS[notification.related_entity_type]}
                            </span>
                          )}
                        </span>
                      </button>
                    )
                  })}
                </div>
              ))
            )}
          </div>

          <div className="overflow-hidden rounded-sm border border-border-default bg-bg-surface">
            <button
              onClick={() => setEntityFilter('all')}
              className={cn(
                'flex w-full items-center justify-between gap-2 border-b border-border-default px-3.5 py-2.5 text-xs transition-colors last:border-b-0',
                entityFilter === 'all'
                  ? 'border-r-2 border-r-brand-primary bg-bg-app font-bold text-text-primary'
                  : 'text-text-secondary hover:bg-bg-app',
              )}
            >
              <span>الكل</span>
              <span className="text-[11px] text-text-muted">{items.length}</span>
            </button>
            {(Object.keys(ENTITY_TYPE_LABELS) as NotificationEntityType[])
              .filter((type) => entityCounts[type])
              .map((type) => (
                <button
                  key={type}
                  onClick={() => setEntityFilter(type)}
                  className={cn(
                    'flex w-full items-center justify-between gap-2 border-b border-border-default px-3.5 py-2.5 text-xs transition-colors last:border-b-0',
                    entityFilter === type
                      ? 'border-r-2 border-r-brand-primary bg-bg-app font-bold text-text-primary'
                      : 'text-text-secondary hover:bg-bg-app',
                  )}
                >
                  <span>{ENTITY_TYPE_LABELS[type]}</span>
                  <span className="text-[11px] text-text-muted">{entityCounts[type]}</span>
                </button>
              ))}
          </div>
        </div>
      )}
    </div>
  )
}
