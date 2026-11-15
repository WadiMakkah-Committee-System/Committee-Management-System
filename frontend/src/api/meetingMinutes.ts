import { apiClient } from '@/lib/apiClient'
import type {
  MeetingMinutes,
  MeetingMinutesDetail,
  MinutesSection,
  MinutesSummary,
  MinutesTemplate,
  MinutesTemplateId,
} from '@/types'

/**
 * وحدة "المحاضر" (SRS §7) — تقابل app/api/v1/meetings.py (مسارات
 * /minutes/*)، راجعي رأس app/services/meeting_minutes_service.py
 * للتصميم الكامل. شاشة مستقلة (MeetingMinutesPage.tsx) داخل قسم
 * الاجتماعات، تُفتح من زر "محضر الاجتماع" بصفحة تفاصيل الاجتماع.
 */

export async function fetchMinutesTemplates(meetingId: string): Promise<MinutesTemplate[]> {
  const { data } = await apiClient.get<MinutesTemplate[]>(`/meetings/${meetingId}/minutes/templates`)
  return data
}

/**
 * إصلاح 2026-09-14 (بلاغ لاما — 500 متكرر على عدة مسارات مختلفة بنفس
 * اللحظة، السبب الجذري: MinutesListPage.tsx كانت تطلق طلب HTTP منفصل
 * بالكامل لكل اجتماع عبر useQueries — انفجار طلبات متزامنة يستنزف
 * Connection Pool بالباك-إند، خصوصًا بعد Render Cold Start. راجعي
 * docstring MinutesSummaryOut بـbackend/app/schemas/meeting_minutes.py
 * للتفصيل الكامل). نداء واحد فقط لكل الاجتماعات دفعة وحدة بدل N نداء.
 *
 * تحقّقت فعليًا (node -e مع axios المثبّت بالمشروع، 1.19.0) إن التسلسل
 * الافتراضي لـ`params: { x: string[] }` ينتج ?x[]=a&x[]=b (بأقواس) —
 * FastAPI Query(list[...]) يقرأ فقط ?x=a&x=b المتكرر بلا أقواس، فما كان
 * ليعمل. تجنّبت الفخ كليًا بنص واحد مفصول بفاصلة بدل قائمة. */
export async function fetchMinutesSummaries(meetingIds: string[]): Promise<MinutesSummary[]> {
  if (meetingIds.length === 0) return []
  const { data } = await apiClient.get<MinutesSummary[]>('/meetings/minutes/summary', {
    params: { meeting_ids: meetingIds.join(',') },
  })
  return data
}

export async function fetchMeetingMinutes(meetingId: string): Promise<MeetingMinutes> {
  const { data } = await apiClient.get<MeetingMinutes>(`/meetings/${meetingId}/minutes`)
  return data
}

/**
 * إصلاح أداء (التوصية الثانية بتقرير أداء لاما 2026-09-14 — راجعي
 * docstring MeetingMinutesDetailOut بالباك-إند): نداء واحد يجيب الاجتماع
 * واللجنة والمحضر والقوالب والبنود المستخرجة معًا، بدل 5 طلبات منفصلة
 * كانت MeetingMinutesPage.tsx تطلقها (واحد منها Network Waterfall حقيقي —
 * طلب اللجنة كان ينتظر نتيجة طلب الاجتماع أولًا). تُستخدم حصرًا من تلك
 * الصفحة (راجعي useMeetingMinutesDetail بـhooks/useMeetingMinutes.ts).
 */
export async function fetchMeetingMinutesDetail(meetingId: string): Promise<MeetingMinutesDetail> {
  const { data } = await apiClient.get<MeetingMinutesDetail>(`/meetings/${meetingId}/minutes/detail`)
  return data
}

export async function selectMinutesTemplate(
  meetingId: string,
  templateId: MinutesTemplateId,
): Promise<MeetingMinutes> {
  const { data } = await apiClient.post<MeetingMinutes>(`/meetings/${meetingId}/minutes/template`, {
    template_id: templateId,
  })
  return data
}

