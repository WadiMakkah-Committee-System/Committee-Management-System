import { ClipboardList, PlayCircle } from 'lucide-react'
import { EmptyState } from '@/components/ui/EmptyState'
import { cn } from '@/lib/utils'
import type { MeetingAgendaItem } from '@/types'

export function AgendaPanel({
  agendaItems,
  discussingAgendaItemId,
  onStartDiscussing,
}: {
  agendaItems: MeetingAgendaItem[]
  discussingAgendaItemId: string | null
  onStartDiscussing: (item: MeetingAgendaItem) => void
}) {
  const sorted = [...agendaItems].sort((a, b) => a.sort_order - b.sort_order)

  if (sorted.length === 0) {
    return (
      <div className="p-4">
        <EmptyState icon={<ClipboardList size={22} />} title="لا توجد بنود بجدول الأعمال" />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-2 p-3">
      {sorted.map((item, index) => {
        const isCurrent = item.agenda_item_id === discussingAgendaItemId
        return (
          <button
            key={item.agenda_item_id}
            type="button"
            onClick={() => onStartDiscussing(item)}
            className={cn(
              'flex flex-col gap-2 rounded-md border p-3 text-right transition-colors',
              isCurrent
                ? 'border-brand-primary/40 bg-brand-primary/5'
                : 'border-border-default bg-bg-surface hover:border-border-strong',
            )}
          >
            <div className="flex items-center gap-2">
              <span
                className={cn(
                  'flex h-6 w-6 shrink-0 items-center justify-center rounded-sm text-[11px] font-bold',
                  isCurrent ? 'bg-brand-primary text-white' : 'bg-bg-elevated text-text-secondary',
                )}
              >
                {String(index + 1).padStart(2, '0')}
              </span>
              <span
                className={cn(
                  'mr-auto flex items-center gap-1 text-[11px] font-semibold',
                  isCurrent ? 'text-brand-primary' : 'text-text-muted',
                )}
              >
                {isCurrent ? (
                  <>
                    <PlayCircle size={12} /> قيد المناقشة الآن
                  </>
                ) : (
                  'انقر لبدء المناقشة'
                )}
              </span>
            </div>
            <p className="text-[13px] font-semibold leading-relaxed text-text-primary">{item.title}</p>
            {item.description && (
              <p className="text-[12px] leading-relaxed text-text-secondary">{item.description}</p>
            )}
          </button>
        )
      })}
    </div>
  )
}
