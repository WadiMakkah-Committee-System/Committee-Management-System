import type { ApiErrorShape, UserRole } from '@/types'

/** دمج أسماء classes بشرط تجاهل القيم الفارغة/false — بديل خفيف عن clsx للاستخدام الداخلي. */
export function cn(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(' ')
}

/** أسماء الأدوار بالعربية — تُستخدم في الجداول والشارات وقوائم الاختيار. */
export const ROLE_LABELS: Record<UserRole, string> = {
  super_admin: 'سوبر أدمن',
  admin: 'مسؤول إدارة',
  executive_president: 'رئيس تنفيذي',
  executive_office_manager: 'مدير المكتب التنفيذي',
  executive_office_secretary: 'سكرتير المكتب التنفيذي',
}

export const ROLE_OPTIONS: { value: UserRole; label: string }[] = (
  Object.keys(ROLE_LABELS) as UserRole[]
).map((value) => ({ value, label: ROLE_LABELS[value] }))

/** يستخرج رسالة خطأ عربية واضحة من أي شكل استجابة خطأ محتمل من الـ API. */
export function extractErrorMessage(error: unknown): string {
  const fallback = 'حدث خطأ غير متوقع، حاول مرة أخرى'

  if (typeof error === 'object' && error !== null && 'response' in error) {
    const response = (error as { response?: { data?: ApiErrorShape; status?: number } }).response
    const data = response?.data

    if (!data) {
      if (response?.status === 0 || response === undefined) {
        return 'تعذّر الاتصال بالخادم — تحقق من اتصالك بالإنترنت'
      }
      return fallback
    }

    if (typeof data.detail === 'string') {
      return data.detail
    }

    if (Array.isArray(data.detail) && data.detail.length > 0) {
      return data.detail.map((d) => d.msg).join('، ')
    }
  }

  if (error instanceof Error) {
    return error.message
  }

  return fallback
}

export function getInitials(firstName: string, lastName: string): string {
  return `${firstName.charAt(0)}${lastName.charAt(0)}`.toUpperCase()
}

export function formatDate(value: string | null): string {
  if (!value) return '—'
  return new Intl.DateTimeFormat('ar-SA-u-ca-gregory-nu-latn', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  }).format(new Date(value))
}

export function formatDateTime(value: string | null): string {
  if (!value) return '—'
  return new Intl.DateTimeFormat('ar-SA-u-ca-gregory-nu-latn', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}
