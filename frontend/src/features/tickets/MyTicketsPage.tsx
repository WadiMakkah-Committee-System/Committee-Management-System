import { useState } from 'react'
import { Plus, Ticket as TicketIcon } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { Select } from '@/components/ui/Select'
import { TableSkeleton } from '@/components/ui/Skeleton'
import { useMyTickets } from '@/hooks/useTickets'
import { NewTicketModal } from './NewTicketModal'
import { TicketListRow, TicketPager } from './TicketList'
import { OPEN_TICKET_STATUSES, ticketStatusLabel } from './ticketLabels'
import type { TicketStatus } from '@/types/tickets'

const PAGE_SIZE = 20

/** خيارات فلتر الحالة لمقدّم الطلب — بأسماء الحالات كما يراها هو (القسم 4). */
const STATUS_FILTER_OPTIONS: { value: string; label: string }[] = [
  { value: 'all', label: 'كل الحالات' },
  { value: 'open', label: 'المفتوحة' },
  ...(['new', 'in_progress', 'waiting_on_requester', 'resolved', 'closed', 'cancelled'] as TicketStatus[]).map(
    (status) => ({ value: status, label: ticketStatusLabel(status, 'requester') }),
  ),
]

/** يحوّل قيمة الفلتر إلى قائمة الحالات المرسلة للباك-إند (undefined = الكل). */
function statusesFor(filter: string): TicketStatus[] | undefined {
  if (filter === 'all') return undefined
  if (filter === 'open') return OPEN_TICKET_STATUSES
  return [filter as TicketStatus]
}

/**
 * الهدف:
 * صفحة "تذاكري" (TKT-FR-002): تذاكر المستخدم نفسه فقط، مرتبة بآخر نشاط، مع
 * فلتر الحالة وزر "تذكرة جديدة".
 *
 * الصلاحيات: "إرسال التذاكر ومتابعتها" (المسار محمي بـProtectedRoute، والباك-إند
 * يقصر القائمة على تذاكر صاحب التوكن مهما كان النطاق).
 * الحالات: تحميل (Skeleton)، خطأ مع إعادة المحاولة، فراغ مع زر الإرسال، وصفحات.
 */
export function MyTicketsPage() {
  const [statusFilter, setStatusFilter] = useState('all')
  const [offset, setOffset] = useState(0)
  const [newOpen, setNewOpen] = useState(false)

  const { data, isLoading, isError, isFetching, refetch } = useMyTickets({
    statuses: statusesFor(statusFilter),
    limit: PAGE_SIZE,
    offset,
  })

  const tickets = data?.items ?? []
  const filtered = statusFilter !== 'all'

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-text-primary sm:text-[1.6rem] sm:leading-tight">تذاكري</h1>
          <p className="mt-1 text-sm text-text-muted">طلباتك للدعم الفني: طلب تعديل، بلاغ خلل، أو استفسار</p>
        </div>
        <Button icon={<Plus size={16} />} onClick={() => setNewOpen(true)}>
          تذكرة جديدة
        </Button>
      </div>

      <div className="w-full sm:w-56">
        <Select
          aria-label="فلتر الحالة"
          value={statusFilter}
          onChange={(e) => {
            setStatusFilter(e.target.value)
            setOffset(0)
          }}
          options={STATUS_FILTER_OPTIONS}
        />
      </div>

      {isLoading ? (
        <Card className="overflow-hidden p-0">
          <TableSkeleton rows={5} cols={3} />
        </Card>
      ) : isError ? (
        <ErrorState onRetry={() => refetch()} />
      ) : tickets.length === 0 ? (
        <EmptyState
          icon={<TicketIcon size={26} />}
          title={filtered ? 'لا توجد تذاكر بهذه الحالة' : 'ما عندك تذاكر بعد'}
          description={
            filtered
              ? 'جرّب حالة ثانية أو اعرض كل الحالات'
              : 'أرسل تذكرة للدعم الفني لأي طلب تعديل أو خلل أو استفسار'
          }
          action={
            !filtered && (
              <Button size="sm" icon={<Plus size={14} />} onClick={() => setNewOpen(true)}>
                تذكرة جديدة
              </Button>
            )
          }
        />
      ) : (
        <Card className="overflow-hidden p-0">
          <div className="divide-y divide-border-default">
            {tickets.map((ticket) => (
              <TicketListRow key={ticket.ticket_id} ticket={ticket} to={`/tickets/${ticket.ticket_id}`} />
            ))}
          </div>
          <TicketPager
            total={data?.total ?? 0}
            limit={PAGE_SIZE}
            offset={offset}
            onChange={setOffset}
            loading={isFetching}
          />
        </Card>
      )}

      <NewTicketModal open={newOpen} onClose={() => setNewOpen(false)} />
    </div>
  )
}
