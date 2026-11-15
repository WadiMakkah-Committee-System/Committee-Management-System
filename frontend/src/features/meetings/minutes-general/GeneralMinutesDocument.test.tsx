import { describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { sectionConflictOf } from '@/api/meetingMinutes'
import { GeneralMinutesDocument } from './GeneralMinutesDocument'
import { RichTextEditor } from './RichTextEditor'
import { sampleSections, sampleSignatures } from './fixtures.test-utils'
import { isLocked, topicHeadingText, withData, type TopicData } from './types'

describe('أدوات القالب العام', () => {
  it('عنوان الموضوع بدون نقطة قبل النقطتين (مثل المحضر الأصلي)', () => {
    const data = { ordinal_label: 'الموضوع الثالث', heading: 'مناقشة موازنة المشروع (مشاركة بالدخل).' } as TopicData
    expect(topicHeadingText(data)).toBe('الموضوع الثالث: مناقشة موازنة المشروع (مشاركة بالدخل):')
  })

  it('withData لا يعدّل القسم الأصلي، وisLocked يقرأ الخانات المقفلة', () => {
    const [header] = sampleSections()
    const next = withData(header, { place_text: 'قاعة' })
    expect(next.data?.place_text).toBe('قاعة')
    expect(header.data?.place_text).toBe('عبر الاتصال المرئي')
    expect(isLocked({ locked: ['role_label'] }, 'role_label')).toBe(true)
    expect(isLocked({ locked: [] }, 'name')).toBe(false)
  })

  it('sectionConflictOf يستخرج نسخة القسم من خطأ 409 فقط', () => {
    const current = sampleSections()[0]
    expect(sectionConflictOf({ response: { status: 409, data: { detail: { current_section: current } } } })).toEqual(current)
    expect(sectionConflictOf({ response: { status: 409, data: { detail: 'المحضر ليس بمرحلة التحضير' } } })).toBeNull()
    expect(sectionConflictOf({ response: { status: 400, data: { detail: 'x' } } })).toBeNull()
  })
})

describe('GeneralMinutesDocument — العرض', () => {
  it('يعرض الترويسة والجداول والمواضيع والتوقيعات بشكل المحضر', () => {
    render(<GeneralMinutesDocument sections={sampleSections()} mode="view" signatures={sampleSignatures()} />)
    expect(screen.getByText('الخميس 1446/07/16هـ الموافق 2025/01/16م')).toBeInTheDocument()
    expect(screen.getByText('لجنة التقنية - الاجتماع السادس لعام 2025م')).toBeInTheDocument()

    const members = screen.getByRole('table', { name: 'أعضاء اللجنة' })
    const headers = within(members).getAllByRole('columnheader').map((h) => h.textContent)
    expect(headers).toEqual(['م', 'اسم العضو', 'آلية الحضور', 'الصفة', 'الحالة'])
    expect(within(members).getByText('1.')).toBeInTheDocument()
    expect(within(members).getByText('سارة محمد')).toBeInTheDocument()

    expect(screen.getByText('الموضوع الأول: الموازنة:')).toBeInTheDocument()
    expect(screen.getByText('القرار (1-6-2025):')).toBeInTheDocument()
    expect(screen.getByText('موقّع إلكترونيًا')).toBeInTheDocument()
    expect(screen.getByText('بانتظار التوقيع')).toBeInTheDocument()
  })

  it('جدول "وقد حضر الاجتماع" يختفي عند العرض إذا ما فيه أحد، ويظهر إذا فيه', () => {
    const { rerender } = render(
      <GeneralMinutesDocument sections={sampleSections()} mode="view" signatures={[]} />,
    )
    expect(screen.queryByText('وقد حضر الاجتماع:')).not.toBeInTheDocument()
    rerender(
      <GeneralMinutesDocument
        sections={sampleSections({ guests: [{ key: 'g1', auto: true, name: 'ضيف', mode_label: 'عن بعد', role_label: 'ضيف خارجي' }] })}
        mode="view"
        signatures={[]}
      />,
    )
    expect(screen.getByText('وقد حضر الاجتماع:')).toBeInTheDocument()
    expect(screen.getByText('ضيف خارجي')).toBeInTheDocument()
  })
})

describe('GeneralMinutesDocument — التحرير', () => {
  it('تغيير حالة عضو وحذف صف وإضافة صف ترجع القسم المعدّل', async () => {
    const onSectionChange = vi.fn()
    render(
      <GeneralMinutesDocument
        sections={sampleSections()}
        mode="edit"
        signatures={[]}
        onSectionChange={onSectionChange}
      />,
    )
    const members = screen.getByRole('table', { name: 'أعضاء اللجنة' })
    const statusSelects = within(members).getAllByRole('combobox', { name: 'الحالة' })
    await userEvent.selectOptions(statusSelects[1], 'حاضر')
    const changed = onSectionChange.mock.lastCall?.[0]
    expect(changed.id).toBe('m')
    expect(changed.data.rows[1].status_label).toBe('حاضر')
    expect(changed.data.rows[1].key).toBe('u-m1') // المفتاح يبقى حتى يقفل الخادم الخانة الصحيحة

    await userEvent.click(within(members).getAllByRole('button', { name: 'حذف الصف' })[0])
    expect(onSectionChange.mock.lastCall?.[0].data.rows.map((r: { key: string }) => r.key)).toEqual(['u-m1'])

    const addButtons = screen.getAllByRole('button', { name: /إضافة صف/ })
    await userEvent.click(addButtons[0])
    expect(onSectionChange.mock.lastCall?.[0].data.rows).toHaveLength(3)
  })

  it('الجزء اللي يحرره عضو آخر يصير للقراءة فقط مع تنبيه باسمه', () => {
    render(
      <GeneralMinutesDocument
        sections={sampleSections()}
        mode="edit"
        signatures={[]}
        onSectionChange={() => {}}
        lockedBy={(id) => (id === 'h' ? 'سارة' : null)}
      />,
    )
    expect(screen.getByText('سارة يحرر هذا الجزء الآن')).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: 'التاريخ' })).not.toBeInTheDocument()
    expect(screen.getAllByRole('textbox', { name: 'اسم العضو' }).length).toBeGreaterThan(0)
  })

  it('الخانة التلقائية المقفلة يدويًا تظهر بتلميح مختلف عن التلقائية', () => {
    render(
      <GeneralMinutesDocument sections={sampleSections()} mode="edit" signatures={[]} onSectionChange={() => {}} />,
    )
    const roles = screen.getAllByRole('textbox', { name: 'الصفة' })
    expect(roles[0]).toHaveAttribute('title', 'تتعبّأ تلقائيًا من بيانات الاجتماع إلى أن تعدّلها')
    expect(roles[1]).toHaveAttribute('title', 'عُدّلت يدويًا — لن تتغير تلقائيًا')
  })
})

describe('RichTextEditor', () => {
  it('لا يطلق حفظًا عند التحميل حتى لو صحّحت المكتبة بنية جدول (بلاغ: تعارض 409 بدون تعديل)', async () => {
    const onChange = vi.fn()
    const doc = {
      type: 'doc',
      content: [
        {
          type: 'table',
          // صف ناقص خلية — المكتبة تكمّله تلقائيًا عند التحميل.
          content: [
            { type: 'tableRow', content: [{ type: 'tableHeader', content: [{ type: 'paragraph' }] }, { type: 'tableHeader', content: [{ type: 'paragraph' }] }] },
            { type: 'tableRow', content: [{ type: 'tableCell', content: [{ type: 'paragraph' }] }] },
          ],
        },
      ],
    }
    render(<RichTextEditor value={doc} onChange={onChange} ariaLabel="حيثيات" />)
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(onChange).not.toHaveBeenCalled()
  })
})
