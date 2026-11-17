import type { ReactNode } from 'react'
import { History, Repeat } from 'lucide-react'
import { Avatar } from '@/components/ui/Avatar'
import { Card } from '@/components/ui/Card'
import { Skeleton } from '@/components/ui/Skeleton'
import { useToast } from '@/components/ui/Toast'
import { useTicketHistory, useUpdateTicketFields } from '@/hooks/useTickets'
import { cn, extractErrorMessage, formatDateTime, formatRelativeTime } from '@/lib/utils'
import { TicketPriorityBadge, TicketStatusBadge } from './TicketBadges'
import {
  TICKET_MODULE_LABELS,
  TICKET_MODULE_OPTIONS,
  TICKET_PRIORITY_OPTIONS,
  TICKET_TYPE_LABELS,
  TICKET_TYPE_OPTIONS,
  ticketHistoryText,
} from './ticketLabels'
import type { Ticket, TicketFieldsUpdate, TicketModule, TicketPriority, TicketType } from '@/types/tickets'

/** سطر "اسم: قيمة" بلوحة التفاصيل. */
function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 py-2.5">
      <dt className="shrink-0 text-xs text-text-muted">{label}</dt>
      <dd className="min-w-0 text-end text-sm text-text-primary">{children}</dd>
    </div>
  )
}

/** قائمة اختيار مضغوطة داخل اللوحة (تعديل الحقل مباشرة). */
function InlineSelect({
  label,
  value,
  options,
  disabled,
  onChange,
}: {
  label: string
  value: string
  options: { value: string; label: string }[]
  disabled?: boolean
  onChange: (value: string) => void
}) {
  return (
    <select
      aria-label={label}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
      className="h-8 max-w-44 rounded-sm border border-border-default bg-bg-surface px-2 text-xs text-text-primary transition-colors focus:border-brand-primary focus:outline-none focus:ring-2 focus:ring-brand-accent/40 disabled:opacity-60"
    >
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  )
}

/** اسم شخص مع صورته المختصرة. */
function Person({ person, muted }: { person: { first_name: string; last_name: string }; muted?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2">
      <Avatar firstName={person.first_name} lastName={person.last_name} size={22} />
      <span className={cn('truncate', muted && 'text-text-muted line-through')}>
        {person.first_name} {person.last_name}
      </span>
    </span>
  )
}

/**
 * الهدف:
 * لوحة تفاصيل التذكرة بجانب المحادثة.
 *
 * المسؤولية:
 * - للطرفين: الحالة، النوع، الوحدة، مقدّم الطلب، المسؤول عنها، والتواريخ.
 * - للدعم: الأولوية وبريد مقدّم الطلب، وتعديل الأولوية والنوع والوحدة مباشرة
 *   لو يملك "إدارة التذكرة" (TKT-FR-016)، وزر "تغيير" للإسناد لو يملك "إسناد التذكرة".
 * - المسند إليه اللي خرج من الدعم يظهر مشطوبًا مع تنبيه (القسم 10).
 *
 * المدخلات: ticket، onAssign (فتح نافذة الإسناد).
 * الصلاحيات: الأزرار حسب ticket.actions من الباك-إند؛ الباك-إند يفحص كل تعديل.
 */
