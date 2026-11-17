import { describe, expect, it } from 'vitest'
import {
  MANUAL_STATUS_TRANSITIONS,
  isFinalTicketStatus,
  ticketHistoryText,
  ticketStatusLabel,
  ticketStatusTone,
} from './ticketLabels'

describe('أسماء الحالات حسب المشاهد (القسم 4)', () => {
  it('مقدّم الطلب يشوف "تم الإرسال" و"بانتظار ردك"', () => {
    expect(ticketStatusLabel('new', 'requester')).toBe('تم الإرسال')
    expect(ticketStatusLabel('waiting_on_requester', 'requester')).toBe('بانتظار ردك')
  })

  it('الدعم يشوف "جديدة" و"بانتظار رد المستخدم"', () => {
    expect(ticketStatusLabel('new', 'support')).toBe('جديدة')
    expect(ticketStatusLabel('waiting_on_requester', 'support')).toBe('بانتظار رد المستخدم')
  })

  it('اللون التحذيري للطرف اللي الدور عليه', () => {
    expect(ticketStatusTone('new', 'support')).toBe('warning')
    expect(ticketStatusTone('new', 'requester')).toBe('info')
    expect(ticketStatusTone('waiting_on_requester', 'requester')).toBe('warning')
    expect(ticketStatusTone('waiting_on_requester', 'support')).toBe('neutral')
  })
})

describe('الانتقالات اليدوية (نفس _MANUAL_TRANSITIONS بالباك-إند)', () => {
  it('المحلولة والنهائية ما لها انتقال يدوي', () => {
    expect(MANUAL_STATUS_TRANSITIONS.resolved).toEqual([])
    expect(MANUAL_STATUS_TRANSITIONS.closed).toEqual([])
    expect(MANUAL_STATUS_TRANSITIONS.cancelled).toEqual([])
  })

  it('قيد المعالجة ⇄ بانتظار، والكل ← تم الحل', () => {
    expect(MANUAL_STATUS_TRANSITIONS.new).toEqual(['resolved'])
    expect(MANUAL_STATUS_TRANSITIONS.in_progress).toEqual(['waiting_on_requester', 'resolved'])
    expect(MANUAL_STATUS_TRANSITIONS.waiting_on_requester).toEqual(['in_progress', 'resolved'])
  })

  it('isFinalTicketStatus', () => {
    expect(isFinalTicketStatus('closed')).toBe(true)
    expect(isFinalTicketStatus('cancelled')).toBe(true)
    expect(isFinalTicketStatus('resolved')).toBe(false)
  })
})

describe('نص سجل التذكرة', () => {
  it('تغيير الحالة بأسماء الدعم', () => {
    expect(ticketHistoryText({ event: 'status_changed', from_value: 'new', to_value: 'resolved' })).toBe(
      'غيّر الحالة من «جديدة» إلى «تم الحل»',
    )
  })

  it('الإسناد الأول وإعادة الإسناد بالأسماء', () => {
    expect(ticketHistoryText({ event: 'assigned', from_value: null, to_value: 'سارة أحمد' })).toBe(
      'أسند التذكرة إلى سارة أحمد',
    )
    expect(ticketHistoryText({ event: 'assigned', from_value: 'سارة أحمد', to_value: 'خالد علي' })).toBe(
      'أعاد الإسناد من سارة أحمد إلى خالد علي',
    )
  })

  it('الأولوية والنوع والوحدة', () => {
    expect(ticketHistoryText({ event: 'priority_changed', from_value: 'medium', to_value: 'urgent' })).toBe(
      'غيّر الأولوية من «متوسطة» إلى «عاجلة»',
    )
    expect(ticketHistoryText({ event: 'type_changed', from_value: 'inquiry', to_value: 'bug' })).toBe(
      'غيّر النوع من «استفسار» إلى «بلاغ خلل»',
    )
    expect(ticketHistoryText({ event: 'module_changed', from_value: 'tasks', to_value: 'meetings' })).toBe(
      'غيّر الوحدة من «المهام» إلى «الاجتماعات»',
    )
  })
})
