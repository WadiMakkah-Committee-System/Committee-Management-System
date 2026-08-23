import { describe, expect, it } from 'vitest'
import { AxiosError } from 'axios'
import { cn, extractErrorMessage, getInitials, roleLabel } from './utils'

describe('cn', () => {
  it('يدمج classes الصحيحة ويتجاهل القيم الفارغة', () => {
    expect(cn('a', false, 'b', undefined, null, 'c')).toBe('a b c')
  })
})

describe('getInitials', () => {
  it('يرجع أول حرف من الاسم الأول واسم العائلة بأحرف كبيرة', () => {
    expect(getInitials('سارة', 'العتيبي')).toBe('سا')
    expect(getInitials('john', 'doe')).toBe('JD')
  })
})

describe('roleLabel', () => {
  it('يرجع التسمية العربية الثابتة لأي دور نظامي', () => {
    expect(roleLabel({ name: 'super_admin' })).toBe('سوبر أدمن')
    expect(roleLabel({ name: 'admin' })).toBe('مسؤول إدارة')
  })

  it('يرجع الاسم نفسه لدور مخصَّص غير معروف من الكتالوج الثابت', () => {
    expect(roleLabel({ name: 'مشرف الاجتماعات' })).toBe('مشرف الاجتماعات')
  })
})

describe('extractErrorMessage', () => {
  it('يستخرج رسالة detail النصية من استجابة FastAPI', () => {
    const error = new AxiosError('Bad Request')
    error.response = {
      data: { detail: 'اسم المستخدم مستخدم مسبقًا' },
      status: 400,
      statusText: 'Bad Request',
      headers: {},
      // @ts-expect-error -- لا نحتاج config كامل في الاختبار
      config: {},
    }
    expect(extractErrorMessage(error)).toBe('اسم المستخدم مستخدم مسبقًا')
  })

  it('يدمج رسائل validation المتعددة من Pydantic (422)', () => {
    const error = new AxiosError('Unprocessable Entity')
    error.response = {
      data: { detail: [{ msg: 'كلمة المرور قصيرة جدًا' }, { msg: 'البريد غير صحيح' }] },
      status: 422,
      statusText: 'Unprocessable Entity',
      headers: {},
      // @ts-expect-error -- لا نحتاج config كامل في الاختبار
      config: {},
    }
    expect(extractErrorMessage(error)).toBe('كلمة المرور قصيرة جدًا، البريد غير صحيح')
  })

  it('يرجع رسالة افتراضية عند خطأ غير معروف', () => {
    expect(extractErrorMessage('شيء غريب')).toBe('حدث خطأ غير متوقع، حاول مرة أخرى')
  })
})
