import { describe, expect, it } from 'vitest'
import { AxiosError } from 'axios'
import {
  assignedRoles,
  cn,
  extractErrorMessage,
  fileNameFromDisposition,
  getInitials,
  otherRolesGrantingAccess,
  roleLabel,
} from './utils'

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

describe('fileNameFromDisposition', () => {
  it('يفضّل الاسم العربي من filename* على البديل اللاتيني', () => {
    const header = `attachment; filename="document.pdf"; filename*=UTF-8''${encodeURIComponent('محضر - الاجتماع.pdf')}`
    expect(fileNameFromDisposition(header, 'x')).toBe('محضر - الاجتماع.pdf')
  })
  it('يرجع لـfilename العادي ثم للبديل', () => {
    expect(fileNameFromDisposition('attachment; filename="a.txt"', 'x')).toBe('a.txt')
    expect(fileNameFromDisposition('', 'x')).toBe('x')
  })
})

// ============================ تعدد الأدوار (migration 0046) ============================

describe('assignedRoles / otherRolesGrantingAccess', () => {
  const role = (role_id: string, is_super_admin = false) => ({
    role_id,
    name: role_id,
    description: null,
    is_super_admin,
  })
  const office = role('office')
  const admin = role('admin')
  const root = role('root', true)

  it('يرجع الدور الحالي وحده لو قائمة الأدوار غير محمّلة', () => {
    expect(assignedRoles({ role: office, roles: null })).toEqual([office])
    expect(assignedRoles({ role: null })).toEqual([])
    expect(assignedRoles({ role: office, roles: [office, admin] })).toEqual([office, admin])
  })

  it('يقترح فقط الأدوار الأخرى اللي تملك إحدى صلاحيات الصفحة', () => {
    const user = {
      role: admin,
      roles: [admin, office],
      roles_permissions: { admin: ['committees.request.create'], office: ['committees.request.view'] },
    }
    expect(otherRolesGrantingAccess(user, { anyPermission: ['committees.request.view'] })).toEqual([office])
    // الدور الحالي نفسه لا يُقترح أبدًا
    expect(otherRolesGrantingAccess(user, { anyPermission: ['committees.request.create'] })).toEqual([])
    expect(otherRolesGrantingAccess(user, { anyPermission: ['users.view'] })).toEqual([])
  })

  it('صفحات السوبر ادمن: يقترح دور is_super_admin فقط، وجلسة قديمة بلا roles_permissions آمنة', () => {
    expect(otherRolesGrantingAccess({ role: admin, roles: [admin, root] }, { superAdminOnly: true })).toEqual([root])
    expect(otherRolesGrantingAccess({ role: admin, roles: [admin, office] }, { anyPermission: ['x'] })).toEqual([])
  })
})