export function TicketDetailsPanel({ ticket, onAssign }: { ticket: Ticket; onAssign: () => void }) {
  const { showToast } = useToast()
  const updateMutation = useUpdateTicketFields()
  const isSupport = ticket.viewer === 'support'
  const canManage = ticket.actions.can_manage
  const assigneeLeft = isSupport && !!ticket.assignee && ticket.assignee_is_active_support === false

  function update(payload: TicketFieldsUpdate) {
    updateMutation.mutate(
      { ticketId: ticket.ticket_id, payload },
      {
        onSuccess: () => showToast('تم حفظ التعديل', 'success'),
        onError: (err) => showToast(extractErrorMessage(err), 'error'),
      },
    )
  }

  return (
    <Card className="p-0">
      <h2 className="border-b border-border-default px-4 py-3 text-sm font-semibold text-text-primary">تفاصيل التذكرة</h2>
      <dl className="divide-y divide-border-default px-4">
        <Row label="الحالة">
          <TicketStatusBadge status={ticket.status} viewer={ticket.viewer} />
        </Row>
        {isSupport && ticket.priority && (
          <Row label="الأولوية">
            {canManage ? (
              <InlineSelect
                label="الأولوية"
                value={ticket.priority}
                options={TICKET_PRIORITY_OPTIONS}
                disabled={updateMutation.isPending}
                onChange={(value) => update({ priority: value as TicketPriority })}
              />
            ) : (
              <TicketPriorityBadge priority={ticket.priority} />
            )}
          </Row>
        )}
        <Row label="النوع">
          {canManage ? (
            <InlineSelect
              label="النوع"
              value={ticket.ticket_type}
              options={TICKET_TYPE_OPTIONS}
              disabled={updateMutation.isPending}
              onChange={(value) => update({ ticket_type: value as TicketType })}
            />
          ) : (
            TICKET_TYPE_LABELS[ticket.ticket_type]
          )}
        </Row>
        <Row label="الوحدة المتأثرة">
          {canManage ? (
            <InlineSelect
              label="الوحدة المتأثرة"
              value={ticket.module}
              options={TICKET_MODULE_OPTIONS}
              disabled={updateMutation.isPending}
              onChange={(value) => update({ module: value as TicketModule })}
            />
          ) : (
            TICKET_MODULE_LABELS[ticket.module]
          )}
        </Row>
        <Row label="مقدّم الطلب">
          <span className="flex flex-col items-end gap-0.5">
            <Person person={ticket.requester} />
            {isSupport && ticket.requester.email && (
              <a href={`mailto:${ticket.requester.email}`} dir="ltr" className="text-xs text-brand-primary hover:underline">
                {ticket.requester.email}
              </a>
            )}
          </span>
        </Row>
        <Row label={isSupport ? 'المسند إليه' : 'المسؤول عنها'}>
          <span className="flex flex-col items-end gap-1">
            {ticket.assignee ? (
              <Person person={ticket.assignee} muted={assigneeLeft} />
            ) : (
              <span className="text-text-muted">{isSupport ? 'غير مسندة' : 'لم تُستلم بعد'}</span>
            )}
            {assigneeLeft && <span className="text-xs text-warning">لم يعد ضمن الدعم الفني</span>}
            {ticket.actions.can_assign && (
              <button
                type="button"
                onClick={onAssign}
                className="flex items-center gap-1 text-xs font-semibold text-brand-primary hover:underline"
              >
                <Repeat size={12} />
                {ticket.assignee ? 'تغيير' : 'إسناد'}
              </button>
            )}
          </span>
        </Row>
        <Row label="تاريخ الإرسال">{formatDateTime(ticket.created_at)}</Row>
        <Row label="آخر تحديث">
          <span title={formatDateTime(ticket.updated_at)}>{formatRelativeTime(ticket.updated_at)}</span>
        </Row>
        {ticket.resolved_at && <Row label="تاريخ الحل">{formatDateTime(ticket.resolved_at)}</Row>}
        {ticket.closed_at && <Row label="تاريخ الإغلاق">{formatDateTime(ticket.closed_at)}</Row>}
        {ticket.cancelled_at && <Row label="تاريخ الإلغاء">{formatDateTime(ticket.cancelled_at)}</Row>}
      </dl>
      {ticket.status === 'resolved' && (
        <p className="border-t border-border-default px-4 py-3 text-xs text-text-muted">
          تُغلق تلقائيًا بعد ٤ أيام من الحل إذا ما رد مقدّم الطلب.
        </p>
      )}
    </Card>
  )
}

/**
 * الهدف: سجل التذكرة للدعم (TKT-FR-017) — من غيّر الحالة أو الإسناد أو الأولوية
 * أو النوع أو الوحدة، ومتى. العمليات التلقائية (الإغلاق بالمجدول) بدون فاعل.
 * المدخلات: ticketId. يُجلب فقط للدعم (الباك-إند يرفضه لغيرهم).
 */
export function TicketHistoryCard({ ticketId }: { ticketId: string }) {
  const { data, isLoading, isError, refetch } = useTicketHistory(ticketId, true)
  const entries = data ? [...data].reverse() : []

  return (
    <Card className="p-0">
      <h2 className="flex items-center gap-2 border-b border-border-default px-4 py-3 text-sm font-semibold text-text-primary">
        <History size={15} />
        سجل التذكرة
      </h2>
      {isLoading ? (
        <div className="flex flex-col gap-3 p-4">
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-4 w-2/3" />
        </div>
      ) : isError ? (
        <div className="px-4 py-4 text-center text-xs text-text-muted">
          تعذّر تحميل السجل.{' '}
          <button type="button" onClick={() => refetch()} className="font-semibold text-brand-primary hover:underline">
            إعادة المحاولة
          </button>
        </div>
      ) : entries.length === 0 ? (
        <p className="px-4 py-4 text-center text-xs text-text-muted">لا توجد أحداث بعد</p>
      ) : (
        <ol className="flex max-h-80 flex-col gap-3 overflow-y-auto p-4">
          {entries.map((entry, index) => (
            <li key={`${entry.event}-${entry.created_at}-${index}`} className="relative flex gap-2.5">
              <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-brand-primary/60" aria-hidden />
              <div className="min-w-0">
                <p className="text-xs text-text-primary">
                  <span className="font-semibold">
                    {entry.actor ? `${entry.actor.first_name} ${entry.actor.last_name}` : 'النظام'}
                  </span>{' '}
                  {ticketHistoryText(entry)}
                </p>
                <time className="text-[11px] text-text-muted" dateTime={entry.created_at} title={formatDateTime(entry.created_at)}>
                  {formatRelativeTime(entry.created_at)}
                </time>
              </div>
            </li>
          ))}
        </ol>
      )}
    </Card>
  )
}
