import { describe, expect, it, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ToastProvider } from '@/components/ui/Toast'
import type { MeetingMinutes, MinutesSection } from '@/types'
import { sampleSections } from './fixtures.test-utils'
import { useGeneralMinutesState } from './useGeneralMinutesState'
import { withData } from './types'

const api = vi.hoisted(() => ({
  updateMinutesSection: vi.fn(),
  updateMinutesSections: vi.fn(),
}))

vi.mock('@/api/meetingMinutes', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/meetingMinutes')>()
  return { ...actual, updateMinutesSection: api.updateMinutesSection, updateMinutesSections: api.updateMinutesSections }
})

function minutesWith(sections: MinutesSection[]): MeetingMinutes {
  return {
    minutes_id: 'mn',
    meeting_id: 'mt',
    template_id: 'general',
    template_name: 'القالب العام',
    stage: 'preparing',
    owner: null,
    sections,
    reviewers: [],
    signatures: [],
    sent_to_review_at: null,
    approved_at: null,
    sent_for_signature_at: null,
    completed_at: null,
    created_at: '2025-01-16T10:00:00Z',
    updated_at: '2025-01-16T10:00:00Z',
  }
}

function setup(sections = sampleSections()) {
  const client = new QueryClient()
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <ToastProvider>{children}</ToastProvider>
    </QueryClientProvider>
  )
  return renderHook(
    () => useGeneralMinutesState({ meetingId: 'mt', minutes: minutesWith(sections), remoteSections: null, remoteSection: null }),
    { wrapper },
  )
}

const header = () => sampleSections()[0]

describe('useGeneralMinutesState', () => {
  beforeEach(() => {
    api.updateMinutesSection.mockReset()
    api.updateMinutesSections.mockReset()
  })

  it('يحفظ القسم المعدّل وحده بعد توقف الكتابة، ويأخذ rev الجديد من الخادم', async () => {
    api.updateMinutesSection.mockImplementation(async (_id: string, section: MinutesSection) =>
      minutesWith(sampleSections().map((s) => (s.id === section.id ? { ...section, rev: (section.rev ?? 0) + 1 } : s))),
    )
    const { result } = setup()
    act(() => result.current.updateSection(withData(header(), { place_text: 'قاعة 1' })))
    act(() => result.current.updateSection(withData(header(), { place_text: 'قاعة 2' })))
    expect(api.updateMinutesSection).not.toHaveBeenCalled() // ينتظر توقف الكتابة

    await waitFor(() => expect(api.updateMinutesSection).toHaveBeenCalledTimes(1), { timeout: 3000 })
    const [, sent] = api.updateMinutesSection.mock.calls[0]
    expect(sent.id).toBe('h')
    expect(sent.data.place_text).toBe('قاعة 2')
    expect(sent.rev).toBe(1)
    await waitFor(() => expect(result.current.sections.find((s) => s.id === 'h')?.rev).toBe(2))
    expect(result.current.error).toBeNull()
  })

  it('تعارض النسخ (409) يعرض نسخة الخادم الحالية بدل الكتابة فوقها', async () => {
    const serverVersion = withData({ ...header(), rev: 5 }, { place_text: 'من عضو آخر' })
    api.updateMinutesSection.mockRejectedValue({
      response: { status: 409, data: { detail: { message: 'تعارض', current_section: serverVersion } } },
    })
    const { result } = setup()
    act(() => result.current.updateSection(withData(header(), { place_text: 'تعديلي' })))
    await waitFor(() => expect(result.current.sections.find((s) => s.id === 'h')?.data?.place_text).toBe('من عضو آخر'), {
      timeout: 3000,
    })
    expect(result.current.sections.find((s) => s.id === 'h')?.rev).toBe(5)
  })

  it('الكتابة أثناء الحفظ لا تضيع — يُعاد الحفظ بالـrev الجديد', async () => {
    let release: (() => void) | undefined
    api.updateMinutesSection.mockImplementation(
      (_id: string, section: MinutesSection) =>
        new Promise((resolve) => {
          release = () =>
            resolve(minutesWith(sampleSections().map((s) => (s.id === section.id ? { ...section, rev: (section.rev ?? 0) + 1 } : s))))
        }),
    )
    const { result } = setup()
    act(() => result.current.updateSection(withData(header(), { place_text: 'أولى' })))
    await waitFor(() => expect(api.updateMinutesSection).toHaveBeenCalledTimes(1), { timeout: 3000 })

    // المستخدم يكتب والطلب الأول ما رجع.
    act(() => result.current.updateSection(withData(result.current.sections[0], { place_text: 'ثانية' })))
    await act(async () => release?.())
    expect(result.current.sections[0].data?.place_text).toBe('ثانية')
    expect(result.current.sections[0].rev).toBe(2)

    await waitFor(() => expect(api.updateMinutesSection).toHaveBeenCalledTimes(2), { timeout: 3000 })
    const [, second] = api.updateMinutesSection.mock.calls[1]
    expect(second.data.place_text).toBe('ثانية')
    expect(second.rev).toBe(2)
    await act(async () => release?.())
  })

  it('حذف موضوع يحفظ القائمة كاملة بدونه', async () => {
    api.updateMinutesSections.mockImplementation(async (_id: string, sections: MinutesSection[]) => minutesWith(sections))
    const { result } = setup()
    await act(async () => result.current.deleteSection('tp1'))
    expect(api.updateMinutesSections).toHaveBeenCalledTimes(1)
    const [, sent] = api.updateMinutesSections.mock.calls[0]
    expect(sent.map((s: MinutesSection) => s.id)).not.toContain('tp1')
    expect(result.current.sections.map((s) => s.id)).not.toContain('tp1')
  })
})
