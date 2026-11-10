import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { PasswordRulesChecklist } from './PasswordRulesChecklist'
import { newPasswordSchema } from './passwordPolicy'

/** حالة كل قاعدة بالقائمة: {id: متحققة؟}. */
function rulesState(): Record<string, boolean> {
  return Object.fromEntries(
    screen.getAllByRole('listitem').map((li) => [li.getAttribute('data-rule'), li.getAttribute('data-met') === 'true']),
  )
}

describe('PasswordRulesChecklist', () => {
  it('كل القواعد غير متحققة لخانة فارغة', () => {
    render(<PasswordRulesChecklist password="" />)
    expect(rulesState()).toEqual({ length: false, uppercase: false, lowercase: false, digit: false })
  })

  it('تتحقق كل قاعدة لحالها أثناء الكتابة', () => {
    const { rerender } = render(<PasswordRulesChecklist password="A" />)
    expect(rulesState()).toEqual({ length: false, uppercase: true, lowercase: false, digit: false })

    rerender(<PasswordRulesChecklist password="Ab" />)
    expect(rulesState()).toMatchObject({ uppercase: true, lowercase: true, digit: false })

    rerender(<PasswordRulesChecklist password="Ab1" />)
    expect(rulesState()).toMatchObject({ uppercase: true, lowercase: true, digit: true, length: false })

    rerender(<PasswordRulesChecklist password="Abcdefg1" />)
    expect(rulesState()).toEqual({ length: true, uppercase: true, lowercase: true, digit: true })
  })

  it('القواعد غير المتحققة تظهر كخطأ بعد محاولة الحفظ فقط', () => {
    const { rerender } = render(<PasswordRulesChecklist password="abc" />)
    expect(screen.getByText('حرف كبير (A-Z)').closest('li')).not.toHaveClass('text-danger')

    rerender(<PasswordRulesChecklist password="abc" showUnmet />)
    expect(screen.getByText('حرف كبير (A-Z)').closest('li')).toHaveClass('text-danger')
    expect(screen.getByText('حرف صغير (a-z)').closest('li')).toHaveClass('text-success')
  })

  it('قارئ الشاشة يقرأ حالة كل قاعدة', () => {
    render(<PasswordRulesChecklist password="A" />)
    expect(screen.getByText('حرف كبير (A-Z)').closest('li')).toHaveTextContent('متحقق')
    expect(screen.getByText('رقم (0-9)').closest('li')).toHaveTextContent('غير متحقق')
  })
})

describe('newPasswordSchema — نفس قواعد القائمة', () => {
  it.each([
    ['Ab1', 'يجب أن تحتوي على 8 أحرف على الأقل'],
    ['abcdefg1', 'يجب أن تحتوي على حرف كبير'],
    ['ABCDEFG1', 'يجب أن تحتوي على حرف صغير'],
    ['Abcdefgh', 'يجب أن تحتوي على رقم'],
  ])('%s مرفوضة برسالة واضحة', (value, message) => {
    const result = newPasswordSchema.safeParse(value)
    expect(result.success).toBe(false)
    expect(result.error?.issues[0].message).toBe(message)
  })

  it('كلمة مرور تحقق كل القواعد مقبولة', () => {
    expect(newPasswordSchema.safeParse('StrongPass1').success).toBe(true)
  })
})
