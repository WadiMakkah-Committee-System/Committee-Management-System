import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AxiosError, AxiosHeaders } from 'axios'
import { ticketsKeys } from '@/hooks/useTickets'
import { useTicketOutbox } from './useTicketOutbox'
import { makeMessage, makeTicket, textDoc } from './ticketFixtures.test-utils'
import type { TicketMessage } from '@/types/tickets'

const api = vi.hoisted(() => ({ postTicketMessage: vi.fn() }))

vi.mock('@/api/tickets', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/tickets')>()
  return { ...actual, postTicketMessage: api.postTicketMessage }
})

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  client.setQueryData<TicketMessage[]>(ticketsKeys.messages('t1'), [makeMessage({ is_description: true })])
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  const hook = renderHook(() => useTicketOutbox('t1'), { wrapper })
  return { client, hook }
}

/** خطأ axios بنفس شكل رد الباك-إند ({detail}). */
function apiError(status: number, detail: string) {
  const headers = new AxiosHeaders()
  return new AxiosError('fail', 'ERR', undefined, undefined, {
    status,
    statusText: '',
    headers,
    config: { headers },
    data: { detail },
  })
}

const outgoing = { doc: textDoc('شكرًا'), files: [], isInternal: false, statusAfter: null }

describe('useTicketOutbox — الإرسال المتفائل', () => {
  beforeEach(() => {
    api.postTicketMessage.mockReset()
  })

  it('الرسالة تظهر "جاري الإرسال" ثم تنتقل للمحادثة والتذكرة تتحدّث', async () => {
    let resolve!: (value: unknown) => void
    api.postTicketMessage.mockReturnValue(new Promise((r) => (resolve = r)))
    const { client, hook } = setup()

    let sending!: Promise<boolean>
    act(() => {
      sending = hook.result.current.send(outgoing)
    })
    expect(hook.result.current.entries).toHaveLength(1)
    expect(hook.result.current.entries[0].status).toBe('sending')
    const clientId = hook.result.current.entries[0].clientId
    // TanStack Query يبدأ mutationFn بعد microtask.
    await waitFor(() =>
      expect(api.postTicketMessage).toHaveBeenCalledWith(
        't1',
        expect.objectContaining({ client_message_id: clientId, is_internal: false, status_after: null }),
      ),
    )

    const saved = makeMessage({ message_id: 'm2', client_message_id: clientId, body_json: textDoc('شكرًا') })
    await act(async () => {
      resolve({ message: saved, ticket: makeTicket({ status: 'in_progress' }) })
      await expect(sending).resolves.toBe(true)
    })

    expect(hook.result.current.entries).toHaveLength(0)
    const messages = client.getQueryData<TicketMessage[]>(ticketsKeys.messages('t1'))
    expect(messages?.map((m) => m.message_id)).toEqual(['m1', 'm2'])
    expect(client.getQueryData(ticketsKeys.detail('t1'))).toMatchObject({ status: 'in_progress' })
  })

  it('ما تتكرر الرسالة لو وصلت بإعادة جلب قبل رد الإرسال', async () => {
    const { client, hook } = setup()
    const saved = makeMessage({ message_id: 'm2' })
    client.setQueryData<TicketMessage[]>(ticketsKeys.messages('t1'), (cur) => [...(cur ?? []), saved])
    api.postTicketMessage.mockResolvedValue({ message: saved, ticket: makeTicket() })

    await act(async () => {
      await hook.result.current.send(outgoing)
    })
    const messages = client.getQueryData<TicketMessage[]>(ticketsKeys.messages('t1'))
    expect(messages?.filter((m) => m.message_id === 'm2')).toHaveLength(1)
  })

  it('الفشل يبقي الرسالة بعلامة فشل وسبب الرفض، وإعادة المحاولة بنفس المعرّف', async () => {
    api.postTicketMessage.mockRejectedValueOnce(apiError(409, 'التذكرة مغلقة'))
    const { hook } = setup()

    await act(async () => {
      await hook.result.current.send(outgoing)
    })
    const [failed] = hook.result.current.entries
    expect(failed.status).toBe('failed')
    expect(failed.error).toBe('التذكرة مغلقة')

    api.postTicketMessage.mockResolvedValueOnce({
      message: makeMessage({ message_id: 'm3', client_message_id: failed.clientId }),
      ticket: makeTicket(),
    })
    act(() => hook.result.current.retry(failed.clientId))
    await waitFor(() => expect(hook.result.current.entries).toHaveLength(0))

    const ids = api.postTicketMessage.mock.calls.map((call) => call[1].client_message_id)
    expect(ids).toEqual([failed.clientId, failed.clientId])
  })

  it('حذف رسالة فاشلة يشيلها من الصادر', async () => {
    api.postTicketMessage.mockRejectedValueOnce(new Error('network'))
    const { hook } = setup()
    await act(async () => {
      await hook.result.current.send(outgoing)
    })
    const [failed] = hook.result.current.entries
    act(() => hook.result.current.discard(failed.clientId))
    expect(hook.result.current.entries).toHaveLength(0)
  })

  it('الملاحظة الداخلية ما تُرسل معها حالة بعد الرد', async () => {
    api.postTicketMessage.mockResolvedValue({ message: makeMessage({ message_id: 'm9' }), ticket: makeTicket() })
    const { hook } = setup()
    await act(async () => {
      await hook.result.current.send({ ...outgoing, isInternal: true, statusAfter: 'resolved' })
    })
    expect(api.postTicketMessage).toHaveBeenCalledWith(
      't1',
      expect.objectContaining({ is_internal: true, status_after: null }),
    )
  })
})
