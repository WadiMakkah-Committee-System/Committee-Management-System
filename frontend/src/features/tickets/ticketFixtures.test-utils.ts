import type { Ticket, TicketDoc, TicketMessage } from '@/types/tickets'

/** بيانات اختبار لوحدة التذاكر — بنفس شكل استجابات الباك-إند. */

export const REQUESTER = { user_id: 'u-req', first_name: 'نورة', last_name: 'سالم', email: null }
export const SUPPORT = { user_id: 'u-sup', first_name: 'خالد', last_name: 'الدعم', email: 'sup@example.com' }

export function textDoc(text: string): TicketDoc {
  return { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text }] }] }
}

export function makeTicket(overrides: Partial<Ticket> = {}): Ticket {
  return {
    ticket_id: 't1',
    ticket_number: 'TKT-2026-0001',
    title: 'زر التوقيع ما يظهر',
    ticket_type: 'bug',
    module: 'minutes',
    status: 'new',
    priority: null,
    requester: REQUESTER,
    assignee: null,
    assignee_is_active_support: null,
    created_at: '2026-11-17T08:00:00Z',
    updated_at: '2026-11-17T08:00:00Z',
    last_public_activity_at: '2026-11-17T08:00:00Z',
    resolved_at: null,
    closed_at: null,
    cancelled_at: null,
    viewer: 'requester',
    actions: { can_reply: true, can_add_internal_note: false, can_cancel: true, can_manage: false, can_assign: false },
    ...overrides,
  }
}

export function makeMessage(overrides: Partial<TicketMessage> = {}): TicketMessage {
  return {
    message_id: 'm1',
    ticket_id: 't1',
    author: REQUESTER,
    author_side: 'requester',
    is_internal: false,
    is_description: false,
    body_json: textDoc('رسالة'),
    client_message_id: null,
    created_at: '2026-11-17T08:00:00Z',
    attachments: [],
    ...overrides,
  }
}
