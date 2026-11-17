import type { ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { ChevronLeft, ChevronRight, UserRound } from 'lucide-react'
import { Avatar } from '@/components/ui/Avatar'
import { Button } from '@/components/ui/Button'
import { cn, formatRelativeTime } from '@/lib/utils'
import { TicketNumber, TicketPriorityBadge, TicketStatusBadge } from './TicketBadges'
import { TICKET_MODULE_LABELS, TICKET_TYPE_LABELS, ticketStatusTone } from './ticketLabels'
import type { Ticket } from '@/types/tickets'

interface TicketListRowProps {
  ticket: Ticket
  /** مسار صفحة التفاصيل (يختلف بين "تذاكري" وقائمة الدعم). */
  to: string
  /** عرض الدعم: مقدّم الطلب والأولوية والمسند إليه. */
  supportView?: boolean
  /** زر سريع بنهاية الصف (مثل "استلام") — النقر عليه ما يفتح التذكرة. */
  action?: ReactNode
}

/**
 * الهدف: صف تذكرة واحد بالقوائم (TKT-FR-002 وTKT-FR-010).
 *
 * المسؤولية: الرقم والعنوان والنوع والوحدة والحالة وآخر تحديث؛ وللدعم
 * إضافةً: مقدّم الطلب والأولوية والمسند إليه. الصف كامل قابل للنقر (وبلوحة
 * المفاتيح Enter/Space) ويفتح التذكرة.
 *
 * "آخر تحديث" لمقدّم الطلب = آخر نشاط عام (الباك-إند يرجعه كذا)، فما ينكشف
 * له نشاط داخلي للدعم.
 */
export function TicketListRow({ ticket, to, supportView, action }: TicketListRowProps) {
  const navigate = useNavigate()
  const location = useLocation()
  // الرابط الحالي (بفلاتره) يُمرَّر للتفاصيل، فزر الرجوع هناك يرجّع نفس العرض.
  const open = () => navigate(to, { state: { from: location.pathname + location.search } })
  const tone = ticketStatusTone(ticket.status, ticket.viewer)
  const assigneeLeft = supportView && ticket.assignee && ticket.assignee_is_active_support === false

  return (
    <div
      role="link"
      tabIndex={0}
      onClick={open}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          open()
        }
      }}
      className="flex cursor-pointer flex-col gap-3 border-r-[3px] px-4 py-3.5 transition-colors hover:bg-table-hover-bg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand-accent lg:flex-row lg:items-center lg:gap-4"
      style={{ borderRightColor: `color-mix(in srgb, var(--status-${tone === 'danger' ? 'error' : tone}-main) 55%, transparent)` }}
    >
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <TicketNumber value={ticket.ticket_number} />
          <p className="min-w-0 truncate text-sm font-semibold text-text-primary">{ticket.title}</p>
        </div>
        <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-text-muted">
          <span>{TICKET_TYPE_LABELS[ticket.ticket_type]}</span>
          <span aria-hidden>·</span>
          <span>{TICKET_MODULE_LABELS[ticket.module]}</span>
          {supportView && (
            <>
              <span aria-hidden>·</span>
              <span className="flex items-center gap-1">
                <UserRound size={12} />
                {ticket.requester.first_name} {ticket.requester.last_name}
              </span>
            </>
          )}
        </p>
      </div>

      {supportView && (
        <div className="flex shrink-0 items-center gap-2 lg:w-40">
          {ticket.assignee ? (
            <>
              <Avatar firstName={ticket.assignee.first_name} lastName={ticket.assignee.last_name} size={24} />
              <span className={cn('truncate text-xs font-medium', assigneeLeft ? 'text-text-muted line-through' : 'text-text-secondary')}>
                {ticket.assignee.first_name} {ticket.assignee.last_name}
              </span>
            </>
          ) : (
            <span className="text-xs text-text-muted">غير مسندة</span>
          )}
        </div>
      )}

      <div className="flex shrink-0 flex-wrap items-center gap-2 lg:w-auto">
        {supportView && ticket.priority && <TicketPriorityBadge priority={ticket.priority} />}
        <TicketStatusBadge status={ticket.status} viewer={ticket.viewer} />
        <span className="text-xs text-text-muted lg:w-24" title={ticket.updated_at}>
          {formatRelativeTime(ticket.updated_at)}
        </span>
        {action && (
          <div onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
            {action}
          </div>
        )}
      </div>
    </div>
  )
}

/**
 * الهدف: تنقّل بين صفحات القائمة (limit/offset من الباك-إند).
 * المدخلات: total وlimit وoffset، وonChange(offsetالجديد). لا يُعرض لو صفحة واحدة.
 */
export function TicketPager({
  total,
  limit,
  offset,
  onChange,
  loading,
}: {
  total: number
  limit: number
  offset: number
  onChange: (offset: number) => void
  loading?: boolean
}) {
  if (total <= limit) return null
  const from = offset + 1
  const to = Math.min(offset + limit, total)
  return (
    <div className="flex items-center justify-between gap-3 border-t border-border-default px-4 py-3">
      <p className="text-xs text-text-muted">
        عرض {from}–{to} من {total}
      </p>
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          variant="secondary"
          icon={<ChevronRight size={14} />}
          disabled={offset === 0 || loading}
          onClick={() => onChange(Math.max(0, offset - limit))}
        >
          السابق
        </Button>
        <Button
          size="sm"
          variant="secondary"
          disabled={to >= total || loading}
          onClick={() => onChange(offset + limit)}
        >
          التالي
          <ChevronLeft size={14} />
        </Button>
      </div>
    </div>
  )
}
