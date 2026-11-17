import { afterEach, describe, expect, it, vi } from 'vitest'
import { countChars, fileExtension, isEmptyTicketDoc, newClientMessageId, ticketPlainText } from './ticketContent'
import type { TicketDoc } from '@/types/tickets'

const p = (...content: TicketDoc[]): TicketDoc => ({ type: 'paragraph', content })
const t = (text: string): TicketDoc => ({ type: 'text', text })

describe('ticketPlainText — نفس plain_text بالباك-إند', () => {
  it('كل فقرة بسطر، والفقرات الفاضية تُتجاهل', () => {
    const doc: TicketDoc = { type: 'doc', content: [p(t('السطر الأول')), p(), p(t('الثاني'))] }
    expect(ticketPlainText(doc)).toBe('السطر الأول\nالثاني')
  })

  it('القوائم وhardBreak والتنسيق', () => {
    const doc: TicketDoc = {
      type: 'doc',
      content: [
        p({ type: 'text', text: 'عريض', marks: [{ type: 'bold' }] }, { type: 'hardBreak' }, t('بعده')),
        {
          type: 'bulletList',
          content: [
            { type: 'listItem', content: [p(t('أ'))] },
            { type: 'listItem', content: [p(t('ب'))] },
          ],
        },
      ],
    }
    expect(ticketPlainText(doc)).toBe('عريض\nبعده\nأ\nب')
  })

  it('null أو مستند فاضي = نص فاضي', () => {
    expect(ticketPlainText(null)).toBe('')
    expect(isEmptyTicketDoc({ type: 'doc', content: [p(t('   '))] })).toBe(true)
    expect(isEmptyTicketDoc({ type: 'doc', content: [p(t('نص'))] })).toBe(false)
  })
})

describe('countChars', () => {
  it('يعدّ الإيموجي حرفًا واحدًا مثل len بالبايثون', () => {
    expect('👍'.length).toBe(2)
    expect(countChars('👍')).toBe(1)
    expect(countChars('مرحبا')).toBe(5)
  })
})

describe('newClientMessageId', () => {
  afterEach(() => vi.unstubAllGlobals())

  const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

  it('يرجع UUID v4', () => {
    expect(newClientMessageId()).toMatch(UUID_V4)
  })

  it('يشتغل بدون crypto.randomUUID (صفحة HTTP غير آمنة)', () => {
    const realCrypto = globalThis.crypto
    vi.stubGlobal('crypto', { getRandomValues: realCrypto.getRandomValues.bind(realCrypto) })
    expect(typeof globalThis.crypto.randomUUID).toBe('undefined')
    const a = newClientMessageId()
    const b = newClientMessageId()
    expect(a).toMatch(UUID_V4)
    expect(a).not.toBe(b)
  })
})

describe('fileExtension', () => {
  it('امتداد بأحرف صغيرة مع النقطة', () => {
    expect(fileExtension('Screen.PNG')).toBe('.png')
    expect(fileExtension('report.final.xlsx')).toBe('.xlsx')
    expect(fileExtension('README')).toBe('')
  })
})
