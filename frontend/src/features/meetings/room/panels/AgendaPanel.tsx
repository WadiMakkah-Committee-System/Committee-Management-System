import { useState } from 'react'
import { ClipboardList, Loader2, PlayCircle, Plus, Timer } from 'lucide-react'
import { EmptyState } from '@/components/ui/EmptyState'
import { cn } from '@/lib/utils'
import type { MeetingAgendaItem } from '@/types'

export function AgendaPanel({
  agendaItems,
  discussingAgendaItemId,
  onStartDiscussing,
  canManage,
  pendingItemId = null,
  onAddItem,
}: {
  /** طلب لاما 2026-11-04: إضافة بند من داخل الاجتماع (لمن يملك الصلاحية فقط —
   * الخادم يتحقق من meetings.agenda.item.add). غير مُمرَّر ⇒ ما يظهر الحقل. */
  onAddItem?: (title: string) => Promise<boolean>
  agendaItems: MeetingAgendaItem[]
  discussingAgendaItemId: string | null
  /** durationSeconds: مؤقت البند الاختياري (null = بدون مؤقت) — قرار لاما 2026-11-03. */
  onStartDiscussing: (item: MeetingAgendaItem, durationSeconds: number | null) => void
  /** إصلاح 2026-09-14 (بلاغ لاما) — بس رئيس اللجنة يقدر يبدأ/يغيّر بند
   * المناقشة الحالي؛ الأعضاء يشوفون نفس الجدول للقراءة فقط بلا أي
   * تفاعل، عشان ضغطة عضو عرضية ما تسرق الحالة من رئيس اللجنة. */
  canManage: boolean
  /** إصلاح 2026-09-14 (بلاغ لاما الثاني — زر "بدء المناقشة" بلا أي
   * مؤشر عند الضغط): معرّف البند قيد الإرسال حاليًا (إن وُجد) — يعطّله
   * ويعرض مؤشر تحميل واضح بدل ثبات ظاهري يوحي بعدم استجابة الزر. */
  pendingItemId?: string | null
}) {
  const sorted = [...agendaItems].sort((a, b) => a.sort_order - b.sort_order)
  // البند المفتوح عليه اختيار المؤقت (الرئيس يضغط البند ⇒ يختار المدة ⇒ يبدأ).
  const [chooserFor, setChooserFor] = useState<string | null>(null)

  const addForm = onAddItem ? <AddAgendaItemForm onAdd={onAddItem} /> : null

  if (sorted.length === 0) {
    return (
      <div className="flex flex-col gap-3 p-4">
        <EmptyState icon={<ClipboardList size={22} />} title="لا توجد بنود بجدول الأعمال" />
        {addForm}
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col gap-2 overflow-y-auto p-3">
      {addForm}
      {sorted.map((item, index) => {
        const isCurrent = item.agenda_item_id === discussingAgendaItemId
        const isPending = pendingItemId === item.agenda_item_id
        return (
          <div key={item.agenda_item_id} className="flex flex-col gap-1.5">
          <button
            type="button"
            disabled={!canManage || pendingItemId !== null}
            onClick={() => canManage && !isPending && setChooserFor(chooserFor === item.agenda_item_id ? null : item.agenda_item_id)}
            className={cn(
              'flex flex-col gap-2 rounded-md border p-3 text-right transition-colors',
              isCurrent
                ? 'border-brand-primary/40 bg-brand-primary/5'
                : 'border-border-default bg-bg-surface',
              canManage && !isCurrent && 'hover:border-border-strong',
              !canManage && 'cursor-default',
              isPending && 'opacity-70',
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
                {isPending ? (
                  <>
                    <Loader2 size={12} className="animate-spin" /> جارٍ البدء...
                  </>
                ) : isCurrent ? (
                  <>
                    <PlayCircle size={12} /> قيد المناقشة الآن
                  </>
                ) : canManage ? (
                  'انقر لبدء المناقشة'
                ) : null}
                {isCurrent && canManage && !isPending && <span className="text-text-muted">· انقر لتغيير المؤقت</span>}
              </span>
            </div>
            <p className="text-[13px] font-semibold leading-relaxed text-text-primary">{item.title}</p>
            {item.description && (
              <p className="text-[12px] leading-relaxed text-text-secondary">{item.description}</p>
            )}
          </button>
          {canManage && chooserFor === item.agenda_item_id && (
            <TimerChooser
              onPick={(seconds) => {
                setChooserFor(null)
                onStartDiscussing(item, seconds)
              }}
              onCancel={() => setChooserFor(null)}
            />
          )}
          </div>
        )
      })}
    </div>
  )
}

const PRESET_MINUTES = [5, 10, 15]

/**
 * اختيار مؤقت البند قبل بدء مناقشته (قرار لاما 2026-11-03): بدون مؤقت، أو
 * 5/10/15 دقيقة، أو مدة يكتبها الرئيس (1–240 دقيقة). المؤقت تنبيهي فقط —
 * ما يوقف النقاش لما يخلص.
 */
function TimerChooser({ onPick, onCancel }: { onPick: (seconds: number | null) => void; onCancel: () => void }) {
  const [custom, setCustom] = useState('')
  const customMinutes = Number(custom)
  const customValid = Number.isInteger(customMinutes) && customMinutes >= 1 && customMinutes <= 240
  return (
    <div className="flex flex-col gap-2 rounded-md border border-brand-primary/30 bg-bg-surface p-2.5">
      <p className="flex items-center gap-1.5 text-[11px] font-semibold text-text-secondary">
        <Timer size={12} /> مؤقت للبند؟
      </p>
      <div className="flex flex-wrap gap-1.5">
        <button
          type="button"
          onClick={() => onPick(null)}
          className="rounded-full border border-border-default px-2.5 py-1 text-[11px] font-medium text-text-secondary hover:border-brand-primary hover:text-brand-primary"
        >
          بدون مؤقت
        </button>
        {PRESET_MINUTES.map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => onPick(m * 60)}
            className="rounded-full border border-border-default px-2.5 py-1 text-[11px] font-medium text-text-secondary hover:border-brand-primary hover:text-brand-primary"
          >
            {m} دقائق
          </button>
        ))}
      </div>
      <div className="flex items-center gap-1.5">
        <input
          type="number"
          min={1}
          max={240}
          value={custom}
          onChange={(e) => setCustom(e.target.value)}
          placeholder="مدة أخرى (دقائق)"
          className="h-8 min-w-0 flex-1 rounded-sm border border-border-default bg-bg-app px-2 text-[12px] text-text-primary focus:border-brand-primary focus:outline-none"
        />
        <button
          type="button"
          disabled={!customValid}
          onClick={() => onPick(customMinutes * 60)}
          className="h-8 shrink-0 rounded-sm bg-brand-primary px-3 text-[11px] font-semibold text-white disabled:opacity-50"
        >
          بدء
        </button>
        <button type="button" onClick={onCancel} className="h-8 shrink-0 px-2 text-[11px] text-text-muted hover:text-text-primary">
          إلغاء
        </button>
      </div>
    </div>
  )
}