export async function updateMinutesSections(
  meetingId: string,
  sections: MinutesSection[],
): Promise<MeetingMinutes> {
  const { data } = await apiClient.put<MeetingMinutes>(`/meetings/${meetingId}/minutes/sections`, {
    sections,
  })
  return data
}

export async function approveMinutesReview(meetingId: string, comment?: string): Promise<MeetingMinutes> {
  const { data } = await apiClient.post<MeetingMinutes>(`/meetings/${meetingId}/minutes/review/approve`, {
    comment: comment ?? null,
  })
  return data
}

export async function returnMinutesReview(meetingId: string, comment: string): Promise<MeetingMinutes> {
  const { data } = await apiClient.post<MeetingMinutes>(`/meetings/${meetingId}/minutes/review/return`, {
    comment,
  })
  return data
}

export async function approveMinutes(meetingId: string): Promise<MeetingMinutes> {
  const { data } = await apiClient.post<MeetingMinutes>(`/meetings/${meetingId}/minutes/approve`, {})
  return data
}

export async function returnMinutesForEdit(meetingId: string, comment: string): Promise<MeetingMinutes> {
  const { data } = await apiClient.post<MeetingMinutes>(`/meetings/${meetingId}/minutes/return`, {
    comment,
  })
  return data
}

export async function sendMinutesForSignature(meetingId: string): Promise<MeetingMinutes> {
  const { data } = await apiClient.post<MeetingMinutes>(`/meetings/${meetingId}/minutes/signature/send`, {})
  return data
}

/**
 * الهدف: حفظ قسم واحد من محضر "القالب العام" (PATCH) — الحفظ الأساسي أثناء
 * التحرير الجماعي، فتعديلان متزامنان على قسمين مختلفين لا يمسح أحدهما الآخر.
 *
 * المدخلات: meetingId، والقسم المعدّل كاملًا (لازم يحمل rev الحالي).
 * المخرجات: المحضر كاملًا بعد الحفظ.
 * الأخطاء: 409 لو rev قديم — detail.current_section فيه نسخة القسم الحالية
 * (راجعي sectionConflictOf أدناه)، 400 لبيانات غير صالحة، 403 بلا صلاحية.
 */
export async function updateMinutesSection(meetingId: string, section: MinutesSection): Promise<MeetingMinutes> {
  const { data } = await apiClient.patch<MeetingMinutes>(
    `/meetings/${meetingId}/minutes/sections/${encodeURIComponent(section.id)}`,
    { section },
  )
  return data
}

/**
 * الهدف: استخراج نسخة القسم الحالية من خطأ 409 (تعديل بنسخة قديمة).
 * المخرجات: القسم الحالي من الخادم، أو null لو الخطأ مو تعارض نسخ.
 */
export function sectionConflictOf(error: unknown): MinutesSection | null {
  const response = (error as { response?: { status?: number; data?: { detail?: unknown } } })?.response
  if (response?.status !== 409) return null
  const detail = response.data?.detail as { current_section?: MinutesSection } | undefined
  return detail && typeof detail === 'object' && detail.current_section ? detail.current_section : null
}

/** مصدر التوقيع: رسم الآن (مع خيار حفظه للمرات الجاية) أو التوقيع المحفوظ. */
export type SignMinutesInput =
  | { signatureImage: string; saveForLater?: boolean; useSaved?: false }
  | { useSaved: true; signatureImage?: undefined; saveForLater?: false }

/**
 * الهدف: توقيع المحضر إلكترونيًا.
 * المدخلات: signatureImage (PNG data URL) مع saveForLater، أو useSaved فقط —
 * الخادم يقرأ التوقيع المحفوظ بنفسه (لا تُرسل صورته من هنا).
 * الأخطاء: 400 لو ما فيه توقيع محفوظ، 403 لو مو من الموقّعين.
 */
export async function signMinutes(meetingId: string, input: SignMinutesInput): Promise<MeetingMinutes> {
  const body = input.useSaved
    ? { use_saved: true }
    : { signature_image: input.signatureImage, save_for_later: !!input.saveForLater }
  const { data } = await apiClient.post<MeetingMinutes>(`/meetings/${meetingId}/minutes/sign`, body)
  return data
}
