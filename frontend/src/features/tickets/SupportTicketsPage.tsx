import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Hand, Headset, Inbox, Layers, RotateCcw, UserCheck } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { SearchInput } from '@/components/ui/SearchInput'
import { Select } from '@/components/ui/Select'
import { TableSkeleton } from '@/components/ui/Skeleton'
import { Tabs } from '@/components/ui/Tabs'
import { useToast } from '@/components/ui/Toast'
import { useClaimTicket, useSupportTickets } from '@/hooks/useTickets'
import { extractErrorMessage } from '@/lib/utils'
import { TicketListRow, TicketPager } from './TicketList'
import {
  OPEN_TICKET_STATUSES,
  TICKET_MODULE_OPTIONS,
  TICKET_PRIORITY_OPTIONS,
  TICKET_TYPE_OPTIONS,
  ticketStatusLabel,
} from './ticketLabels'
import type {
  SupportTicketsTab,
  Ticket,
  TicketModule,
  TicketPriority,
  TicketStatus,
  TicketType,
} from '@/types/tickets'

const PAGE_SIZE = 20

const TABS: { key: SupportTicketsTab; label: string; icon: ReactNode }[] = [
  { key: 'unassigned', label: 'غير مسندة', icon: <Inbox size={16} /> },
  { key: 'mine', label: 'المسندة لي', icon: <UserCheck size={16} /> },
  { key: 'all', label: 'الكل', icon: <Layers size={16} /> },
]

const STATUS_FILTER_OPTIONS = [
  { value: '', label: 'كل الحالات' },
  { value: 'open', label: 'المفتوحة' },
  ...(['new', 'in_progress', 'waiting_on_requester', 'resolved', 'closed', 'cancelled'] as TicketStatus[]).map(
    (status) => ({ value: status, label: ticketStatusLabel(status, 'support') }),
  ),
]

/** وصف الفراغ لكل تبويب. */
const EMPTY_TEXT: Record<SupportTicketsTab, { title: string; description: string }> = {
  unassigned: { title: 'ما فيه تذاكر بانتظار الاستلام', description: 'أي تذكرة جديدة توصلك بإشعار وتظهر هنا' },
  mine: { title: 'ما عندك تذاكر مسندة', description: 'استلم تذكرة من تبويب "غير مسندة"' },
  all: { title: 'ما فيه تذاكر بعد', description: 'تظهر هنا كل تذاكر المستخدمين' },
}

/** يقرأ قيمة من قائمة مسموحة (أي شيء ثاني بالرابط يُتجاهل). */
function pick<T extends string>(value: string | null, allowed: readonly T[]): T | undefined {
  return value && (allowed as readonly string[]).includes(value) ? (value as T) : undefined
}

/**
 * الهدف:
 * صندوق تذاكر الدعم الفني (TKT-FR-010): ثلاث تبويبات (غير مسندة / المسندة لي /
 * الكل)، وفلاتر الحالة والنوع والوحدة والأولوية، والبحث بالرقم أو العنوان،
 * واستلام سريع من القائمة (TKT-FR-011).
 *
 * المسؤولية:
 * - الفلاتر والتبويب والصفحة بالرابط (search params): الرجوع من التذكرة يرجّع
 *   نفس العرض، ويقدر عضو الدعم يشارك رابط عرض معيّن.
 * - البحث يُرسل بعد توقف الكتابة 300 مللي ثانية (بدون طلب لكل حرف).
 *
 * الصلاحيات: "عرض جميع التذاكر" بنطاق الكل (يفحصها الباك-إند)؛ زر الاستلام
 * يظهر حسب ticket.actions.can_assign من الباك-إند.
 */
