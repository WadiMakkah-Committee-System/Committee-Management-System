import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { ToastProvider } from '@/components/ui/Toast'
import { TicketConversation } from './TicketConversation'
import { TicketRichText } from './ticketEditor'
import { REQUESTER, SUPPORT, makeMessage, textDoc } from './ticketFixtures.test-utils'
import type { OutboxEntry } from './useTicketOutbox'
import type { TicketDoc } from '@/types/tickets'

// jsdom ما فيه scrollIntoView.
Element.prototype.scrollIntoView = vi.fn()

function renderConversation(props: Partial<Parameters<typeof TicketConversation>[0]> = {}) {
  const onRetry = vi.fn()
  const onDiscard = vi.fn()
  render(
    <ToastProvider>
      <TicketConversation
        ticketId="t1"
        messages={[]}
        outbox={[]}
        currentUser={SUPPORT}
        viewer="support"
        onRetry={onRetry}
        onDiscard={onDiscard}
        {...props}
      />
    </ToastProvider>,
  )
  return { onRetry, onDiscard }
}

function entry(overrides: Partial<OutboxEntry> = {}): OutboxEntry {
  return {
    clientId: 'c1',
    doc: textDoc('رد قيد الإرسال'),
    files: [],
    isInternal: false,
    statusAfter: null,
    status: 'sending',
    error: null,
    createdAt: '2026-11-17T09:00:00Z',
    ...overrides,
  }
}

describe('TicketConversation', () => {
  it('الوصف أولًا والملاحظة الداخلية بتسمية واضحة', () => {
    renderConversation({
      messages: [
        makeMessage({ message_id: 'm1', is_description: true, body_json: textDoc('وصف المشكلة') }),
        makeMessage({
          message_id: 'm2',
          author: SUPPORT,
          author_side: 'support',
          is_internal: true,
          body_json: textDoc('نراجع السجلات'),
        }),
      ],
    })
    expect(screen.getByText('وصف التذكرة')).toBeInTheDocument()
    expect(screen.getByText('وصف المشكلة')).toBeInTheDocument()
    expect(screen.getByText(/ملاحظة داخلية — ما يشوفها مقدّم الطلب/)).toBeInTheDocument()
  })

  it('مقدّم الطلب يشوف شارة "الدعم الفني" على ردود الدعم', () => {
    renderConversation({
      currentUser: REQUESTER,
      viewer: 'requester',
      messages: [makeMessage({ message_id: 'm2', author: SUPPORT, author_side: 'support', body_json: textDoc('تم') })],
    })
    expect(screen.getByText('الدعم الفني')).toBeInTheDocument()
  })

  it('رسالة الصادر المحفوظة فعلًا ما تتكرر', () => {
    renderConversation({
      messages: [makeMessage({ message_id: 'm2', author: SUPPORT, client_message_id: 'c1', body_json: textDoc('رد قيد الإرسال') })],
      outbox: [entry()],
    })
    expect(screen.getAllByText('رد قيد الإرسال')).toHaveLength(1)
    expect(screen.queryByText('جاري الإرسال…')).not.toBeInTheDocument()
  })

  it('الرسالة الفاشلة: السبب وإعادة المحاولة والحذف', () => {
    const { onRetry, onDiscard } = renderConversation({
      outbox: [entry({ status: 'failed', error: 'التذكرة مغلقة' })],
    })
    expect(screen.getByText(/فشل الإرسال — التذكرة مغلقة/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /إعادة المحاولة/ }))
    fireEvent.click(screen.getByRole('button', { name: /حذف/ }))
    expect(onRetry).toHaveBeenCalledWith('c1')
    expect(onDiscard).toHaveBeenCalledWith('c1')
  })
})

describe('TicketRichText — عرض بدون HTML خام', () => {
  it('يعرض التنسيق والقوائم كعناصر React', () => {
    const doc: TicketDoc = {
      type: 'doc',
      content: [
        { type: 'paragraph', content: [{ type: 'text', text: 'مهم', marks: [{ type: 'bold' }] }] },
        {
          type: 'orderedList',
          content: [{ type: 'listItem', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'خطوة' }] }] }],
        },
      ],
    }
    const { container } = render(<TicketRichText doc={doc} />)
    expect(container.querySelector('strong')?.textContent).toBe('مهم')
    expect(container.querySelector('ol li')?.textContent).toBe('خطوة')
  })

  it('النص اللي شكله HTML يظهر نصًا (ما يُنفَّذ)', () => {
    const { container } = render(<TicketRichText doc={textDoc('<img src=x onerror=alert(1)>')} />)
    expect(container.querySelector('img')).toBeNull()
    expect(container.textContent).toContain('<img src=x onerror=alert(1)>')
  })

  it('عنصر غير مدعوم يرجع للنص المجرّد بدل ما تنكسر المحادثة', () => {
    const doc: TicketDoc = {
      type: 'doc',
      content: [{ type: 'mysteryNode', content: [{ type: 'text', text: 'نص احتياطي' }] }],
    }
    const { container } = render(<TicketRichText doc={doc} />)
    expect(container.textContent).toContain('نص احتياطي')
  })
})
