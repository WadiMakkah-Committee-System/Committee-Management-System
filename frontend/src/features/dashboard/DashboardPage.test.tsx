import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { DashboardPage } from './DashboardPage'
import { useAuthStore } from '@/store/authStore'
import type { DashboardSummary } from '@/types'

const mockUseDashboardSummary = vi.fn()
vi.mock('@/hooks/useDashboard', () => ({
  useDashboardSummary: () => mockUseDashboardSummary(),
}))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

function renderDashboard() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const emptySummary: DashboardSummary = {
  committees_count: 0,
  committees_preview: [],
  upcoming_meetings_count: 0,
  upcoming_meetings_preview: [],
  pending_votes_count: 0,
  pending_votes_preview: [],
  open_tasks_count: 0,
  open_tasks_preview: [],
  documents_count: 0,
  recent_documents_preview: [],
}

describe('DashboardPage', () => {
  beforeEach(() => {
    mockUseDashboardSummary.mockReset()
    mockNavigate.mockReset()
    useAuthStore.setState({
      user: {
        user_id: 'u1',
        first_name: 'لمى',
        middle_name: 'أ',
        last_name: 'ب',
        username: 'lama',
        email: 'lama@example.com',
        permissions: [],
        permission_scopes: {},
        has_committee_membership_access: false,
        has_any_committee_membership: false,
        role: null,
        status: 'active',
        dep_id: null,
        job_title: null,
        created_at: '',
        updated_at: '',
      } as never,
    })
  })

  it('يعرض هيكل تحميل (Skeleton) أثناء جلب البيانات', () => {
    mockUseDashboardSummary.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
      refetch: vi.fn(),
    })
    const { container } = renderDashboard()
    expect(container.querySelectorAll('[class*="animate-pulse"]').length).toBeGreaterThan(0)
  })

  it('يعرض التحية باسم المستخدم بعد نجاح التحميل', () => {
    mockUseDashboardSummary.mockReturnValue({
      data: emptySummary,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    })
    renderDashboard()
    expect(screen.getByText(/لمى/)).toBeInTheDocument()
  })

  it('يعرض الأعداد الصحيحة ببطاقات الإحصاء', () => {
    mockUseDashboardSummary.mockReturnValue({
      data: { ...emptySummary, committees_count: 3, upcoming_meetings_count: 2 },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    })
    renderDashboard()
    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument()
  })

  it('يعرض حالة فارغة واضحة لكل قسم بلا بيانات', () => {
    mockUseDashboardSummary.mockReturnValue({
      data: emptySummary,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    })
    renderDashboard()
    expect(screen.getByText('لا توجد لجان بعد')).toBeInTheDocument()
    expect(screen.getByText('لا توجد اجتماعات قادمة')).toBeInTheDocument()
    expect(screen.getByText('لا توجد قرارات بانتظارك')).toBeInTheDocument()
    expect(screen.getByText('لا توجد مهام مفتوحة')).toBeInTheDocument()
  })

  it('يعرض رسالة خطأ مع زر إعادة محاولة عند فشل الجلب', () => {
    const refetch = vi.fn()
    mockUseDashboardSummary.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      refetch,
    })
    renderDashboard()
    const retryButton = screen.getByRole('button')
    fireEvent.click(retryButton)
    expect(refetch).toHaveBeenCalled()
  })

  it('ينتقل لصفحة اللجان عند الضغط على بطاقة "لجاني المصرح بها"', () => {
    mockUseDashboardSummary.mockReturnValue({
      data: { ...emptySummary, committees_count: 1 },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    })
    renderDashboard()
    fireEvent.click(screen.getByText('لجاني المصرح بها'))
    expect(mockNavigate).toHaveBeenCalledWith('/committees/approved')
  })

  it('ينتقل لتفاصيل الاجتماع عند الضغط على عنصر بقائمة الاجتماعات القادمة', () => {
    mockUseDashboardSummary.mockReturnValue({
      data: {
        ...emptySummary,
        upcoming_meetings_count: 1,
        upcoming_meetings_preview: [
          {
            meeting_id: 'm1',
            title: 'اجتماع الميزانية',
            scheduled_at: '2026-09-15T10:00:00Z',
            mode: 'remote',
            committee_name: 'لجنة الميزانية',
          },
        ],
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    })
    renderDashboard()
    fireEvent.click(screen.getByText('اجتماع الميزانية'))
    expect(mockNavigate).toHaveBeenCalledWith('/meetings/m1')
  })
})
