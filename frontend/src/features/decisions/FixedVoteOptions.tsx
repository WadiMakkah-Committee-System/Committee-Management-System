import { Lock } from 'lucide-react'
import { cn } from '@/lib/utils'

/**
 * خيارات التصويت الثابتة على القرارات (تحديث 2026-11-03، قرار صاحب المشروع
 * بعد مقارنة منصات الحوكمة): نفس ما يُنشئه الباك-إند في
 * decision_service/voting.py (_FIXED_VOTE_OPTIONS + "ممتنع") — "موافق" وحده
 * يُحتسب موافقة، و"ممتنع" خارج حساب الأغلبية. عرض فقط، بلا أي تعديل.
 */
const FIXED_VOTE_OPTIONS = ['موافق', 'غير موافق', 'ممتنع'] as const

export function FixedVoteOptions({ compact = false, className }: { compact?: boolean; className?: string }) {
  return (
    <ul className={cn('flex flex-col', compact ? 'gap-1.5' : 'gap-2', className)} aria-label="خيارات التصويت">
      {FIXED_VOTE_OPTIONS.map((label) => (
        <li
          key={label}
          className={cn(
            'flex items-center gap-2 rounded-sm border border-border-default bg-bg-elevated text-text-secondary',
            compact ? 'px-2.5 py-1.5 text-xs' : 'px-3 py-2 text-sm',
          )}
        >
          <Lock size={compact ? 11 : 13} className="shrink-0 text-text-muted" aria-hidden="true" />
          {label}
        </li>
      ))}
    </ul>
  )
}
