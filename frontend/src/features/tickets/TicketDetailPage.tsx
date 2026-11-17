import { useMemo, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { isAxiosError } from 'axios'
import { motion } from 'framer-motion'
import {
  ArrowRight,
  Ban,
  CheckCircle2,
  Hand,
  Lock,
  Plus,
  Repeat,
  SearchX,
  ShieldAlert,
  WifiOff,
  XCircle,
} from 'lucide-react'
import { ActionMenu, type ActionMenuItem } from '@/components/ui/ActionMenu'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { Skeleton } from '@/components/ui/Skeleton'
import { useToast } from '@/components/ui/Toast'
import { useCancelTicket, useChangeTicketStatus, useClaimTicket, useTicket, useTicketMessages } from '@/hooks/useTickets'
import { useTicketRealtime } from '@/hooks/useTicketRealtime'
import { extractErrorMessage } from '@/lib/utils'
import { useAuthStore } from '@/store/authStore'
import { AssignTicketModal } from './AssignTicketModal'
import { NewTicketModal } from './NewTicketModal'
import { TicketComposer } from './TicketComposer'
import { TicketConversation } from './TicketConversation'
import { TicketDetailsPanel, TicketHistoryCard } from './TicketDetailsPanel'
import { TicketNumber, TicketPriorityBadge, TicketStatusBadge } from './TicketBadges'
import { MANUAL_STATUS_TRANSITIONS, STATUS_ACTION_LABELS, ticketStatusTone } from './ticketLabels'
import { useTicketOutbox } from './useTicketOutbox'
import type { Ticket, TicketSupportSettableStatus } from '@/types/tickets'

/** رمز حالة HTTP من خطأ الطلب (لتمييز 404 و403 عن أخطاء الشبكة). */
function httpStatus(error: unknown): number | undefined {
  return isAxiosError(error) ? error.response?.status : undefined
}

/**
 * الهدف:
 * صفحة التذكرة للطرفين (TKT-FR-003 وTKT-FR-004 وTKT-FR-011 إلى TKT-FR-017 وTKT-FR-024).
 *
 * المسؤولية:
 * - الترويسة: الرقم والعنوان والحالة، وإجراءات المشاهد:
 *   مقدّم الطلب ← إلغاء (وهي "جديدة")؛ الدعم ← استلام، تم الحل، إعادة الإسناد،
 *   وباقي الانتقالات اليدوية المسموحة.
 * - المحادثة (عرض فقط) وصندوق الرد منفصلين، والإرسال متفائل عبر useTicketOutbox.
 * - التحديث اللحظي عبر useTicketRealtime (استقبال فقط).
 * - لوحة التفاصيل، وسجل التذكرة للدعم.
 * - التذكرة المغلقة/الملغاة للقراءة فقط بدون صندوق رد (القسم 10).
 *
 * الصلاحيات: صفة المشاهد (requester/support) والأزرار المتاحة كلها من الباك-إند
 * (ticket.viewer وticket.actions) — الواجهة ما تعيد حساب قواعد العمل.
 * الأخطاء: 404 (تذكرة غير موجودة أو لمستخدم آخر — ما ينكشف الفرق)، 403 (بدون
 * صلاحية)، وغيرها مع إعادة المحاولة.
 */
export function TicketDetailPage() {
  const { ticketId } = useParams<{ ticketId: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const { showToast } = useToast()
  const user = useAuthStore((s) => s.user)

  const ticketQuery = useTicket(ticketId)
  const messagesQuery = useTicketMessages(ticketId)
  const connection = useTicketRealtime(ticketId)
  const outbox = useTicketOutbox(ticketId ?? '')

  const cancelMutation = useCancelTicket()
  const claimMutation = useClaimTicket()
  const statusMutation = useChangeTicketStatus()

  const [assignOpen, setAssignOpen] = useState(false)
  const [cancelOpen, setCancelOpen] = useState(false)
  const [cancelError, setCancelError] = useState<string | null>(null)
  const [resolveOpen, setResolveOpen] = useState(false)
  const [newTicketOpen, setNewTicketOpen] = useState(false)

  const currentUser = useMemo(
    () => ({
      user_id: user?.user_id ?? '',
      first_name: user?.first_name ?? '',
      last_name: user?.last_name ?? '',
    }),
    [user?.user_id, user?.first_name, user?.last_name],
  )

  const ticket = ticketQuery.data
  const fromList = (location.state as { from?: string } | null)?.from
  const backTo = fromList ?? (ticket?.viewer === 'support' ? '/support/tickets' : '/tickets')

  if (ticketQuery.isLoading) return <DetailSkeleton />

  if (ticketQuery.isError || !ticket) {
    const status = httpStatus(ticketQuery.error)
    if (status === 404) {
      return (
        <EmptyState
          icon={<SearchX size={26} />}
          title="التذكرة غير موجودة"
          description="ممكن الرابط غير صحيح، أو ما عندك وصول لهذه التذكرة"
          action={
            <Button size="sm" variant="secondary" onClick={() => navigate(backTo)}>
              الرجوع للتذاكر
            </Button>
          }
        />
      )
    }
    if (status === 403) {
      return (
        <EmptyState
          icon={<ShieldAlert size={26} />}
          title="ليس لديك صلاحية"
          description={extractErrorMessage(ticketQuery.error)}
          action={
            <Button size="sm" variant="secondary" onClick={() => navigate('/dashboard')}>
              لوحة التحكم
            </Button>
          }
        />
      )
    }
    return <ErrorState onRetry={() => ticketQuery.refetch()} />
  }

  const isSupport = ticket.viewer === 'support'
  const { actions } = ticket
  const claimable = actions.can_assign && (!ticket.assignee || ticket.assignee_is_active_support === false)
  const manualTargets = actions.can_manage ? MANUAL_STATUS_TRANSITIONS[ticket.status] : []
  const canResolve = manualTargets.includes('resolved')
  const otherTargets = manualTargets.filter((s) => s !== 'resolved')
  const tone = ticketStatusTone(ticket.status, ticket.viewer)

  function changeStatus(status: TicketSupportSettableStatus) {
    if (!ticket) return
    statusMutation.mutate(
      { ticketId: ticket.ticket_id, status },
      {
        onSuccess: () => showToast('تم تحديث حالة التذكرة', 'success'),
        onError: (err) => showToast(extractErrorMessage(err), 'error'),
      },
    )
  }

  function claim(target: Ticket) {
    claimMutation.mutate(target.ticket_id, {
      onSuccess: () => showToast('استلمت التذكرة', 'success'),
      onError: (err) => {
        showToast(extractErrorMessage(err), 'error')
        void ticketQuery.refetch()
      },
    })
  }

  const menuItems: ActionMenuItem[] = [
    ...(actions.can_assign
      ? [
          {
            label: ticket.assignee ? 'إعادة الإسناد' : 'إسناد لعضو',
            icon: <Repeat size={14} />,
            onClick: () => setAssignOpen(true),
          },
        ]
      : []),
    ...otherTargets.map((status) => ({
      label: STATUS_ACTION_LABELS[status],
      icon: <CheckCircle2 size={14} />,
      onClick: () => changeStatus(status),
      disabled: statusMutation.isPending,
    })),
  ]

  return (
    <motion.div
      initial={{ opacity: 0, x: 14 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.25, ease: 'easeOut' }}
      className="flex flex-col gap-6"
    >
      <Card className="relative p-0">
        <span
          aria-hidden
          className="absolute inset-y-0 right-0 w-1 rounded-tr-md rounded-br-md"
          style={{ backgroundColor: `var(--status-${tone === 'danger' ? 'error' : tone}-main)` }}
        />
        <div className="flex flex-col gap-4 px-5 py-4 pr-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <button
              type="button"
              onClick={() => navigate(backTo)}
              className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-sm text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
              aria-label="الرجوع للتذاكر"
            >
              <ArrowRight size={18} />
            </button>
            <div className="min-w-0">
              <TicketNumber value={ticket.ticket_number} />
              <h1 className="mt-0.5 break-words text-xl font-bold tracking-tight text-text-primary sm:text-[1.5rem] sm:leading-tight">
                {ticket.title}
              </h1>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <TicketStatusBadge status={ticket.status} viewer={ticket.viewer} />
                {isSupport && ticket.priority && <TicketPriorityBadge priority={ticket.priority} />}
                {connection === 'closed' && (
                  <span className="inline-flex items-center gap-1 rounded-xs bg-neutral-bg px-2 py-1 text-xs text-text-muted">
                    <WifiOff size={12} />
                    التحديث اللحظي متوقف — يعاد الاتصال تلقائيًا
                  </span>
                )}
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {claimable && (
              <Button
                size="sm"
                icon={<Hand size={14} />}
                loading={claimMutation.isPending}
                onClick={() => claim(ticket)}
              >
                استلام
              </Button>
            )}
            {canResolve && (
              <Button
                size="sm"
                variant="secondary"
                icon={<CheckCircle2 size={14} />}
                disabled={statusMutation.isPending}
                onClick={() => setResolveOpen(true)}
              >
                تم الحل
              </Button>
            )}
            {actions.can_cancel && (
              <Button
                size="sm"
                variant="ghost"
                className="text-danger hover:bg-danger-bg hover:text-danger"
                icon={<XCircle size={14} />}
                onClick={() => {
                  setCancelError(null)
                  setCancelOpen(true)
                }}
              >
                إلغاء التذكرة
              </Button>
            )}
            {menuItems.length > 0 && <ActionMenu items={menuItems} />}
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="flex min-w-0 flex-col gap-4">
          {messagesQuery.isLoading ? (
            <div className="flex flex-col gap-4">
              <Skeleton className="h-28 w-full rounded-md" />
              <Skeleton className="h-16 w-2/3 rounded-md" />
            </div>
          ) : messagesQuery.isError ? (
            <ErrorState title="تعذّر تحميل المحادثة" onRetry={() => messagesQuery.refetch()} />
          ) : (
            <TicketConversation
              ticketId={ticket.ticket_id}
              messages={messagesQuery.data ?? []}
              outbox={outbox.entries}
              currentUser={currentUser}
              viewer={ticket.viewer}
              onRetry={outbox.retry}
              onDiscard={outbox.discard}
            />
          )}

          {actions.can_reply || actions.can_add_internal_note ? (
            <TicketComposer ticket={ticket} onSend={(message) => void outbox.send(message)} />
          ) : (
            <ReadOnlyNotice ticket={ticket} onNewTicket={() => setNewTicketOpen(true)} />
          )}
        </div>

        <aside className="flex flex-col gap-4">
          <TicketDetailsPanel ticket={ticket} onAssign={() => setAssignOpen(true)} />
          {isSupport && <TicketHistoryCard ticketId={ticket.ticket_id} />}
        </aside>
      </div>

      {actions.can_assign && (
        <AssignTicketModal
          open={assignOpen}
          onClose={() => setAssignOpen(false)}
          ticket={ticket}
          currentUserId={currentUser.user_id}
        />
      )}

      <ConfirmDialog
        open={resolveOpen}
        onClose={() => setResolveOpen(false)}
        onConfirm={() => {
          setResolveOpen(false)
          changeStatus('resolved')
        }}
        variant="primary"
        title="تحديد التذكرة كمحلولة"
        description="يوصل مقدّم الطلب إشعار بالحل، وتُغلق التذكرة تلقائيًا بعد ٤ أيام إذا ما رد. لو تبي تشرح الحل، اكتب رد واختر «تم الحل» بدل هذا الزر."
        confirmLabel="تم الحل"
        loading={statusMutation.isPending}
      />

      <ConfirmDialog
        open={cancelOpen}
        onClose={() => setCancelOpen(false)}
        onConfirm={() =>
          cancelMutation.mutate(ticket.ticket_id, {
            onSuccess: () => {
              setCancelOpen(false)
              showToast('تم إلغاء التذكرة', 'success')
            },
            onError: (err) => setCancelError(extractErrorMessage(err)),
          })
        }
        title="إلغاء التذكرة"
        description={`سيتم إلغاء التذكرة ${ticket.ticket_number} ولن تقدر ترد عليها بعد الإلغاء. هل أنت متأكد؟`}
        confirmLabel="إلغاء التذكرة"
        loading={cancelMutation.isPending}
        errorMessage={cancelError}
      />

      <NewTicketModal open={newTicketOpen} onClose={() => setNewTicketOpen(false)} />
    </motion.div>
  )
}

/**
 * بديل صندوق الرد لما يكون الرد غير متاح: مغلقة (مع زر تذكرة جديدة لمقدّم الطلب
 * — القسم 4: المغلقة ما ترجع)، ملغاة، أو عضو دعم بدون صلاحية الرد.
 */
function ReadOnlyNotice({ ticket, onNewTicket }: { ticket: Ticket; onNewTicket: () => void }) {
  let icon = <Lock size={18} />
  let text: string
  if (ticket.status === 'closed') {
    text =
      ticket.viewer === 'requester'
        ? `التذكرة مغلقة وما تقبل ردود. لمتابعة نفس الموضوع افتح تذكرة جديدة واذكر رقم ${ticket.ticket_number} في الوصف.`
        : 'التذكرة مغلقة وللقراءة فقط.'
  } else if (ticket.status === 'cancelled') {
    icon = <Ban size={18} />
    text = 'التذكرة ملغاة وللقراءة فقط.'
  } else {
    text = 'ما عندك صلاحية الرد على التذاكر.'
  }
  return (
    <Card className="flex flex-col items-start gap-3 bg-bg-elevated/50 sm:flex-row sm:items-center sm:justify-between">
      <p className="flex items-center gap-2 text-sm text-text-secondary">
        <span className="shrink-0 text-text-muted">{icon}</span>
        {text}
      </p>
      {ticket.status === 'closed' && ticket.viewer === 'requester' && (
        <Button size="sm" variant="secondary" icon={<Plus size={14} />} onClick={onNewTicket}>
          تذكرة جديدة
        </Button>
      )}
    </Card>
  )
}

/** هيكل التحميل الأول لصفحة التذكرة. */
function DetailSkeleton() {
  return (
    <div className="flex flex-col gap-6">
      <Skeleton className="h-24 w-full rounded-md" />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="flex flex-col gap-4">
          <Skeleton className="h-32 w-full rounded-md" />
          <Skeleton className="h-16 w-2/3 rounded-md" />
          <Skeleton className="h-40 w-full rounded-md" />
        </div>
        <Skeleton className="h-80 w-full rounded-md" />
      </div>
    </div>
  )
}
