import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ToastProvider } from '@/components/ui/Toast'
import { PRELAUNCH_INITIAL_PASSWORD } from '@/lib/credentialSuggestions'
import { UserFormModal } from './UserFormModal'
import type { User } from '@/types'

// الهوكات تجلب من الـAPI عبر React Query — نستبدلها ببيانات ثابتة.
// mocks: حالة قابلة للتغيير لكل اختبار (أدوار متاحة + تفاصيل مستخدم مجلوبة).
const mocks = vi.hoisted(() => ({
  roleOptions: [] as unknown[],
  userDetail: undefined as unknown,
}))
vi.mock('@/hooks/useRoles', () => ({
  useRoles: () => ({ data: [] }),
  useRoleOptions: () => ({ data: mocks.roleOptions }),
}))
vi.mock('@/hooks/useUsers', () => ({
  useUserDetail: (userId: string | undefined) => ({ data: userId ? mocks.userDetail : undefined }),
}))
vi.mock('@/hooks/useJobTitles', () => ({
  useJobTitles: () => ({ data: [] }),
  useCreateJobTitle: () => ({ mutateAsync: vi.fn() }),
}))

const EXISTING_USER: User = {
  user_id: 'u-1',
  first_name: 'سارة',
  middle_name: 'محمد',
  last_name: 'العتيبي',
  username: 'sara',
  email: 'sara@example.com',
  role: null,
  dep_id: null,
  department: null,
  job_title_id: null,
  job_title: null,
  status: 'active',
  must_change_password: false,
  last_login_at: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
} as unknown as User

/** يعرض نموذج المستخدم مفتوحًا داخل ToastProvider (مطلوب لزر النسخ). */
function renderModal(props: Partial<Parameters<typeof UserFormModal>[0]> = {}) {
  const onSubmitCreate = vi.fn()
  const onSubmitEdit = vi.fn()
  render(
    <ToastProvider>
      <UserFormModal
        open
        onClose={() => {}}
        departments={[]}
        onSubmitCreate={onSubmitCreate}
        onSubmitEdit={onSubmitEdit}
        {...props}
      />
    </ToastProvider>,
  )
  return { onSubmitCreate, onSubmitEdit }
}

beforeEach(() => {
  mocks.roleOptions = []
  mocks.userDetail = undefined
})

const usernameInput = () => screen.getByLabelText(/اسم المستخدم/) as HTMLInputElement
const emailInput = () => screen.getByLabelText(/البريد الإلكتروني/) as HTMLInputElement
const passwordInput = () => screen.getByLabelText(/كلمة المرور المؤقتة/) as HTMLInputElement

