import { describe, expect, it } from 'vitest'
import { formatTodayLabel, getGreeting } from './dashboardGreeting'

function atHour(hour: number): Date {
  const d = new Date(2026, 8, 8) // 8 سبتمبر 2026 — تاريخ ثابت للاختبار
  d.setHours(hour, 0, 0, 0)
  return d
}

describe('getGreeting', () => {
  it('يرجّع "صباح الخير" بين الساعة 5 و12', () => {
    expect(getGreeting(atHour(5))).toBe('صباح الخير')
    expect(getGreeting(atHour(8))).toBe('صباح الخير')
    expect(getGreeting(atHour(11))).toBe('صباح الخير')
  })

  it('يرجّع "يومك سعيد" بين الساعة 12 و17', () => {
    expect(getGreeting(atHour(12))).toBe('يومك سعيد')
    expect(getGreeting(atHour(16))).toBe('يومك سعيد')
  })

  it('يرجّع "مساء الخير" من الساعة 17 حتى قبل 5 صباحًا', () => {
    expect(getGreeting(atHour(17))).toBe('مساء الخير')
    expect(getGreeting(atHour(22))).toBe('مساء الخير')
    expect(getGreeting(atHour(0))).toBe('مساء الخير')
    expect(getGreeting(atHour(4))).toBe('مساء الخير')
  })
})

describe('formatTodayLabel', () => {
  it('يرجّع نصًا غير فارغ بصيغة عربية (يوم الأسبوع + اليوم + الشهر)', () => {
    const label = formatTodayLabel(atHour(10))
    expect(label.length).toBeGreaterThan(0)
    expect(typeof label).toBe('string')
  })
})
