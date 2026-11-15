import type { ReactNode } from 'react'
import { CheckCircle2, Plus, Trash2 } from 'lucide-react'
import { cn, formatDateTime } from '@/lib/utils'
import type { MinutesSection, MinutesSignature } from '@/types'
import { InlineText } from './InlineText'
import { RichTextEditor } from './RichTextEditor'
import {
  dataOf,
  isLocked,
  topicHeadingText,
  withData,
  type AgendaRow,
  type ClosingData,
  type GuestRow,
  type HeaderData,
  type MemberRow,
  type RichData,
  type SignatureRow,
  type SignaturesData,
  type TableData,
  type TableRow,
  type TitleData,
  type TopicData,
} from './types'

/**
 * الهدف:
 * مكوّنات أقسام "القالب العام" بشكل محضر وادي مكة الأصلي — كل مكوّن يعمل بوضعين:
 * تحرير (خانات تُعدَّل في مكانها) وعرض (نص المستند فقط). البيانات والقواعد من
 * الخادم (minutes_general/sections.py)؛ هنا عرض وتعديل فقط.
 *
 * المدخلات المشتركة (BlockProps): القسم، هل التحرير مسموح، دالة التعديل (تعيد
 * القسم كاملًا بعد التعديل)، وonFocus لإعلان "أحرر هذا القسم" للبقية.
 */

export interface BlockProps {
  section: MinutesSection
  editable: boolean
  onChange: (next: MinutesSection) => void
  onFocus: () => void
}

/** تلميح المزامنة لخانة تلقائية: "auto" لو لم تُعدَّل، "locked" لو عُدّلت يدويًا. */
function syncOf(obj: { locked?: string[]; auto?: boolean } | undefined, field: string, auto = true) {
  if (!auto) return undefined
  return isLocked(obj, field) ? ('locked' as const) : ('auto' as const)
}

// ============================== الترويسة والعنوان ==============================

const HEADER_LINES: { field: keyof HeaderData; label: string }[] = [
  { field: 'date_text', label: 'التاريخ' },
  { field: 'place_text', label: 'المكان' },
  { field: 'time_text', label: 'الزمان' },
  { field: 'subject_text', label: 'الموضوع' },
]

/** الترويسة: الشعار يسارًا، والتاريخ والمكان والزمان والموضوع يمينًا (مثل الأصل). */
export function HeaderBlock({ section, editable, onChange, onFocus }: BlockProps) {
  const data = dataOf<HeaderData>(section)
  return (
    <div className="minutes-letterhead flex items-start justify-between gap-6" dir="ltr">
      <img src="/wadi-makkah-logo.png" alt="شعار شركة وادي مكة للتقنية" className="h-16 w-auto shrink-0" />
      <div dir="rtl" className="flex min-w-0 flex-1 flex-col gap-0.5 text-[0.82em] leading-6">
        {HEADER_LINES.map(({ field, label }) => (
          <div key={field} className="flex items-baseline gap-1.5">
            <span className="shrink-0 font-bold">{label}:</span>
            <InlineText
              value={String(data[field] ?? '')}
              editable={editable}
              ariaLabel={label}
              sync={syncOf(data, field)}
              onFocus={onFocus}
              onChange={(value) => onChange(withData<HeaderData>(section, { [field]: value }))}
            />
          </div>
        ))}
      </div>
    </div>
  )
}

