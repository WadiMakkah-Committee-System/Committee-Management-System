import { describe, expect, it } from 'vitest'
import {
  SUGGESTED_PASSWORD_LENGTH,
  generateTemporaryPassword,
  suggestUsernameFromEmail,
} from './credentialSuggestions'

/** نفس قواعد createSchema في UserFormModal (FR-UM-015). */
function meetsPasswordPolicy(password: string): boolean {
  return password.length >= 8 && /[A-Z]/.test(password) && /[a-z]/.test(password) && /[0-9]/.test(password)
}

describe('suggestUsernameFromEmail', () => {
  it('يأخذ الجزء الذي قبل @ بأحرف صغيرة', () => {
    expect(suggestUsernameFromEmail('Ahmed.Ali@wadimakkah.sa')).toBe('ahmed.ali')
  })

  it('يقترح أثناء الكتابة قبل كتابة @', () => {
    expect(suggestUsernameFromEmail('sara.otaibi')).toBe('sara.otaibi')
  })

  it('يحذف وسم + ويستبدل الأحرف غير المسموحة بـ _', () => {
    expect(suggestUsernameFromEmail('mohammed-q+hr@x.com')).toBe('mohammed_q')
  })

  it('يدمج الفواصل المتتالية ويحذفها من الأطراف', () => {
    expect(suggestUsernameFromEmail('.a..b__c.@x.com')).toBe('a.b_c')
  })

  it('يرجع null إذا كان الناتج أقصر من 3 أحرف أو فارغًا', () => {
    expect(suggestUsernameFromEmail('')).toBeNull()
    expect(suggestUsernameFromEmail('ab@x.com')).toBeNull()
    expect(suggestUsernameFromEmail('@x.com')).toBeNull()
  })

  it('لا يتجاوز 50 حرفًا ولا ينتهي بفاصل بعد القص', () => {
    const result = suggestUsernameFromEmail(`${'a'.repeat(49)}.bcd@x.com`)
    expect(result).toBe('a'.repeat(49))
  })

  it('يطابق دائمًا نمط حقل اسم المستخدم', () => {
    for (const email of ['Ali.Hassan@x.com', 'o\'brien@x.com', 'user_01@x.com', 'خالد.k123@x.com']) {
      const result = suggestUsernameFromEmail(email)
      if (result !== null) expect(result).toMatch(/^[a-z0-9_.]{3,50}$/)
    }
  })
})

describe('generateTemporaryPassword', () => {
  it('يولّد كلمة مرور بالطول الافتراضي تطابق سياسة كلمة المرور', () => {
    for (let i = 0; i < 500; i++) {
      const password = generateTemporaryPassword()
      expect(password).toHaveLength(SUGGESTED_PASSWORD_LENGTH)
      expect(meetsPasswordPolicy(password)).toBe(true)
    }
  })

  it('يطابق السياسة حتى بالحد الأدنى للطول (8)', () => {
    for (let i = 0; i < 500; i++) {
      expect(meetsPasswordPolicy(generateTemporaryPassword(8))).toBe(true)
    }
  })

  it('يستبعد الأحرف المتشابهة بصريًا (O 0 I l 1)', () => {
    const sample = Array.from({ length: 200 }, () => generateTemporaryPassword()).join('')
    expect(sample).not.toMatch(/[O0Il1]/)
  })

  it('يولّد قيمًا مختلفة في كل مرة', () => {
    const passwords = new Set(Array.from({ length: 100 }, () => generateTemporaryPassword()))
    expect(passwords.size).toBe(100)
  })

  it('يرفض طولًا أقل من 8', () => {
    expect(() => generateTemporaryPassword(7)).toThrow(RangeError)
  })
})
