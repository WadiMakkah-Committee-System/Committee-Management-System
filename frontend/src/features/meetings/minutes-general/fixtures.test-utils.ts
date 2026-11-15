import type { MinutesSection, MinutesSignature } from '@/types'

/**
 * أقسام قالب عام نموذجية للاختبارات — بنفس شكل ما يبنيه الخادم
 * (backend/app/services/minutes_general/sections.py::sync_sections).
 */
export function sampleSections(overrides: { guests?: unknown[] } = {}): MinutesSection[] {
  const sections: Omit<MinutesSection, 'order'>[] = [
    {
      id: 'h',
      kind: 'header',
      title: 'الترويسة',
      body: '',
      rev: 1,
      data: {
        date_text: 'الخميس 1446/07/16هـ الموافق 2025/01/16م',
        place_text: 'عبر الاتصال المرئي',
        time_text: 'الساعة 05:00 مساءً',
        subject_text: 'محضر اجتماع لجنة التقنية',
        locked: [],
      },
    },
    {
      id: 't',
      kind: 'title',
      title: 'العنوان',
      body: '',
      rev: 1,
      data: { line1: 'محضر اجتماع', line2: 'لجنة التقنية - الاجتماع السادس لعام 2025م', meeting_number: 6, meeting_year: 2025, locked: [] },
    },
    { id: 'o', kind: 'rich', title: 'الفقرة الافتتاحية', body: '', rev: 1, data: { role: 'opening', heading: '', placeholder: 'اكتب الفقرة الافتتاحية', content: null } },
    {
      id: 'm',
      kind: 'members_table',
      title: 'أعضاء اللجنة',
      body: '',
      rev: 3,
      data: {
        caption: '',
        removed_keys: [],
        locked: [],
        rows: [
          { key: 'u-chair', auto: true, locked: [], name: 'أحمد علي', role_label: 'رئيس اللجنة', mode_label: 'عن بعد', status_label: 'حاضر' },
          { key: 'u-m1', auto: true, locked: ['role_label'], name: 'سارة محمد', role_label: 'عضو', mode_label: 'غائب', status_label: 'غائب' },
        ],
      },
    },
    {
      id: 'g',
      kind: 'guests_table',
      title: 'الحاضرون من خارج اللجنة',
      body: '',
      rev: 1,
      data: { caption: 'وقد حضر الاجتماع:', removed_keys: [], locked: [], rows: overrides.guests ?? [] },
    },
    {
      id: 'a',
      kind: 'agenda_table',
      title: 'جدول الأعمال',
      body: '',
      rev: 1,
      data: {
        caption: 'وقد تم استعراض ومناقشة جدول الأعمال وفقاً للتالي:',
        removed_keys: [],
        locked: [],
        rows: [{ key: 'a1', auto: true, locked: [], ordinal_label: 'الموضوع الأول', title: 'الموازنة.' }],
      },
    },
    { id: 'd', kind: 'rich', title: 'مناقشة', body: '', rev: 1, data: { role: 'discussion', heading: 'مناقشة أعضاء اللجنة', placeholder: '', content: null } },
    {
      id: 'tp1',
      kind: 'topic',
      title: 'الموضوع الأول: الموازنة.',
      body: '',
      rev: 1,
      data: {
        agenda_item_id: 'a1',
        ordinal_label: 'الموضوع الأول',
        heading: 'الموازنة.',
        background_label: 'حيثيات الموضوع:',
        background: { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'نص الحيثيات' }] }] },
        decision_label: 'القرار',
        decision_number: '(1-6-2025)',
        decision: null,
        locked: [],
      },
    },
    {
      id: 'c',
      kind: 'closing',
      title: 'الختام',
      body: '',
      rev: 1,
      data: { text: 'وقد انتهى الاجتماع ... في الساعة 06:00 مساءً.', sign_off: 'وعلى ذلك جرى التوقيع،', locked: [] },
    },
    {
      id: 's',
      kind: 'signatures',
      title: 'التوقيعات',
      body: '',
      rev: 1,
      data: {
        heading: 'توقيع أعضاء لجنة التقنية على محضر الاجتماع السادس لعام 2025م',
        caption: '',
        removed_keys: [],
        locked: [],
        rows: [
          { key: 'u-m1', auto: true, locked: [], name: 'سارة محمد', role_label: 'عضو اللجنة' },
          { key: 'u-chair', auto: true, locked: [], name: 'أحمد علي', role_label: 'رئيس اللجنة' },
        ],
      },
    },
    { id: 'meta', kind: 'meta', title: 'بيانات القالب', body: '', rev: 1, data: { template: 'general', removed_topic_keys: [] } },
  ]
  return sections.map((s, order) => ({ ...s, order }))
}

export function sampleSignatures(): MinutesSignature[] {
  const user = (user_id: string, first_name: string) => ({ user_id, first_name, middle_name: '', last_name: '', email: '' })
  return [
    { signature_id: 'sig1', user: user('u-chair', 'أحمد'), signed: true, signed_at: '2025-01-16T16:00:00Z' },
    { signature_id: 'sig2', user: user('u-m1', 'سارة'), signed: false, signed_at: null },
  ]
}