describe('UserFormModal — اقتراح بيانات الدخول', () => {
  it('يملأ كلمة المرور الموحّدة قبل التدشين (Wa123456) عند فتح نموذج الإضافة', () => {
    renderModal()
    expect(passwordInput().value).toBe('Wa123456')
  })

  it('كلمة ما قبل التدشين تطابق سياسة كلمة المرور', () => {
    expect(PRELAUNCH_INITIAL_PASSWORD).toBe('Wa123456')
    expect(PRELAUNCH_INITIAL_PASSWORD.length).toBeGreaterThanOrEqual(8)
    expect(PRELAUNCH_INITIAL_PASSWORD).toMatch(/[A-Z]/)
    expect(PRELAUNCH_INITIAL_PASSWORD).toMatch(/[a-z]/)
    expect(PRELAUNCH_INITIAL_PASSWORD).toMatch(/[0-9]/)
  })

  it('يقترح اسم المستخدم من البريد أثناء الكتابة', async () => {
    const user = userEvent.setup()
    renderModal()
    await user.type(emailInput(), 'Ahmed.Ali@wadimakkah.sa')
    expect(usernameInput().value).toBe('ahmed.ali')
  })

  it('لا يغيّر اسم المستخدم بعد تعديله يدويًا', async () => {
    const user = userEvent.setup()
    renderModal()
    await user.type(usernameInput(), 'custom_name')
    await user.type(emailInput(), 'ahmed@wadimakkah.sa')
    expect(usernameInput().value).toBe('custom_name')
  })

  it('يعود للاقتراح التلقائي إذا مُسح اسم المستخدم بالكامل', async () => {
    const user = userEvent.setup()
    renderModal()
    await user.type(usernameInput(), 'x')
    await user.clear(usernameInput())
    await user.type(emailInput(), 'khalid@wadimakkah.sa')
    expect(usernameInput().value).toBe('khalid')
  })

  it('يولّد كلمة مرور جديدة عند الضغط على الزر', async () => {
    const user = userEvent.setup()
    renderModal()
    const before = passwordInput().value
    await user.click(screen.getByRole('button', { name: 'توليد كلمة مرور جديدة' }))
    expect(passwordInput().value).not.toBe(before)
  })

  it('يمنع المتصفح من تعبئة بيانات دخول الادمن المحفوظة', () => {
    renderModal()
    expect(passwordInput()).toHaveAttribute('autocomplete', 'new-password')
    expect(usernameInput()).toHaveAttribute('autocomplete', 'off')
  })

  it('يرسل اسم المستخدم وكلمة المرور المقترحين عند الحفظ', async () => {
    const user = userEvent.setup()
    const { onSubmitCreate } = renderModal()
    await user.type(screen.getByLabelText(/الاسم الأول/), 'أحمد')
    await user.type(screen.getByLabelText(/الاسم الأوسط/), 'محمد')
    await user.type(screen.getByLabelText(/اسم العائلة/), 'علي')
    await user.type(emailInput(), 'ahmed.ali@wadimakkah.sa')
    const password = passwordInput().value
    await user.click(screen.getByRole('button', { name: 'إضافة المستخدم' }))
    expect(onSubmitCreate).toHaveBeenCalledWith(
      expect.objectContaining({ username: 'ahmed.ali', password, email: 'ahmed.ali@wadimakkah.sa' }),
    )
  })

  it('لا يعرض حقول اسم المستخدم وكلمة المرور في وضع التعديل', () => {
    renderModal({ user: EXISTING_USER })
    expect(screen.queryByLabelText(/اسم المستخدم/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'توليد كلمة مرور جديدة' })).not.toBeInTheDocument()
    expect(emailInput().value).toBe('sara@example.com')
  })
})

// ============================ تعدد الأدوار (migration 0046) ============================

const ROLE = (role_id: string, name: string) => ({
  role_id,
  name,
  description: null,
  is_system: true,
  is_super_admin: false,
  kind: 'user',
  committee_role_slug: null,
})
const OFFICE = ROLE('r-office', 'executive_office_manager')
const ADMIN = ROLE('r-admin', 'admin')
const CHAIR = { ...ROLE('r-chair', 'رئيس اللجنة'), kind: 'committee', committee_role_slug: 'chair' }

const LEGAL = { dep_id: 'd-legal', name: 'الإدارة القانونية', parent_dep_id: null } as const
const OFFICE_DEP = { dep_id: 'd-office', name: 'مكتب الرئيس التنفيذي', parent_dep_id: null } as const
const DEPARTMENTS = [LEGAL, OFFICE_DEP] as unknown as Parameters<typeof UserFormModal>[0]['departments']

const saveEdit = () => screen.getByRole('button', { name: 'حفظ التعديلات' })
const roleSelects = () => screen.getAllByLabelText('الدور') as HTMLSelectElement[]
const depSelects = () => screen.getAllByLabelText('الإدارة') as HTMLSelectElement[]

