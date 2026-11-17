import type { ReactNode } from 'react'
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  Clock3,
  Lock,
  Minus,
  PlayCircle,
  Send,
  XCircle,
} from 'lucide-react'
import { Badge } from '@/components/ui/StatusBadge'
import { TICKET_PRIORITY_LABELS, TICKET_PRIORITY_TONES, ticketStatusLabel, ticketStatusTone } from './ticketLabels'
import type { TicketPriority, TicketStatus, TicketViewer } from '@/types/tickets'

const STATUS_ICONS: Record<TicketStatus, ReactNode> = {
  new: <Send size={13} />,
  in_progress: <PlayCircle size={13} />,
  waiting_on_requester: <Clock3 size={13} />,
  resolved: <CheckCircle2 size={13} />,
  closed: <Lock size={13} />,
  cancelled: <XCircle size={13} />,
}

const PRIORITY_ICONS: Record<TicketPriority, ReactNode> = {
  low: <ArrowDown size={13} />,
  medium: <Minus size={13} />,
  high: <ArrowUp size={13} />,
  urgent: <AlertTriangle size={13} />,
}

/**
 * شارة حالة التذكرة — الاسم واللون حسب صفة المشاهد (القسم 4: مقدّم الطلب يشوف
 * "تم الإرسال" و"بانتظار ردك"). الأيقونة مع النص عشان الحالة ما تعتمد على اللون وحده.
 */
export function TicketStatusBadge({ status, viewer }: { status: TicketStatus; viewer: TicketViewer }) {
  return (
    <Badge tone={ticketStatusTone(status, viewer)} icon={STATUS_ICONS[status]}>
      {ticketStatusLabel(status, viewer)}
    </Badge>
  )
}

/** شارة الأولوية — للدعم فقط (الباك-إند يرجع null لمقدّم الطلب، فما تنعرض له). */
export function TicketPriorityBadge({ priority }: { priority: TicketPriority }) {
  return (
    <Badge tone={TICKET_PRIORITY_TONES[priority]} icon={PRIORITY_ICONS[priority]}>
      {TICKET_PRIORITY_LABELS[priority]}
    </Badge>
  )
}

/** رقم التذكرة المرجعي (TKT-2026-0001) — اتجاه LTR وأرقام بعرض ثابت حتى داخل نص عربي. */
export function TicketNumber({ value, className }: { value: string; className?: string }) {
  return (
    <span dir="ltr" className={`font-mono text-xs font-semibold tabular-nums text-text-muted ${className ?? ''}`}>
      {value}
    </span>
  )
}