/** العنوان: "محضر اجتماع" + السطر الثاني، وخط مزدوج. رقم الاجتماع وسنته يظهران للتعديل فقط. */
export function TitleBlock({ section, editable, onChange, onFocus }: BlockProps) {
  const data = dataOf<TitleData>(section)
  const setNumber = (field: 'meeting_number' | 'meeting_year', raw: string) => {
    const value = Number.parseInt(raw, 10)
    if (Number.isFinite(value)) onChange(withData<TitleData>(section, { [field]: value }))
  }
  return (
    <div className="mt-8 text-center">
      <div>
      <InlineText
        value={data.line1 ?? ''}
        editable={editable}
        align="center"
        ariaLabel="عنوان المحضر"
        onFocus={onFocus}
        className="text-[1.18em] font-bold underline underline-offset-[6px]"
        onChange={(value) => onChange(withData<TitleData>(section, { line1: value }))}
      />
      </div>
      <div>
      <InlineText
        value={data.line2 ?? ''}
        editable={editable}
        multiline
        align="center"
        ariaLabel="السطر الثاني من العنوان"
        sync={syncOf(data, 'line2')}
        onFocus={onFocus}
        className="mt-1 text-[1.06em] font-bold"
        onChange={(value) => onChange(withData<TitleData>(section, { line2: value }))}
      />
      </div>
      {editable && (
        <div className="minutes-edit-box mx-auto mt-2 flex w-fit items-center gap-3 rounded-sm px-3 py-1 font-sans text-xs text-[color:var(--paper-muted)]">
          <label className="flex items-center gap-1.5">
            رقم الاجتماع
            <input
              type="number"
              min={1}
              max={999}
              value={data.meeting_number ?? 1}
              onFocus={onFocus}
              onChange={(e) => setNumber('meeting_number', e.target.value)}
              className="minutes-edit-control w-14 rounded-xs bg-transparent px-1 text-center"
            />
          </label>
          <label className="flex items-center gap-1.5">
            لعام
            <input
              type="number"
              min={1900}
              max={2200}
              value={data.meeting_year ?? new Date().getFullYear()}
              onFocus={onFocus}
              onChange={(e) => setNumber('meeting_year', e.target.value)}
              className="minutes-edit-control w-20 rounded-xs bg-transparent px-1 text-center"
            />
          </label>
        </div>
      )}
      <div className="minutes-double-rule mt-4" aria-hidden />
    </div>
  )
}

// ============================== المحرر الغني ==============================

/** فقرة يدوية (الافتتاحية/الافتتاح/قسم مضاف) أو مربع "مناقشة أعضاء اللجنة". */
export function RichBlock({ section, editable, onChange, onFocus }: BlockProps) {
  const data = dataOf<RichData>(section)
  const empty = !data.content
  const editor = (
    <RichTextEditor
      value={data.content ?? null}
      editable={editable}
      placeholder={data.placeholder || 'اكتب هنا'}
      onFocus={onFocus}
      ariaLabel={data.heading || section.title}
      onChange={(content) => onChange(withData<RichData>(section, { content }))}
    />
  )
  if (data.role === 'discussion') {
    return (
      <div className="mt-6">
        <div className="minutes-grey-box px-4 py-2.5 text-center">
          <InlineText
            value={data.heading ?? ''}
            editable={editable}
            align="center"
            ariaLabel="عنوان مربع المناقشة"
            onFocus={onFocus}
            onChange={(value) => onChange(withData<RichData>(section, { heading: value }))}
          />
        </div>
        {!editable && empty ? <div className="h-40" aria-hidden /> : <div className="mt-3">{editor}</div>}
      </div>
    )
  }
  if (!editable && empty && !data.heading) return null
  return (
    <div className="mt-4">
      {(editable && data.role === 'custom') || data.heading ? (
        <InlineText
          value={data.heading ?? ''}
          editable={editable}
          ariaLabel="عنوان القسم"
          placeholder="عنوان القسم"
          onFocus={onFocus}
          className="mb-1 font-bold underline underline-offset-4"
          onChange={(value) => onChange(withData<RichData>(section, { heading: value }))}
        />
      ) : null}
      {editor}
    </div>
  )
}

// ============================== الجداول ==============================

interface Column<Row> {
  field: keyof Row & string
  label: string
  width: string
  align?: 'right' | 'center'
  bold?: boolean
  options?: string[]
}

/** خلية جدول: نص يُعدَّل في مكانه، أو قائمة اختيار (حالة الحضور). */
function Cell<Row extends TableRow>({
  row,
  column,
  editable,
  onFocus,
  onChange,
}: {
  row: Row
  column: Column<Row>
  editable: boolean
  onFocus: () => void
  onChange: (value: string) => void
}) {
  const value = String(row[column.field] ?? '')
  if (column.options && editable) {
    const options = column.options.includes(value) ? column.options : [...column.options, value]
    return (
      <select
        aria-label={column.label}
        value={value}
        onFocus={onFocus}
        onChange={(e) => onChange(e.target.value)}
        title={row.auto ? (isLocked(row, column.field) ? 'عُدّلت يدويًا' : 'تلقائي من الحضور') : undefined}
        className={cn(
          'minutes-cell-select w-full rounded-xs bg-transparent text-center outline-none',
          row.auto && !isLocked(row, column.field) && 'minutes-inline-auto',
        )}
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {option || '—'}
          </option>
        ))}
      </select>
    )
  }
  return (
    <InlineText
      value={value}
      editable={editable}
      multiline
      align={column.align ?? 'center'}
      ariaLabel={column.label}
      sync={syncOf(row, column.field, !!row.auto)}
      onFocus={onFocus}
      className={cn(column.bold && 'font-bold')}
      onChange={onChange}
    />
  )
}

