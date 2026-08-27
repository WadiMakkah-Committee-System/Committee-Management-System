import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemberPicker } from './MemberPicker'
import type { User } from '@/types'

function makeUser(overrides: Partial<User>): User {
  return {
    user_id: 'u-1',
    first_name: 'سارة',
    middle_name: '',
    last_name: 'العتيبي',
    username: 'sarah',
    email: 'sarah@example.com',
    role: { role_id: 'r-1', name: 'admin', description: null, is_super_admin: false },
    dep_id: null,
    department: null,
    job_title_id: null,
    job_title: null,
    status: 'active',
    must_change_password: false,
    last_login_at: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

const USERS: User[] = [
  makeUser({ user_id: 'u-1', first_name: 'سارة', last_name: 'العتيبي', email: 'sarah@example.com' }),
  makeUser({ user_id: 'u-2', first_name: 'محمد', last_name: 'القحطاني', email: 'mohammed@example.com' }),
]

/** Props مشتركة لاختيار الرئيس — بلا رئيس محدد افتراضيًا، تُستبدَل عند الحاجة داخل كل اختبار. */
const noopChair = { chairId: null, onChairChange: () => {} }

describe('MemberPicker', () => {
  it('يعرض عدّاد "0 محدد" عند عدم اختيار أي عضو', () => {
    render(<MemberPicker users={USERS} selected={[]} onChange={() => {}} {...noopChair} />)
    expect(screen.getByText('0 محدد')).toBeInTheDocument()
  })

  it('يستدعي onChange بالمعرّف الصحيح عند اختيار عضو', async () => {
    const onChange = vi.fn()
    render(<MemberPicker users={USERS} selected={[]} onChange={onChange} {...noopChair} />)

    await userEvent.click(screen.getByText('سارة العتيبي'))
    expect(onChange).toHaveBeenCalledWith(['u-1'])
  })

  it('يعرض رقائق الأعضاء المحدَّدين ويحدّث العدّاد', () => {
    render(<MemberPicker users={USERS} selected={['u-1', 'u-2']} onChange={() => {}} {...noopChair} />)
    expect(screen.getByText('2 محدد')).toBeInTheDocument()
    expect(screen.getAllByText('سارة العتيبي').length).toBeGreaterThan(0)
  })

  it('يزيل العضو عند الضغط على زر الإزالة بالرقاقة', async () => {
    const onChange = vi.fn()
    render(<MemberPicker users={USERS} selected={['u-1']} onChange={onChange} {...noopChair} />)

    await userEvent.click(screen.getByLabelText('إزالة سارة العتيبي'))
    expect(onChange).toHaveBeenCalledWith([])
  })

  it('يعرض رسالة الخطأ الممرَّرة', () => {
    render(<MemberPicker users={USERS} selected={[]} onChange={() => {}} {...noopChair} error="اختاري عضوًا واحدًا على الأقل" />)
    expect(screen.getByText('اختاري عضوًا واحدًا على الأقل')).toBeInTheDocument()
  })

  it('يفلتر القائمة بالبحث بالاسم', async () => {
    render(<MemberPicker users={USERS} selected={[]} onChange={() => {}} {...noopChair} />)
    await userEvent.type(screen.getByPlaceholderText('ابحث بالاسم أو البريد الإلكتروني...'), 'محمد')
    expect(screen.getByText('محمد القحطاني')).toBeInTheDocument()
    expect(screen.queryByText('سارة العتيبي')).not.toBeInTheDocument()
  })

  it('يعرض المسمى الوظيفي بدل البريد الإلكتروني عند توفره', () => {
    const usersWithDetails: User[] = [
      makeUser({
        user_id: 'u-3',
        first_name: 'نورة',
        last_name: 'الحربي',
        email: 'noura@example.com',
        department: { dep_id: 'd-1', name: 'إدارة الجودة', code: null } as User['department'],
        job_title: { job_title_id: 'jt-1', name: 'محلل جودة' } as User['job_title'],
      }),
    ]
    render(<MemberPicker users={usersWithDetails} selected={[]} onChange={() => {}} {...noopChair} />)
    expect(screen.getByText('محلل جودة')).toBeInTheDocument()
    expect(screen.queryByText('noura@example.com')).not.toBeInTheDocument()
  })

  it('يفلتر القائمة بالبحث بالمسمى الوظيفي', async () => {
    const usersWithDetails: User[] = [
      ...USERS,
      makeUser({
        user_id: 'u-3',
        first_name: 'نورة',
        last_name: 'الحربي',
        email: 'noura@example.com',
        job_title: { job_title_id: 'jt-1', name: 'محلل جودة' } as User['job_title'],
      }),
    ]
    render(<MemberPicker users={usersWithDetails} selected={[]} onChange={() => {}} {...noopChair} />)
    await userEvent.type(screen.getByPlaceholderText('ابحث بالاسم أو البريد الإلكتروني...'), 'محلل جودة')
    expect(screen.getByText('نورة الحربي')).toBeInTheDocument()
    expect(screen.queryByText('سارة العتيبي')).not.toBeInTheDocument()
  })

  it('يجمّع الأعضاء حسب الإدارة ويضع "بدون إدارة" بالنهاية', () => {
    const usersWithDepts: User[] = [
      makeUser({
        user_id: 'u-4',
        first_name: 'خالد',
        last_name: 'الدوسري',
        email: 'khalid@example.com',
        department: { dep_id: 'd-2', name: 'إدارة الموارد البشرية', code: null } as User['department'],
      }),
      makeUser({ user_id: 'u-5', first_name: 'ريم', last_name: 'السبيعي', email: 'reem@example.com', department: null }),
    ]
    render(<MemberPicker users={usersWithDepts} selected={[]} onChange={() => {}} {...noopChair} />)
    const headers = screen.getAllByText(/إدارة الموارد البشرية|بدون إدارة/)
    expect(headers[0]).toHaveTextContent('إدارة الموارد البشرية')
    expect(headers[1]).toHaveTextContent('بدون إدارة')
  })

  it('لا يعرض قسم اختيار الرئيس إلا بعد اختيار عضو واحد على الأقل', () => {
    const { rerender } = render(<MemberPicker users={USERS} selected={[]} onChange={() => {}} {...noopChair} />)
    expect(screen.queryByText('رئيس اللجنة')).not.toBeInTheDocument()

    rerender(<MemberPicker users={USERS} selected={['u-1']} onChange={() => {}} {...noopChair} />)
    expect(screen.getByText('رئيس اللجنة')).toBeInTheDocument()
  })

  it('يستدعي onChairChange عند اختيار عضو كرئيس', async () => {
    const onChairChange = vi.fn()
    render(
      <MemberPicker
        users={USERS}
        selected={['u-1', 'u-2']}
        onChange={() => {}}
        chairId={null}
        onChairChange={onChairChange}
      />,
    )
    const radios = screen.getAllByRole('radio')
    await userEvent.click(radios[0])
    expect(onChairChange).toHaveBeenCalledWith('u-1')
  })

  it('يمنع اختيار أكثر من رئيس واحد (Radio بدل Checkbox)', () => {
    render(
      <MemberPicker users={USERS} selected={['u-1', 'u-2']} onChange={() => {}} chairId="u-1" onChairChange={() => {}} />,
    )
    const radios = screen.getAllByRole('radio') as HTMLInputElement[]
    expect(radios).toHaveLength(2)
    expect(radios.filter((r) => r.checked)).toHaveLength(1)
  })

  it('يمسح اختيار الرئيس تلقائيًا عند إزالته من الأعضاء المحدَّدين', async () => {
    const onChange = vi.fn()
    const onChairChange = vi.fn()
    render(
      <MemberPicker
        users={USERS}
        selected={['u-1', 'u-2']}
        onChange={onChange}
        chairId="u-1"
        onChairChange={onChairChange}
      />,
    )
    await userEvent.click(screen.getByLabelText('إزالة سارة العتيبي'))
    expect(onChange).toHaveBeenCalledWith(['u-2'])
    expect(onChairChange).toHaveBeenCalledWith('')
  })

  it('يعرض رسالة خطأ اختيار الرئيس الممرَّرة', () => {
    render(
      <MemberPicker
        users={USERS}
        selected={['u-1']}
        onChange={() => {}}
        chairId={null}
        onChairChange={() => {}}
        chairError="يجب اختيار رئيس للجنة"
      />,
    )
    expect(screen.getByText('يجب اختيار رئيس للجنة')).toBeInTheDocument()
  })
})
