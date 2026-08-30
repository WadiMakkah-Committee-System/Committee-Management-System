import type { ApiErrorShape, RoleSummary, SystemRoleName } from '@/types'

/** دمج أسماء classes بشرط تجاهل القيم الفارغة/false — بديل خفيف عن clsx للاستخدام الداخلي. */
export function cn(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(' ')
}

/**
 * أسماء الأدوار النظامية الخمسة بالعربية — للأدوار المخصَّصة (غير النظامية)
 * الاسم نفسه عربي أصلًا (يُدخله Super Admin عند الإنشاء)، فلا حاجة لترجمته.
 * استخدمي roleLabel() دائمًا بدل الوصول المباشر لهذا الكائن.
 */
const SYSTEM_ROLE_LABELS: Record<SystemRoleName, string> = {
  super_admin: 'سوبر أدمن',
  admin: 'مسؤول إدارة',
  executive_president: 'رئيس تنفيذي',
  executive_office_manager: 'مدير المكتب التنفيذي',
  executive_office_secretary: 'سكرتير المكتب التنفيذي',
}

/** التسمية المعروضة لأي دور — نظامي أو مخصَّص — تُستخدم في الجداول والشارات. */
export function roleLabel(role: Pick<RoleSummary, 'name'> | null): string {
  // مراجعة لاما 2026-08-30: مستخدم بلا دور مُعيَّن (role=null) حالة صالحة الآن.
  if (!role) return 'غير محدد'
  return SYSTEM_ROLE_LABELS[role.name as SystemRoleName] ?? role.name
}

/** تسميات أقسام كتالوج الصلاحيات (تطابق category في backend/db/migrations/0006). */
export const PERMISSION_CATEGORY_LABELS: Record<string, string> = {
  departments: 'الإدارات',
  users: 'المستخدمون',
  job_titles: 'المسميات الوظيفية',
  committees: 'اللجان',
  meetings: 'الاجتماعات',
  tasks: 'المهام',
  decisions: 'القرارات',
  ai_items: 'البنود المستخرجة من الذكاء الاصطناعي',
  documents: 'الوثائق',
  minutes: 'المحاضر',
}

/** ترتيب عرض الأقسام في نموذج إنشاء/تعديل الدور — يطابق ترتيب طلب المتطلبات. */
export const PERMISSION_CATEGORY_ORDER = [
  'departments',
  'users',
  'job_titles',
  'committees',
  'meetings',
  'tasks',
  'decisions',
  'ai_items',
  'documents',
  'minutes',
]

/**
 * درجات فاتح جدًا من ألوان هوية الشركة *يُستخدم كخلفية لبطاقات (بطاقات
 * الإدارات وبطاقات الأدوار والصلاحيات) لإضفاء تمييز بصري خفيف بين البطاقات
 * دون طغيان اللون، حسب طلب العمل. الشفافية منخفضة جدًا (٦٪) عمدًا لتبقى
 * الخلفية "فاتحة جدًا" في كلا الوضعين (فاتح/داكن).
 */
const CARD_TONE_CLASSES = [
  '!bg-brand-primary/5 !border-brand-primary/15',
  '!bg-brand-teal/5 !border-brand-teal/15',
  '!bg-brand-purple/5 !border-brand-purple/15',
  '!bg-brand-orange/5 !border-brand-orange/15',
  '!bg-brand-dark-blue/5 !border-brand-dark-blue/15',
  '!bg-brand-lime/5 !border-brand-lime/15',
] as const

/** ترجع تدرّج لون بطاقة ثابت لكل بطاقة حسب ترتيبها (تدوير على القائمة أعلاه). */
export function cardToneClass(index: number): string {
  return CARD_TONE_CLASSES[index % CARD_TONE_CLASSES.length]
}

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

/** يحوّل حجم ملف بالبايت إلى نص مقروء (كيلوبايت/ميجابايت) — يُستخدم في وحدة الوثائق. */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} بايت`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} كيلوبايت`
  return `${(bytes / (1024 * 1024)).toFixed(1)} ميجابايت`
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