describe('UserFormModal — الإدارات والأدوار (migration 0052)', () => {
  it('يعرض الأدوار النظامية فقط ويرسل كل التعيينات عند الإضافة', async () => {
    mocks.roleOptions = [OFFICE, ADMIN, CHAIR]
    const user = userEvent.setup()
    const { onSubmitCreate } = renderModal({ departments: DEPARTMENTS })

    await user.type(screen.getByLabelText(/الاسم الأول/), 'معاذ')
    await user.type(screen.getByLabelText(/الاسم الأوسط/), 'محمد')
    await user.type(screen.getByLabelText(/اسم العائلة/), 'العتيبي')
    await user.type(emailInput(), 'moath@wadimakkah.sa')
    await user.click(screen.getByRole('button', { name: 'إضافة إدارة ودور' }))
    await user.click(screen.getByRole('button', { name: 'إضافة إدارة ودور' }))
    expect(screen.queryByRole('option', { name: /رئيس اللجنة/ })).not.toBeInTheDocument()
    await user.selectOptions(depSelects()[0], 'd-office')
    await user.selectOptions(roleSelects()[0], 'r-office')
    await user.selectOptions(depSelects()[1], 'd-legal')
    await user.selectOptions(roleSelects()[1], 'r-admin')
    await user.click(screen.getByRole('button', { name: 'إضافة المستخدم' }))

    expect(onSubmitCreate).toHaveBeenCalledWith(
      expect.objectContaining({
        assignments: [
          { role_id: 'r-office', dep_id: 'd-office' },
          { role_id: 'r-admin', dep_id: 'd-legal' },
        ],
        dep_id: 'd-office',
      }),
    )
  })

  it('لا يرسل التعيينات عند التعديل لو لم يغيّرها المسؤول', async () => {
    mocks.roleOptions = [OFFICE, ADMIN]
    const user = userEvent.setup()
    const { onSubmitEdit } = renderModal({
      departments: DEPARTMENTS,
      user: {
        ...EXISTING_USER,
        role: OFFICE,
        roles: [OFFICE, ADMIN],
        dep_id: 'd-office',
        assignments: [
          { role: OFFICE, department: OFFICE_DEP },
          { role: ADMIN, department: LEGAL },
        ],
      } as unknown as User,
    })
    expect(roleSelects().map((s) => s.value)).toEqual(['r-office', 'r-admin'])
    expect(depSelects().map((s) => s.value)).toEqual(['d-office', 'd-legal'])

    await user.click(saveEdit())
    expect(onSubmitEdit).toHaveBeenCalledTimes(1)
    expect(onSubmitEdit.mock.calls[0][0]).not.toHaveProperty('assignments')
  })

  it('يرسل التعيينات كاملة لو عدّلها المسؤول', async () => {
    mocks.roleOptions = [OFFICE, ADMIN]
    const user = userEvent.setup()
    const { onSubmitEdit } = renderModal({
      departments: DEPARTMENTS,
      user: {
        ...EXISTING_USER,
        role: OFFICE,
        roles: [OFFICE],
        dep_id: 'd-office',
        assignments: [{ role: OFFICE, department: OFFICE_DEP }],
      } as unknown as User,
    })
    await user.click(screen.getByRole('button', { name: 'إضافة إدارة ودور' }))
    await user.selectOptions(depSelects()[1], 'd-legal')
    await user.selectOptions(roleSelects()[1], 'r-admin')
    await user.click(saveEdit())
    expect(onSubmitEdit).toHaveBeenCalledWith(
      expect.objectContaining({
        assignments: [
          { role_id: 'r-office', dep_id: 'd-office' },
          { role_id: 'r-admin', dep_id: 'd-legal' },
        ],
      }),
    )
  })

  it('يجلب تعيينات المستخدم كاملة لو الشاشة مرّرت دوره الحالي فقط', async () => {
    mocks.roleOptions = [OFFICE, ADMIN]
    mocks.userDetail = {
      ...EXISTING_USER,
      role: OFFICE,
      roles: [OFFICE, ADMIN],
      dep_id: 'd-office',
      assignments: [
        { role: OFFICE, department: OFFICE_DEP },
        { role: ADMIN, department: LEGAL },
      ],
    }
    const user = userEvent.setup()
    const { onSubmitEdit } = renderModal({
      departments: DEPARTMENTS,
      // مثل أعضاء الإدارة: roles/assignments غير محمّلة (null)
      user: { ...EXISTING_USER, role: OFFICE, roles: null, dep_id: 'd-office' } as unknown as User,
    })
    await screen.findAllByLabelText('الدور')
    await vi.waitFor(() => expect(roleSelects()).toHaveLength(2))
    expect(roleSelects().map((s) => s.value)).toEqual(['r-office', 'r-admin'])

    // لم يغيّر التعيينات → لا تُرسل (حتى لا تُستبدل بقائمة ناقصة)
    await user.click(saveEdit())
    expect(onSubmitEdit.mock.calls[0][0]).not.toHaveProperty('assignments')
  })
})
