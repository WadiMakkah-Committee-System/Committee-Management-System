import { describe, expect, it } from 'vitest'
import { isCompanyEmail } from './microsoftSignIn'
import type { LoginOptions } from '@/types'

const options: LoginOptions = {
  microsoft_enabled: true,
  microsoft_client_id: 'client',
  microsoft_tenant_id: 'tenant',
  microsoft_domains: ['wadimakkah.sa'],
}

describe('isCompanyEmail — تحديد طريق الدخول من خانة صفحة الدخول', () => {
  it('بريد الشركة يحوَّل لـMicrosoft بدون حساسية للأحرف والمسافات', () => {
    expect(isCompanyEmail('L.Alzhrani@wadimakkah.sa', options)).toBe(true)
    expect(isCompanyEmail('  m.alfaqih@WADIMAKKAH.SA ', options)).toBe(true)
  })

  it('اسم المستخدم أو بريد خارجي أو نطاق مشابه ⇒ كلمة المرور', () => {
    expect(isCompanyEmail('lalzhrani', options)).toBe(false)
    expect(isCompanyEmail('someone@gmail.com', options)).toBe(false)
    expect(isCompanyEmail('x@tilal.sa', options)).toBe(false)
    expect(isCompanyEmail('x@evil-wadimakkah.sa', options)).toBe(false)
    expect(isCompanyEmail('@wadimakkah.sa', options)).toBe(false)
  })

  it('الميزة غير مفعّلة أو الإعدادات ما وصلت ⇒ كلمة المرور دائمًا', () => {
    expect(isCompanyEmail('a@wadimakkah.sa', { ...options, microsoft_enabled: false })).toBe(false)
    expect(isCompanyEmail('a@wadimakkah.sa', null)).toBe(false)
  })
})
