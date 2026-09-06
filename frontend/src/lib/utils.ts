import type { ApiErrorShape, PermissionScope, RoleSummary, SystemRoleName, UserDetail } from '@/types'

/**
 * ترتيب اتساع نطاقات الوصول من الأوسع للأضيق — يطابق تمامًا
 * _SCOPE_BREADTH_ORDER في backend/app/models/role.py.
 */
const SCOPE_BREADTH_ORDER: readonly PermissionScope[] = ['all', 'department', 'own']

/**
 * أوسع نطاق يملكه المستخدم بين عدّة أكواد صلاحية بديلة — يطابق تمامًا
 * User.scope_for() بالباك-إند (نفس منطق require_permission: يكفي امتلاك
 * واحدة منها). تُرجع null لو لا يملك أي كود منها إطلاقًا.
 *
 * مراجعة لاما 2026-08-31 (بلاغ خطأ): قبل هذه الدالة، كانت شاشات مثل صفحة
 * تفاصيل طلب تشكيل اللجنة تقرر إظهار إجراءات مقيَّدة بنطاق (كـ"إرجاع
 * لمقدّم الطلب") بالاعتماد فقط على permissions.includes(code) — وجود
 * الكود لا يعني أن نطاقه واسع بما يكفي، فكان الادمن (نطاق own على
 * committees.request.update ليقدر يعدّل مسودته) يرى إجراءات المكتب
 * التنفيذي (نطاق department/all) على طلبه هو نفسه. استخدمي هذه الدالة
 * دائمًا بدل permissions.includes() لأي إجراء يفرّق الباك-إند فيه بين
 * النطاقات فعليًا (راجعي دائمًا committee_service.py لتأكيد أن هناك فحص
 * نطاق فعلي مطابق قبل الاعتماد عليها بالواجهة).
 */
export function scopeFor(
  user: Pick<UserDetail, 'permission_scopes'> | null | undefined,
  ...codes: string[]
): PermissionScope | null {
  if (!user) return null
  const owned = new Set(
    codes.map((c) => user.permission_scopes[c]).filter((s): s is PermissionScope => !!s),
  )
  for (const candidate of SCOPE_BREADTH_ORDER) {
    if (owned.has(candidate)) return candidate
  }
  return null
}

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

/**
 * دوائر أيقونات بألوان الهوية (نفس ترتيب الألوان أعلاه) — بنفس نمط دوائر
 * أيقونات StatCard المُثبت أصلًا بالتصميم (خلفية 15٪ + نص/أيقونة بلون كامل)،
 * لإعطاء كل صف بقائمة الاجتماعات هوية لونية واضحة (طلب لاما 2026-09-05:
 * "التقويم كله أبيض... يصير حياة" — امتد نفس المبدأ لقائمة الاجتماعات).
 */
const ICON_TONE_CLASSES = [
  'bg-brand-primary/15 text-brand-primary',
  'bg-brand-teal/15 text-brand-teal',
  'bg-brand-purple/15 text-brand-purple',
  'bg-brand-orange/15 text-brand-orange',
  'bg-brand-dark-blue/15 text-brand-dark-blue',
  'bg-brand-lime/15 text-brand-lime',
] as const

/** ترجع تدرّج لون دائرة أيقونة ثابت حسب الترتيب (تدوير على القائمة أعلاه). */
export function iconToneClass(index: number): string {
  return ICON_TONE_CLASSES[index % ICON_TONE_CLASSES.length]
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

/** الوقت فقط (بلا تاريخ) — يُستخدم بشارة الوقت بالعرض الزمني لصفحة الاجتماعات. */
export function formatTime(value: string | null): string {
  if (!value) return '—'
  return new Intl.DateTimeFormat('ar-SA-u-ca-gregory-nu-latn', {
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

/** عنوان يوم كامل (اليوم، رقم اليوم، الشهر) — يُستخدم كفاصل مجموعات بالعرض الزمني (Timeline). */
export function formatDayHeading(value: string): string {
  return new Intl.DateTimeFormat('ar-SA-u-ca-gregory-nu-latn', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  }).format(new Date(value))
}

/** مفتاح تجميع باليوم (حسب التوقيت المحلي للمتصفح) — لتقسيم قائمة الاجتماعات إلى مجموعات يومية. */
export function dayGroupKey(value: string): string {
  return new Date(value).toDateString()
}

/** حجم ملف مقروء (كيلوبايت/ميجابايت...) — يُستخدم بمرفقات الاجتماعات/الوثائق. */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} بايت`
  const units = ['كيلوبايت', 'ميجابايت', 'جيجابايت']
  let value = bytes / 1024
  let unitIndex = 0
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024
    unitIndex += 1
  }
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[unitIndex]}`
}