/**
 * جدول بشكل الأصل: رأس رمادي وحدود سوداء، وعمود "م" بترقيم "1." — في التحرير:
 * إضافة صف يدوي وحذف أي صف (الصف التلقائي المحذوف لا ترجعه المزامنة).
 */
function PaperTable<Row extends TableRow>({
  section,
  rows,
  columns,
  editable,
  onFocus,
  onRowsChange,
  newRow,
  numbered = true,
  firstColumnShaded = false,
  emptyText,
}: {
  section: MinutesSection
  rows: Row[]
  columns: Column<Row>[]
  editable: boolean
  onFocus: () => void
  onRowsChange: (rows: Row[]) => void
  newRow: () => Row
  numbered?: boolean
  firstColumnShaded?: boolean
  emptyText?: string
}) {
  const update = (index: number, field: string, value: string) =>
    onRowsChange(rows.map((row, i) => (i === index ? ({ ...row, [field]: value } as Row) : row)))
  return (
    <div className="overflow-x-auto">
      <table className="minutes-table w-full" aria-label={section.title}>
        <thead>
          <tr>
            {numbered && <th className="w-[6%]">م</th>}
            {columns.map((c) => (
              <th key={c.field} style={{ width: c.width }}>
                {c.label}
              </th>
            ))}
            {editable && <th className="minutes-table-tools w-8" aria-label="إجراءات" />}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && emptyText && (
            <tr>
              <td colSpan={columns.length + (numbered ? 1 : 0) + (editable ? 1 : 0)} className="text-center opacity-60">
                {emptyText}
              </td>
            </tr>
          )}
          {rows.map((row, index) => (
            <tr key={row.key ?? index}>
              {numbered && <td className="text-center">{index + 1}.</td>}
              {columns.map((c, ci) => (
                <td key={c.field} className={cn(firstColumnShaded && ci === 0 && 'minutes-cell-shaded')}>
                  <Cell
                    row={row}
                    column={c}
                    editable={editable}
                    onFocus={onFocus}
                    onChange={(value) => update(index, c.field, value)}
                  />
                </td>
              ))}
              {editable && (
                <td className="minutes-table-tools text-center">
                  <button
                    type="button"
                    aria-label="حذف الصف"
                    title="حذف الصف"
                    onClick={() => onRowsChange(rows.filter((_, i) => i !== index))}
                    className="rounded-xs p-1 font-sans text-[color:var(--paper-muted)] hover:bg-danger-bg hover:text-danger"
                  >
                    <Trash2 size={13} />
                  </button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {editable && (
        <button
          type="button"
          onClick={() => onRowsChange([...rows, newRow()])}
          className="mt-1 flex items-center gap-1 rounded-xs px-2 py-1 font-sans text-xs font-medium text-brand-primary hover:bg-brand-primary/5"
        >
          <Plus size={13} /> إضافة صف
        </button>
      )}
    </div>
  )
}

function Caption({ section, caption, editable, onFocus, onChange }: {
  section: MinutesSection
  caption: string
  editable: boolean
  onFocus: () => void
  onChange: (value: string) => void
}) {
  if (!editable && !caption) return null
  return (
    <InlineText
      value={caption}
      editable={editable}
      ariaLabel={`عنوان ${section.title}`}
      placeholder="نص قبل الجدول (اختياري)"
      onFocus={onFocus}
      className="mb-1"
      onChange={onChange}
    />
  )
}

const STATUS_OPTIONS = ['', 'حاضر', 'غائب']

/** جدول أعضاء اللجنة: م | اسم العضو | آلية الحضور | الصفة | الحالة (ترتيب الأصل + الحالة). */
export function MembersBlock({ section, editable, onChange, onFocus }: BlockProps) {
  const data = dataOf<TableData<MemberRow>>(section)
  const columns: Column<MemberRow>[] = [
    { field: 'name', label: 'اسم العضو', width: '38%', align: 'right' },
    { field: 'mode_label', label: 'آلية الحضور', width: '17%' },
    { field: 'role_label', label: 'الصفة', width: '24%' },
    { field: 'status_label', label: 'الحالة', width: '15%', options: STATUS_OPTIONS },
  ]
  return (
    <div className="mt-3">
      <Caption
        section={section}
        caption={data.caption ?? ''}
        editable={editable}
        onFocus={onFocus}
        onChange={(caption) => onChange(withData(section, { caption }))}
      />
      <PaperTable
        section={section}
        rows={data.rows ?? []}
        columns={columns}
        editable={editable}
        onFocus={onFocus}
        onRowsChange={(rows) => onChange(withData(section, { rows }))}
        newRow={() => ({ name: '', mode_label: '', role_label: '', status_label: '' })}
      />
    </div>
  )
}

/** "وقد حضر الاجتماع": م | الاسم | آلية الحضور | الصفة — يختفي عند العرض إذا كان فارغًا. */
export function GuestsBlock({ section, editable, onChange, onFocus }: BlockProps) {
  const data = dataOf<TableData<GuestRow>>(section)
  const rows = data.rows ?? []
  if (!editable && rows.length === 0) return null
  const columns: Column<GuestRow>[] = [
    { field: 'name', label: 'الاسم', width: '52%', align: 'right' },
    { field: 'mode_label', label: 'آلية الحضور', width: '17%' },
    { field: 'role_label', label: 'الصفة', width: '25%' },
  ]
  return (
    <div className="mt-4">
      <Caption
        section={section}
        caption={data.caption ?? ''}
        editable={editable}
        onFocus={onFocus}
        onChange={(caption) => onChange(withData(section, { caption }))}
      />
      <PaperTable
        section={section}
        rows={rows}
        columns={columns}
        editable={editable}
        onFocus={onFocus}
        onRowsChange={(next) => onChange(withData(section, { rows: next }))}
        newRow={() => ({ name: '', mode_label: '', role_label: '' })}
        emptyText="لم يحضر أحد من خارج اللجنة — هذا الجدول لا يظهر في المحضر ما لم يُضف حاضر"
      />
    </div>
  )
}

/** جدول الأعمال: رقم الموضوع (عريض بخلفية رمادية) | البند. */
export function AgendaBlock({ section, editable, onChange, onFocus }: BlockProps) {
  const data = dataOf<TableData<AgendaRow>>(section)
  const rows = data.rows ?? []
  if (!editable && rows.length === 0) return null
  const columns: Column<AgendaRow>[] = [
    { field: 'ordinal_label', label: 'رقم الموضوع', width: '22%', bold: true },
    { field: 'title', label: 'البند', width: '78%', align: 'right' },
  ]
  return (
    <div className="mt-4">
      <Caption
        section={section}
        caption={data.caption ?? ''}
        editable={editable}
        onFocus={onFocus}
        onChange={(caption) => onChange(withData(section, { caption }))}
      />
      <PaperTable
        section={section}
        rows={rows}
        columns={columns}
        editable={editable}
        onFocus={onFocus}
        numbered={false}
        firstColumnShaded
        onRowsChange={(next) => onChange(withData(section, { rows: next }))}
        newRow={() => ({ ordinal_label: '', title: '' })}
      />
    </div>
  )
}

// ============================== المواضيع ==============================

function Heading({ children }: { children: ReactNode }) {
  return <div className="mt-3 flex flex-wrap items-baseline gap-x-1 text-[1.04em] font-bold underline underline-offset-[5px]">{children}</div>
}

/** موضوع: "الموضوع الأول: العنوان:"، ثم "حيثيات الموضوع:" ومحرر، ثم "القرار (رقم):" ومحرر. */
export function TopicBlock({
  section,
  editable,
  onChange,
  onFocus,
  onDelete,
}: BlockProps & { onDelete?: () => void }) {
  const data = dataOf<TopicData>(section)
  const set = (patch: Partial<TopicData>) => onChange(withData<TopicData>(section, patch))
  return (
    <div className="group relative mt-6">
      {editable && onDelete && (
        <button
          type="button"
          onClick={onDelete}
          aria-label="حذف الموضوع"
          title="حذف الموضوع"
          className="absolute -left-2 top-0 rounded-xs p-1 font-sans text-[color:var(--paper-muted)] opacity-0 transition-opacity hover:bg-danger-bg hover:text-danger focus:opacity-100 group-hover:opacity-100"
        >
          <Trash2 size={14} />
        </button>
      )}
      {editable ? (
        <Heading>
          <InlineText
            value={data.ordinal_label ?? ''}
            editable
            fit
            ariaLabel="ترتيب الموضوع"
            sync={syncOf(data, 'ordinal_label')}
            onFocus={onFocus}
            onChange={(value) => set({ ordinal_label: value })}
          />
          <span>:</span>
          <span className="min-w-0 flex-1">
            <InlineText
              value={data.heading ?? ''}
              editable
              multiline
              ariaLabel="عنوان الموضوع"
              sync={syncOf(data, 'heading')}
              onFocus={onFocus}
              onChange={(value) => set({ heading: value })}
            />
          </span>
        </Heading>
      ) : (
        <Heading>{topicHeadingText(data)}</Heading>
      )}
      <Heading>
        <InlineText
          value={data.background_label ?? ''}
          editable={editable}
          ariaLabel="عنوان الحيثيات"
          onFocus={onFocus}
          fit
          onChange={(value) => set({ background_label: value })}
        />
      </Heading>
      <RichTextEditor
        value={data.background ?? null}
        editable={editable}
        placeholder={data.background_placeholder || 'اكتب حيثيات الموضوع'}
        ariaLabel="حيثيات الموضوع"
        onFocus={onFocus}
        onChange={(background) => set({ background })}
        className="mt-1"
      />
      <Heading>
        {editable ? (
          <>
            <InlineText
              value={data.decision_label ?? ''}
              editable
              ariaLabel="عنوان القرار"
              onFocus={onFocus}
              fit
              onChange={(value) => set({ decision_label: value })}
            />
            <InlineText
              value={data.decision_number ?? ''}
              editable
              ariaLabel="رقم القرار"
              sync={syncOf(data, 'decision_number')}
              onFocus={onFocus}
              fit
              onChange={(value) => set({ decision_number: value })}
            />
            <span>:</span>
          </>
        ) : (
          <span>
            {[data.decision_label, data.decision_number].filter(Boolean).join(' ')}:
          </span>
        )}
      </Heading>
      <RichTextEditor
        value={data.decision ?? null}
        editable={editable}
        placeholder={data.decision_placeholder || 'اكتب نص القرار'}
        ariaLabel="نص القرار"
        onFocus={onFocus}
        onChange={(decision) => set({ decision })}
        className="mt-1"
      />
    </div>
  )
}

// ============================== الختام والتوقيعات ==============================

/** الختام: سطر انتهاء الاجتماع (بوقت الانتهاء الفعلي) ثم "وعلى ذلك جرى التوقيع،". */
export function ClosingBlock({ section, editable, onChange, onFocus }: BlockProps) {
  const data = dataOf<ClosingData>(section)
  return (
    <div className="mt-10">
      <InlineText
        value={data.text ?? ''}
        editable={editable}
        multiline
        ariaLabel="نص الختام"
        sync={syncOf(data, 'text')}
        onFocus={onFocus}
        className="text-[0.92em] font-bold"
        onChange={(text) => onChange(withData<ClosingData>(section, { text }))}
      />
      <InlineText
        value={data.sign_off ?? ''}
        editable={editable}
        align="center"
        ariaLabel="عبارة التوقيع"
        onFocus={onFocus}
        className="mt-2 block text-[1.06em] font-bold"
        onChange={(sign_off) => onChange(withData<ClosingData>(section, { sign_off }))}
      />
    </div>
  )
}

/** خانة توقيع: الاسم و(الصفة) ثم مساحة التوقيع بحالته من نظام التوقيع الإلكتروني فقط. */
function SignatureCell({
  row,
  status,
  editable,
  onFocus,
  onChange,
}: {
  row: SignatureRow
  status: MinutesSignature | undefined
  editable: boolean
  onFocus: () => void
  onChange: (row: SignatureRow) => void
}) {
  return (
    <div className="flex h-full flex-col">
      <div className="minutes-sign-label px-2 py-2 text-center font-bold">
        <InlineText
          value={row.name ?? ''}
          editable={editable}
          align="center"
          ariaLabel="اسم الموقّع"
          sync={syncOf(row, 'name', !!row.auto)}
          onFocus={onFocus}
          onChange={(name) => onChange({ ...row, name })}
        />
        <div className="flex items-center justify-center">
          <span>(</span>
          <InlineText
            value={row.role_label ?? ''}
            editable={editable}
            align="center"
            ariaLabel="صفة الموقّع"
            sync={syncOf(row, 'role_label', !!row.auto)}
            onFocus={onFocus}
            fit
            onChange={(role_label) => onChange({ ...row, role_label })}
          />
          <span>)</span>
        </div>
      </div>
      <div className="flex min-h-24 flex-1 flex-col items-center justify-center gap-1 p-2 font-sans text-xs">
        {status?.signed ? (
          <>
            <span className="flex items-center gap-1.5 font-semibold text-success">
              <CheckCircle2 size={15} /> موقّع إلكترونيًا
            </span>
            <span className="text-[color:var(--paper-muted)]">{formatDateTime(status.signed_at)}</span>
          </>
        ) : status ? (
          <span className="text-[color:var(--paper-muted)]">بانتظار التوقيع</span>
        ) : null}
      </div>
    </div>
  )
}

/**
 * صفحة التوقيعات: العنوان، ثم شبكة عمودين (الأول يمينًا)، والأخير (رئيس اللجنة)
 * بعرض كامل — مثل الأصل. حالة كل توقيع من minutes.signatures (لا تُعدَّل يدويًا).
 */
export function SignaturesBlock({
  section,
  editable,
  onChange,
  onFocus,
  signatures,
}: BlockProps & { signatures: MinutesSignature[] }) {
  const data = dataOf<SignaturesData>(section)
  const rows = data.rows ?? []
  const byUser = new Map(signatures.map((s) => [s.user.user_id, s]))
  const setRow = (index: number, row: SignatureRow) =>
    onChange(withData<SignaturesData>(section, { rows: rows.map((r, i) => (i === index ? row : r)) }))
  const last = rows.length - 1
  return (
    <div className="minutes-signatures-page mt-12">
      <InlineText
        value={data.heading ?? ''}
        editable={editable}
        multiline
        align="center"
        ariaLabel="عنوان صفحة التوقيعات"
        sync={syncOf(data, 'heading')}
        onFocus={onFocus}
        className="font-bold underline underline-offset-[5px]"
        onChange={(heading) => onChange(withData<SignaturesData>(section, { heading }))}
      />
      {rows.length > 0 && (
        <div className="minutes-sign-grid mt-10 grid grid-cols-2">
          {rows.map((row, index) => (
            <div key={row.key ?? index} className="contents">
              {/* عدد فردي قبل الأخير ⇒ خانة فاضية بحدود حتى يبقى الشكل مثل الأصل. */}
              {index === last && last % 2 === 1 && <div className="minutes-sign-cell" aria-hidden />}
              <div className={cn('minutes-sign-cell', index === last && 'col-span-2')}>
                <SignatureCell
                  row={row}
                  status={row.key ? byUser.get(row.key) : undefined}
                  editable={editable}
                  onFocus={onFocus}
                  onChange={(next) => setRow(index, next)}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/** قسم نصي (قديم أو مضاف يدويًا من نوع text): عنوان ونص. */
export function TextBlock({ section, editable, onChange, onFocus }: BlockProps) {
  return (
    <div className="mt-6">
      <InlineText
        value={section.title}
        editable={editable}
        ariaLabel="عنوان القسم"
        onFocus={onFocus}
        className="font-bold underline underline-offset-4"
        onChange={(title) => onChange({ ...section, title })}
      />
      <InlineText
        value={section.body}
        editable={editable}
        multiline
        ariaLabel="نص القسم"
        onFocus={onFocus}
        onChange={(body) => onChange({ ...section, body })}
      />
    </div>
  )
}
