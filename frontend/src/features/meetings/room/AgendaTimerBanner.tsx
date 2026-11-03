import { useEffect, useState } from 'react'
import { ClipboardList, Timer } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { DiscussingAgendaItem } from '@/hooks/useMeetingRealtime'

/** يحوّل الثواني لصيغة mm:ss (أو h:mm:ss). */
function formatClock(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  return h > 0 ? `${h}:${pad(m)}:${pad(sec)}` : `${pad(m)}:${pad(sec)}`
}

/**
 * شريط "جارٍ الآن مناقشة" + مؤقت البند (قرار لاما 2026-11-03):
 * عدّاد تنازلي يشوفه الكل لو الرئيس اختار مؤقت — يتلون أصفر بآخر دقيقة،
 * وأحمر لما يخلص ("تجاوز الوقت +mm:ss"). تنبيهي فقط، ما يوقف النقاش.
 * بدون مؤقت ⇒ يعرض الوقت المنقضي على البند.
 */
export function AgendaTimerBanner({ item }: { item: DiscussingAgendaItem }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])

  const started = item.startedAt ? new Date(item.startedAt).getTime() : null
  const elapsed = started ? (now - started) / 1000 : null
  const remaining = item.durationSeconds && elapsed !== null ? item.durationSeconds - elapsed : null
  const over = remaining !== null && remaining <= 0
  const warning = remaining !== null && remaining > 0 && remaining <= 60

  return (
    <div
      className={cn(
        'flex items-center gap-2 rounded-md border px-3 py-2 text-[12px] font-medium text-white transition-colors',
        over
          ? 'border-danger/50 bg-danger/20'
          : warning
            ? 'border-warning/50 bg-warning/20'
            : 'border-brand-primary/30 bg-brand-primary/10',
      )}
    >
      <ClipboardList size={14} className="shrink-0 text-brand-accent" />
      <span className="min-w-0 flex-1 truncate">جارٍ الآن مناقشة: {item.title}</span>
      {remaining !== null ? (
        <span
          className={cn(
            'flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 font-mono text-[12px] font-bold',
            over ? 'bg-danger text-white' : warning ? 'bg-warning text-white' : 'bg-white/10',
          )}
        >
          <Timer size={12} />
          {over ? `تجاوز الوقت +${formatClock(-remaining)}` : formatClock(remaining)}
        </span>
      ) : elapsed !== null ? (
        <span className="flex shrink-0 items-center gap-1 font-mono text-[11px] text-white/60">
          <Timer size={11} /> {formatClock(elapsed)}
        </span>
      ) : null}
    </div>
  )
}
