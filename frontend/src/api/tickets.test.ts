import { beforeEach, describe, expect, it, vi } from 'vitest'

const client = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn() }))

vi.mock('@/lib/apiClient', () => ({ apiClient: client, API_BASE_URL: 'http://localhost/api/v1' }))

import { createTicket, fetchSupportTickets, postTicketMessage } from './tickets'

describe('api/tickets — شكل الطلبات كما يقرأها FastAPI', () => {
  beforeEach(() => {
    client.get.mockReset().mockResolvedValue({ data: { items: [], total: 0, limit: 20, offset: 0 } })
    client.post.mockReset().mockResolvedValue({ data: {} })
  })

  it('الحالات المتعددة تُرسل status=…&status=… والبحث الفاضي ما يُرسل', async () => {
    await fetchSupportTickets({ tab: 'all', statuses: ['new', 'in_progress'], q: '  ', limit: 20, offset: 0 })
    const params: URLSearchParams = client.get.mock.calls[0][1].params
    expect(client.get.mock.calls[0][0]).toBe('/tickets')
    expect(params.getAll('status')).toEqual(['new', 'in_progress'])
    expect(params.has('q')).toBe(false)
    expect(params.get('tab')).toBe('all')
  })

  it('الإنشاء multipart: المحتوى JSON والمرفقات بنفس اسم الحقل', async () => {
    const file = new File(['x'], 'shot.png', { type: 'image/png' })
    await createTicket({
      title: 'عنوان التذكرة',
      ticket_type: 'bug',
      module: 'tasks',
      body: { type: 'doc', content: [] },
      client_message_id: 'cid',
      files: [file, file],
    })
    const [url, form] = client.post.mock.calls[0] as [string, FormData]
    expect(url).toBe('/tickets')
    expect(JSON.parse(form.get('body') as string)).toEqual({ type: 'doc', content: [] })
    expect(form.getAll('files')).toHaveLength(2)
    expect(form.get('client_message_id')).toBe('cid')
  })

  it('رد بمرفق فقط: body فاضي، وstatus_after ما يُرسل لو null', async () => {
    await postTicketMessage('t1', {
      body: null,
      is_internal: false,
      status_after: null,
      client_message_id: 'cid',
      files: [new File(['x'], 'a.pdf')],
    })
    const [url, form] = client.post.mock.calls[0] as [string, FormData]
    expect(url).toBe('/tickets/t1/messages')
    expect(form.get('body')).toBe('')
    expect(form.get('is_internal')).toBe('false')
    expect(form.has('status_after')).toBe(false)
  })
})
