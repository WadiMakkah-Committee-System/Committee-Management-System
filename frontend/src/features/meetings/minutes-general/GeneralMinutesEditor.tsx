import { useEffect, useState } from 'react'
import { AlertTriangle, Check, Info, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { cn, formatRelativeTime } from '@/lib/utils'
import type { MinutesCollaborator } from '@/hooks/useMinutesRealtime'
import type { MeetingMinutes, MinutesSection } from '@/types'
import { GeneralMinutesDocument } from './GeneralMinutesDocument'
import { useGeneralMinutesState } from './useGeneralMinutesState'

/**
 * الهدف:
 * محرر محضر "القالب العام" — المستند نفسه يُعدَّل في مكانه (مثل الوورد)، ويُحفظ
 * قسم قسم تلقائيًا. يُستخدم بصفحة المحضر وبلوحة المحضر داخل غرفة الاجتماع.
 *
 * المدخلات:
 * - meetingId، minutes: المحضر من الخادم.
 * - editable: صلاحية التعديل بالمرحلة الحالية (تقريب بصري — الحماية بالخادم).
 * - realtime: مخرجات useMinutesRealtime (من المستدعي — اتصال Socket واحد للصفحة).
 * - currentUserId: لاستبعاد نفسي من قفل "عضو آخر يحرر هذا الجزء".
 * - compact: لوحة الاجتماع الضيقة.
 *
 * القفل البصري: عضو آخر كتب بجزء خلال آخر LOCK_TTL_MS ⇒ الجزء للقراءة فقط لي
 * مؤقتًا (نفس سلوك المحرر القديم).
 */

const LOCK_TTL_MS = 4000

interface GeneralMinutesEditorProps {
  meetingId: string
  minutes: MeetingMinutes
  editable: boolean
  realtime: {
    collaborators: MinutesCollaborator[]
    remoteSections: { sections: MinutesSection[]; at: number } | null
    remoteSection: { section: MinutesSection; at: number } | null
    announceEditing: (sectionId: string) => void
  }
  currentUserId: string | undefined
  compact?: boolean
}

export function GeneralMinutesEditor({
  meetingId,
  minutes,
  editable,
  realtime,
  currentUserId,
  compact,
}: GeneralMinutesEditorProps) {
  const state = useGeneralMinutesState({
    meetingId,
    minutes,
    remoteSections: realtime.remoteSections,
    remoteSection: realtime.remoteSection,
  })

  // نبضة كل ثانية أثناء وجود متعاونين — حتى ينفك القفل تلقائيًا بعد انتهاء المهلة.
  const [, tick] = useState(0)
  const hasCollaborators = realtime.collaborators.length > 0
  useEffect(() => {
    if (!hasCollaborators) return
    const id = setInterval(() => tick((n) => n + 1), 1000)
    return () => clearInterval(id)
  }, [hasCollaborators])

  const lockedBy = (sectionId: string) => {
    const entry = realtime.collaborators.find((c) => c.sectionId === sectionId && c.userId !== currentUserId)
    if (!entry || Date.now() - entry.at > LOCK_TTL_MS) return null
    return entry.fullName
  }

  const onSectionChange = (next: MinutesSection) => {
    state.updateSection(next)
    realtime.announceEditing(next.id)
  }

  return (
    <div className="flex flex-col gap-3">
      {editable && (
        <div
          className={cn(
            'flex flex-wrap items-center justify-between gap-2 rounded-md border border-border-default bg-bg-surface px-3 py-2 text-xs',
            compact && 'px-2',
          )}
        >
          <p className="flex items-center gap-1.5 text-text-muted">
            <Info size={13} className="shrink-0" />
            الخانات المنقّطة تتعبّأ من بيانات الاجتماع تلقائيًا إلى أن تعدّلها، وكل تعديل يُحفظ وحده.
          </p>
          <div className="flex items-center gap-2" aria-live="polite">
            {state.error ? (
              <span className="flex items-center gap-1 font-medium text-danger">
                <AlertTriangle size={13} /> {state.error}
              </span>
            ) : state.saving ? (
              <span className="flex items-center gap-1 text-text-muted">
                <Loader2 size={13} className="animate-spin" /> جارٍ الحفظ…
              </span>
            ) : state.lastSavedAt ? (
              <span className="flex items-center gap-1 text-success">
                <Check size={13} /> تم الحفظ {formatRelativeTime(new Date(state.lastSavedAt).toISOString())}
              </span>
            ) : null}
            <Button size="sm" variant="secondary" onClick={() => void state.flush()} loading={state.saving}>
              حفظ الآن
            </Button>
          </div>
        </div>
      )}
      <div className={cn('rounded-md bg-bg-elevated', compact ? 'p-2' : 'p-3 md:p-8')}>
        <GeneralMinutesDocument
          sections={state.sections}
          mode={editable ? 'edit' : 'view'}
          signatures={minutes.signatures}
          onSectionChange={editable ? onSectionChange : undefined}
          onFocusSection={editable ? realtime.announceEditing : undefined}
          lockedBy={lockedBy}
          onAddTopic={editable ? state.addTopic : undefined}
          onDeleteSection={editable ? state.deleteSection : undefined}
          compact={compact}
        />
      </div>
    </div>
  )
}