/** حقل "إضافة بند" داخل الاجتماع — يمسح الحقل بعد النجاح، ويوضح لو الحقل فاضي. */
function AddAgendaItemForm({ onAdd }: { onAdd: (title: string) => Promise<boolean> }) {
  const [title, setTitle] = useState('')
  const [busy, setBusy] = useState(false)
  const [hint, setHint] = useState<string | null>(null)

  async function submit() {
    const clean = title.trim()
    if (clean.length < 2) {
      setHint('اكتب عنوان البند (حرفين على الأقل)')
      return
    }
    setHint(null)
    setBusy(true)
    try {
      if (await onAdd(clean)) setTitle('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-1 rounded-md border border-dashed border-border-default bg-bg-surface p-2">
      <div className="flex items-center gap-2">
        <input
          value={title}
          onChange={(e) => {
            setTitle(e.target.value)
            if (hint) setHint(null)
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              void submit()
            }
          }}
          placeholder="عنوان بند جديد..."
          maxLength={255}
          className="h-9 min-w-0 flex-1 rounded-sm border border-border-default bg-bg-app px-2.5 text-[13px] text-text-primary placeholder:text-text-muted focus:border-brand-primary focus:outline-none"
        />
        <button
          type="button"
          onClick={() => void submit()}
          disabled={busy}
          className="flex h-9 shrink-0 items-center gap-1 rounded-sm bg-brand-primary px-3 text-[12px] font-semibold text-white transition-all hover:brightness-110 disabled:opacity-60"
        >
          {busy ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
          إضافة بند
        </button>
      </div>
      {hint && <p className="text-[11px] font-medium text-danger">{hint}</p>}
    </div>
  )
}
