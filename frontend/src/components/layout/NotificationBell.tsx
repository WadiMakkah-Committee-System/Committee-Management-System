import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { Bell } from 'lucide-react'
import {
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useNotifications,
  useUnreadCount,
} from '@/hooks/useNotifications'
import { notificationIcon, notificationLinkPath, notificationToneBorderClass } from '@/lib/notificationDisplay'
import { useToast } from '@/components/ui/Toast'
import { cn, formatRelativeTime } from '@/lib/utils'
import type { Notification } from '@/types'

const DROPDOWN_PREVIEW_LIMIT = 6

/**
 * جرس الإشعارات بالـTopbar — تصميم معتمد من صاحبة المشروع (2026-09-07،
 * النسخة الثالثة من التصميم المقترح): بدون تدرّجات أو دوائر ملوّنة، شارة
 * نقطة بسيطة فقط عند وجود غير مقروء، وقائمة منسدلة بنمط "صندوق بريد"
 * (عنوان الإشعار غير المقروء Bold، خط جانبي رفيع بلون نوع الحدث).
 *
 * تحديث 2026-09-07 (طلب صاحبة المشروع: "لما يجي إشعار جديد ينهز الجرس
 * وتجيني رسالة 'إشعارات جديدة'"): useUnreadCount أصلًا يستطلع كل 30
 * ثانية (راجعي useNotifications.ts) — نقارن هنا كل قراءة بالقراءة
 * السابقة؛ لو زاد العدد (وليس أول تحميل للصفحة، ولا نقصانًا بعد
 * "تعليم الكل كمقروء")، نشغّل اهتزاز قصير على الجرس (framer-motion) +
 * توست "إشعارات جديدة". لا صوت — لم يُطلَب صراحة، ونتجنّب تشغيل صوت
 * تلقائي بدون إذن المستخدم (قيود المتصفحات أصلًا تمنعه غالبًا بدون
 * تفاعل مسبق من المستخدم بالصفحة).
 */
export function NotificationBell() {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const { showToast } = useToast()

  const { data: unreadCount } = useUnreadCount()
  const { data: page } = useNotifications(false, DROPDOWN_PREVIEW_LIMIT)
  const markRead = useMarkNotificationRead()
  const markAllRead = useMarkAllNotificationsRead()

  const previousUnreadCount = useRef<number | null>(null)
  const [shake, setShake] = useState(false)

  useEffect(() => {
    if (unreadCount === undefined) return
    const previous = previousUnreadCount.current
    // previous === null يعني أول قراءة (تحميل الصفحة) — لا نهزّ الجرس
    // عندها، فقط عند زيادة فعلية عن قراءة سابقة أثناء بقاء المستخدم بالصفحة.
    if (previous !== null && unreadCount > previous) {
      setShake(true)
      showToast('إشعارات جديدة', 'info')
    }
    previousUnreadCount.current = unreadCount
  }, [unreadCount, showToast])

  useEffect(() => {
    if (!open) return
    const onClickOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [open])

  function handleItemClick(notification: Notification) {
    setOpen(false)
    if (!notification.is_read) markRead.mutate(notification.notification_id)
    const path = notificationLinkPath(notification)
    if (path) navigate(path)
  }

  return (
    <div className="relative" ref={ref}>
      <motion.button
        onClick={() => setOpen((o) => !o)}
        aria-label="الإشعارات"
        animate={shake ? { rotate: [0, -14, 12, -10, 8, -4, 0] } : { rotate: 0 }}
        transition={{ duration: 0.55, ease: 'easeInOut' }}
        onAnimationComplete={() => setShake(false)}
        className="relative flex h-9 w-9 items-center justify-center rounded-sm text-text-secondary transition-colors hover:bg-bg-elevated hover:text-text-primary"
      >
        <Bell size={18} />
        {!!unreadCount && (
          <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full border-2 border-bg-surface bg-danger" />
        )}
      </motion.button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: -4 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: -4 }}
            transition={{ duration: 0.12 }}
            className="absolute left-0 top-full z-30 mt-2 w-[23rem] overflow-hidden rounded-sm border border-border-default bg-bg-elevated shadow-lg"
          >
            <div className="flex items-baseline justify-between px-4 py-3">
              <h3 className="text-sm font-bold text-text-primary">الإشعارات</h3>
              {!!unreadCount && (
                <button
                  onClick={() => markAllRead.mutate()}
                  disabled={markAllRead.isPending}
                  className="text-xs font-semibold text-brand-primary hover:underline disabled:opacity-50"
                >
                  تعليم الكل كمقروء
                </button>
              )}
            </div>

            <div className="max-h-96 overflow-y-auto border-t border-border-default">
              {!page || page.items.length === 0 ? (
                <p className="px-4 py-6 text-center text-xs text-text-muted">لا توجد إشعارات بعد</p>
              ) : (
                page.items.map((notification) => {
                  const Icon = notificationIcon(notification)
                  return (
                    <button
                      key={notification.notification_id}
                      onClick={() => handleItemClick(notification)}
                      className={cn(
                        'flex w-full items-start gap-2.5 border-b border-border-default px-4 py-3 text-right transition-colors last:border-b-0 hover:bg-bg-surface',
                        !notification.is_read && 'border-r-2 bg-bg-app',
                        !notification.is_read && notificationToneBorderClass(notification.event_type),
                      )}
                    >
                      <Icon size={13} className="mt-0.5 shrink-0 text-text-muted" />
                      <span className="min-w-0 flex-1">
                        <span
                          className={cn(
                            'block text-xs leading-snug text-text-primary',
                            !notification.is_read && 'font-bold',
                          )}
                        >
                          {notification.title}
                        </span>
                        <span className="mt-1 block text-[11px] text-text-muted">
                          {formatRelativeTime(notification.created_at)}
                        </span>
                      </span>
                    </button>
                  )
                })
              )}
            </div>

            <button
              onClick={() => {
                setOpen(false)
                navigate('/notifications')
              }}
              className="block w-full border-t border-border-default py-2.5 text-center text-xs font-semibold text-brand-primary hover:bg-bg-surface"
            >
              عرض كل الإشعارات
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
