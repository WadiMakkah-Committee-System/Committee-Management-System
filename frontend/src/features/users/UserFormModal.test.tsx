import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ToastProvider } from '@/components/ui/Toast'
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
  it('يملأ كلمة مرور مؤقتة مطابقة للسياسة عند فتح نموذج الإضافة', () => {
    renderModal()
    const password = passwordInput().value
    expect(password).toHaveLength(12)
    expect(password).toMatch(/[A-Z]/)
    expect(password).toMatch(/[a-z]/)
    expect(password).toMatch(/[0-9]/)
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

const roleCheckbox = (label: RegExp) => screen.getByRole('checkbox', { name: label })
const saveEdit = () => screen.getByRole('button', { name: 'حفظ التعديلات' })

describe('UserFormModal — تعدد الأدوار', () => {
  it('يعرض الأدوار النظامية فقط ويرسل كل الأدوار المختارة عند الإضافة', async () => {
    mocks.roleOptions = [OFFICE, ADMIN, CHAIR]
    const user = userEvent.setup()
    const { onSubmitCreate } = renderModal()

    expect(screen.queryByRole('checkbox', { name: /رئيس اللجنة/ })).not.toBeInTheDocument()
    await user.type(screen.getByLabelText(/الاسم الأول/), 'نائب')
    await user.type(screen.getByLabelText(/الاسم الأوسط/), 'الرئيس')
    await user.type(screen.getByLabelText(/اسم العائلة/), 'التنفيذي')
    await user.type(emailInput(), 'deputy@wadimakkah.sa')
    await user.click(roleCheckbox(/مدير المكتب التنفيذي/))
    await user.click(roleCheckbox(/مسؤول إدارة/))
    await user.click(screen.getByRole('button', { name: 'إضافة المستخدم' }))

    expect(onSubmitCreate).toHaveBeenCalledWith(expect.objectContaining({ role_ids: ['r-office', 'r-admin'] }))
  })

  it('لا يرسل الأدوار عند التعديل لو لم يغيّرها المسؤول', async () => {
    mocks.roleOptions = [OFFICE, ADMIN]
    const user = userEvent.setup()
    const { onSubmitEdit } = renderModal({
      user: { ...EXISTING_USER, role: OFFICE, roles: [OFFICE, ADMIN] } as unknown as User,
    })
    expect(roleCheckbox(/مدير المكتب التنفيذي/)).toBeChecked()
    expect(roleCheckbox(/مسؤول إدارة/)).toBeChecked()

    await user.click(saveEdit())
    expect(onSubmitEdit).toHaveBeenCalledTimes(1)
    expect(onSubmitEdit.mock.calls[0][0]).not.toHaveProperty('role_ids')
  })

  it('يرسل قائمة الأدوار كاملة لو عدّلها المسؤول', async () => {
    mocks.roleOptions = [OFFICE, ADMIN]
    const user = userEvent.setup()
    const { onSubmitEdit } = renderModal({
      user: { ...EXISTING_USER, role: OFFICE, roles: [OFFICE] } as unknown as User,
    })
    await user.click(roleCheckbox(/مسؤول إدارة/))
    await user.click(saveEdit())
    expect(onSubmitEdit).toHaveBeenCalledWith(expect.objectContaining({ role_ids: ['r-office', 'r-admin'] }))
  })

  it('يجلب أدوار المستخدم كاملة لو الشاشة مرّرت دوره الحالي فقط', async () => {
    mocks.roleOptions = [OFFICE, ADMIN]
    mocks.userDetail = { ...EXISTING_USER, role: OFFICE, roles: [OFFICE, ADMIN] }
    const user = userEvent.setup()
    const { onSubmitEdit } = renderModal({
      // مثل أعضاء الإدارة: roles غير محمّلة (null)
      user: { ...EXISTING_USER, role: OFFICE, roles: null } as unknown as User,
    })
    expect(await screen.findByRole('checkbox', { name: /مسؤول إدارة/ })).toBeChecked()
    expect(roleCheckbox(/مدير المكتب التنفيذي/)).toBeChecked()

    // لم يغيّر الأدوار → لا تُرسل (حتى لا تُستبدل أدواره بقائمة ناقصة)
    await user.click(saveEdit())
    expect(onSubmitEdit.mock.calls[0][0]).not.toHaveProperty('role_ids')
  })
})
