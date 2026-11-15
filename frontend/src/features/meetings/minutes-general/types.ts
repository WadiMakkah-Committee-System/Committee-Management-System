import type { JSONContent } from '@tiptap/core'
import type { MinutesSection, MinutesSectionKind } from '@/types'

/**
 * أنواع بيانات أقسام "القالب العام" — تطابق backend/app/services/minutes_general/sections.py.
 *
 * قواعد مهمة للواجهة:
 * - locked / removed_keys / auto / key / role / placeholder / agenda_item_id يحددها
 *   الخادم فقط — الواجهة تقرؤها للعرض ولا تعتمد على تعديلها.
 * - أي خانة تلقائية تتغير قيمتها بتعديل يدوي يقفلها الخادم عن المزامنة.
 */

export type EditorDoc = JSONContent

export interface TableRow {
  key?: string
  auto?: boolean
  locked?: string[]
  [field: string]: unknown
}

export interface MemberRow extends TableRow {
  name: string
  role_label: string
  mode_label: string
  status_label: string
}

export interface GuestRow extends TableRow {
  name: string
  mode_label: string
  role_label: string
}

export interface AgendaRow extends TableRow {
  ordinal_label: string
  title: string
}

export interface SignatureRow extends TableRow {
  name: string
  role_label: string
}

export interface HeaderData {
  date_text: string
  place_text: string
  time_text: string
  subject_text: string
  locked?: string[]
}

export interface TitleData {
  line1: string
  line2: string
  meeting_number: number
  meeting_year: number
  locked?: string[]
}

export type RichRole = 'opening' | 'opening_followup' | 'discussion' | 'custom'

export interface RichData {
  role: RichRole
  heading: string
  placeholder: string
  content: EditorDoc | null
}

export interface TableData<Row extends TableRow> {
  caption: string
  rows: Row[]
  removed_keys?: string[]
  locked?: string[]
}

export interface TopicData {
  agenda_item_id: string | null
  ordinal_label: string
  heading: string
  background_label: string
  background_placeholder?: string
  background: EditorDoc | null
  decision_label: string
  decision_number: string
  decision_placeholder?: string
  decision: EditorDoc | null
  locked?: string[]
}

export interface ClosingData {
  text: string
  sign_off: string
  locked?: string[]
}

export interface SignaturesData extends TableData<SignatureRow> {
  heading: string
}

/** نوع القسم (القديم بلا kind = نص). */
export function kindOf(section: MinutesSection): MinutesSectionKind {
  return section.kind ?? 'text'
}

/** بيانات القسم بنوعها (للقراءة فقط — التعديل عبر withData). */
export function dataOf<T>(section: MinutesSection): T {
  return (section.data ?? {}) as T
}

/** نسخة جديدة من القسم ببيانات معدّلة (بدون تعديل الأصل). */
export function withData<T>(section: MinutesSection, patch: Partial<T>): MinutesSection {
  return { ...section, data: { ...(section.data ?? {}), ...patch } }
}

/** هل الخانة مقفلة عن المزامنة (عُدّلت يدويًا)؟ */
export function isLocked(obj: { locked?: string[] } | null | undefined, field: string): boolean {
  return !!obj?.locked?.includes(field)
}

/** هل المحضر مبني على القالب العام؟ */
export function isGeneralTemplate(templateId: string | null | undefined): boolean {
  return templateId === 'general'
}

/** نص "الموضوع الأول: العنوان:" بدون نقطة قبل النقطتين (مثل المحضر الأصلي). */
export function topicHeadingText(data: TopicData): string {
  const title = (data.heading ?? '').replace(/[\s.:،]+$/u, '')
  return [data.ordinal_label, title].filter(Boolean).join(': ') + ':'
}
