import { useState } from 'react'
import { Repeat } from 'lucide-react'
import { Avatar } from '@/components/ui/Avatar'
import { Button } from '@/components/ui/Button'
import { Modal } from '@/components/ui/Modal'
import { Skeleton } from '@/components/ui/Skeleton'
import { useToast } from '@/components/ui/Toast'
import { useAssignTicket, useTicketSupportMembers } from '@/hooks/useTickets'
import { cn, extractErrorMessage } from '@/lib/utils'
import type { Ticket } from '@/types/tickets'

/**
 * الهدف:
 * إسناد التذكرة أو إعادة إسنادها لعضو دعم (TKT-FR-012).
 *
 * المسؤولية: عرض أعضاء الدعم النشطين (من يملك "عرض جميع التذاكر" بأي من
 * أدواره — القسم 6.2) واختيار واحد، مع إبراز المسند إليه الحالي ونفسي.
 *
 * المدخلات: open، onClose، ticket، currentUserId.
 * الصلاحيات: "إسناد التذكرة" — الباك-إند يرفض لو المختار مو عضو دعم مؤهل.
 * التأثيرات الجانبية: POST /tickets/{id}/assign، وإشعار للمسند إليه (بالباك-إند).
 */
export function AssignTicketModal({
  open,
  onClose,
  ticket,
  currentUserId,
}: {
  open: boolean
  onClose: () => void
  ticket: Ticket
  currentUserId: string
}) {
  const { showToast } = useToast()
  const membersQuery = useTicketSupportMembers(open)
  const assignMutation = useAssignTicket()
  const [selected, setSelected] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  /** إغلاق مع تصفير الاختيار، فالفتحة التالية تبدأ من جديد. */
  function close() {
    setSelected(null)
    setError(null)
    onClose()
  }

  const members = membersQuery.data ?? []
  const currentAssigneeId = ticket.assignee?.user_id

  function confirm() {
    if (!selected) return
    setError(null)
    assignMutation.mutate(
      { ticketId: ticket.ticket_id, assigneeId: selected },
      {
        onSuccess: () => {
          showToast('تم إسناد التذكرة', 'success')
          close()
        },
        onError: (err) => setError(extractErrorMessage(err)),
      },
    )
  }

  return (
    <Modal
      open={open}
      onClose={close}
      size="sm"
      title={ticket.assignee ? 'إعادة إسناد التذكرة' : 'إسناد التذكرة'}
      description="اختر عضو الدعم المسؤول — يوصله إشعار ويُسجَّل بسجل التذكرة"
      footer={
        <>
          <Button variant="ghost" onClick={close} disabled={assignMutation.isPending}>
            إلغاء
          </Button>
          <Button
            icon={<Repeat size={16} />}
            onClick={confirm}
            loading={assignMutation.isPending}
            disabled={!selected || selected === currentAssigneeId}
          >
            تأكيد الإسناد
          </Button>
        </>
      }
    >
      {membersQuery.isLoading ? (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-10" />
          <Skeleton className="h-10" />
        </div>
      ) : membersQuery.isError ? (
        <p className="text-sm text-danger">{extractErrorMessage(membersQuery.error)}</p>
      ) : members.length === 0 ? (
        <p className="text-sm text-text-muted">ما فيه أعضاء دعم فني نشطين حاليًا.</p>
      ) : (
        <div role="radiogroup" aria-label="أعضاء الدعم الفني" className="flex flex-col gap-1 rounded-sm border border-border-default p-1">
          {members.map((member) => {
            const checked = selected === member.user_id
            return (
              <label
                key={member.user_id}
                className={cn(
                  'flex cursor-pointer items-center gap-2.5 rounded-xs px-2 py-2 text-sm transition-colors hover:bg-bg-elevated',
                  checked && 'bg-brand-primary/5',
                )}
              >
                <input
                  type="radio"
                  name="ticket-assignee"
                  checked={checked}
                  onChange={() => setSelected(member.user_id)}
                  className="h-4 w-4 shrink-0 border-border-default text-brand-primary focus:ring-brand-accent/40"
                />
                <Avatar firstName={member.first_name} lastName={member.last_name} size={28} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium text-text-primary">
                    {member.first_name} {member.last_name}
                  </span>
                  <span dir="ltr" className="block truncate text-end text-xs text-text-muted">
                    {member.email}
                  </span>
                </span>
                {member.user_id === currentAssigneeId && <span className="shrink-0 text-xs text-text-muted">(الحالي)</span>}
                {member.user_id === currentUserId && member.user_id !== currentAssigneeId && (
                  <span className="shrink-0 text-xs text-text-muted">(أنا)</span>
                )}
              </label>
            )
          })}
        </div>
      )}
      {error && (
        <p className="mt-3 rounded-sm border border-danger-border/30 bg-danger-bg px-3 py-2 text-sm font-medium text-danger">
          {error}
        </p>
      )}
    </Modal>
  )
}