export function SupportTicketsPage() {
  const [params, setParams] = useSearchParams()
  const { showToast } = useToast()
  const claimMutation = useClaimTicket()

  const tab = pick(params.get('tab'), ['unassigned', 'mine', 'all'] as const) ?? 'unassigned'
  const statusParam = params.get('status') ?? ''
  const ticketType = pick<TicketType>(params.get('type'), TICKET_TYPE_OPTIONS.map((o) => o.value))
  const module = pick<TicketModule>(params.get('module'), TICKET_MODULE_OPTIONS.map((o) => o.value))
  const priority = pick<TicketPriority>(params.get('priority'), TICKET_PRIORITY_OPTIONS.map((o) => o.value))
  const query = params.get('q') ?? ''
  const offset = Math.max(0, Number(params.get('offset')) || 0)

  const [searchDraft, setSearchDraft] = useState(query)

  /** يحدّث معاملات الرابط (القيمة الفاضية تنحذف)، ويرجع للصفحة الأولى عند تغيير أي فلتر. */
  const update = (changes: Record<string, string | undefined>, resetPage = true) => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        for (const [key, value] of Object.entries(changes)) {
          if (value) next.set(key, value)
          else next.delete(key)
        }
        if (resetPage) next.delete('offset')
        return next
      },
      { replace: true },
    )
  }

  useEffect(() => {
    if (searchDraft.trim() === query) return
    const timer = window.setTimeout(() => update({ q: searchDraft.trim() || undefined }), 300)
    return () => window.clearTimeout(timer)
    // update يُبنى كل رسم؛ المقصود الاستجابة لتغيّر نص البحث فقط.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchDraft, query])

  const statuses = useMemo<TicketStatus[] | undefined>(() => {
    if (!statusParam) return undefined
    if (statusParam === 'open') return OPEN_TICKET_STATUSES
    const status = pick<TicketStatus>(statusParam, [
      'new',
      'in_progress',
      'waiting_on_requester',
      'resolved',
      'closed',
      'cancelled',
    ])
    return status ? [status] : undefined
  }, [statusParam])

  const { data, isLoading, isError, isFetching, refetch } = useSupportTickets({
    tab,
    statuses,
    ticket_type: ticketType,
    module,
    priority,
    q: query || undefined,
    limit: PAGE_SIZE,
    offset,
  })

  const tickets = data?.items ?? []
  const hasFilters = !!(statusParam || ticketType || module || priority || query)

  function claim(ticket: Ticket) {
    claimMutation.mutate(ticket.ticket_id, {
      onSuccess: () => showToast(`تم استلام التذكرة ${ticket.ticket_number}`, 'success'),
      onError: (err) => {
        showToast(extractErrorMessage(err), 'error')
        void refetch()
      },
    })
  }

  /** زر الاستلام السريع: للتذاكر غير المسندة (أو مسندة لعضو خرج من الدعم) والمفتوحة. */
  function claimAction(ticket: Ticket) {
    const unassigned = !ticket.assignee || ticket.assignee_is_active_support === false
    const open = ticket.status !== 'closed' && ticket.status !== 'cancelled'
    if (!ticket.actions.can_assign || !unassigned || !open) return undefined
    const pending = claimMutation.isPending && claimMutation.variables === ticket.ticket_id
    return (
      <Button size="sm" variant="secondary" icon={<Hand size={14} />} loading={pending} onClick={() => claim(ticket)}>
        استلام
      </Button>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="flex items-center gap-2 text-xl font-bold tracking-tight text-text-primary sm:text-[1.6rem] sm:leading-tight">
          <Headset size={24} className="text-brand-primary" />
          تذاكر الدعم الفني
        </h1>
        <p className="mt-1 text-sm text-text-muted">استقبال طلبات المستخدمين والرد عليها ومتابعتها لين تنحل</p>
      </div>

      <Tabs
        items={TABS}
        value={tab}
        onChange={(key) => update({ tab: key === 'unassigned' ? undefined : key })}
      />

      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-[minmax(0,1.6fr)_repeat(4,minmax(0,1fr))]">
          <div className="sm:col-span-2 xl:col-span-1">
            <SearchInput value={searchDraft} onChange={setSearchDraft} placeholder="ابحث برقم التذكرة أو العنوان..." />
          </div>
          <Select
            aria-label="فلتر الحالة"
            value={statusParam}
            onChange={(e) => update({ status: e.target.value || undefined })}
            options={STATUS_FILTER_OPTIONS}
          />
          <Select
            aria-label="فلتر النوع"
            value={ticketType ?? ''}
            onChange={(e) => update({ type: e.target.value || undefined })}
            options={[{ value: '', label: 'كل الأنواع' }, ...TICKET_TYPE_OPTIONS]}
          />
          <Select
            aria-label="فلتر الوحدة"
            value={module ?? ''}
            onChange={(e) => update({ module: e.target.value || undefined })}
            options={[{ value: '', label: 'كل الوحدات' }, ...TICKET_MODULE_OPTIONS]}
          />
          <Select
            aria-label="فلتر الأولوية"
            value={priority ?? ''}
            onChange={(e) => update({ priority: e.target.value || undefined })}
            options={[{ value: '', label: 'كل الأولويات' }, ...TICKET_PRIORITY_OPTIONS]}
          />
        </div>
        {hasFilters && (
          <div>
            <Button
              variant="ghost"
              size="sm"
              icon={<RotateCcw size={14} />}
              onClick={() => {
                setSearchDraft('')
                update({ status: undefined, type: undefined, module: undefined, priority: undefined, q: undefined })
              }}
            >
              مسح الفلاتر
            </Button>
          </div>
        )}
      </div>

      {isLoading ? (
        <Card className="overflow-hidden p-0">
          <TableSkeleton rows={6} cols={4} />
        </Card>
      ) : isError ? (
        <ErrorState onRetry={() => refetch()} />
      ) : tickets.length === 0 ? (
        <EmptyState
          icon={<Inbox size={26} />}
          title={hasFilters ? 'لا توجد نتائج مطابقة' : EMPTY_TEXT[tab].title}
          description={hasFilters ? 'جرّب فلاتر أو كلمات بحث مختلفة' : EMPTY_TEXT[tab].description}
        />
      ) : (
        <Card className="overflow-hidden p-0">
          <div className="flex items-center justify-between border-b border-border-default bg-table-header-bg px-4 py-2.5 text-xs font-semibold text-text-muted">
            <span>{data?.total ?? 0} تذكرة</span>
            {tab === 'unassigned' && <span>الأقدم أولًا</span>}
          </div>
          <div className="divide-y divide-border-default">
            {tickets.map((ticket) => (
              <TicketListRow
                key={ticket.ticket_id}
                ticket={ticket}
                to={`/support/tickets/${ticket.ticket_id}`}
                supportView
                action={claimAction(ticket)}
              />
            ))}
          </div>
          <TicketPager
            total={data?.total ?? 0}
            limit={PAGE_SIZE}
            offset={offset}
            onChange={(next) => update({ offset: next ? String(next) : undefined }, false)}
            loading={isFetching}
          />
        </Card>
      )}
    </div>
  )
}
