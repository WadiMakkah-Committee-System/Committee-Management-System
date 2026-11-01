import type { QueryClient, QueryKey } from '@tanstack/react-query'

/**
 * تحديث متفائل (Optimistic Update) — أدوات مشتركة (تحسين أداء 2026-10-24).
 *
 * الفكرة: الواجهة تعكس نتيجة العملية (حذف/تحديث حالة/تصويت/قراءة إشعار)
 * فورًا داخل الكاش، بدون انتظار رد السيرفر. نحفظ لقطة من الكاش قبل التعديل،
 * ولو فشل الطلب نرجّعها كما كانت (rollback)، وبعد انتهاء الطلب (نجاحًا أو
 * فشلًا) نعيد المزامنة مع السيرفر بـinvalidate كالسابق — فالسيرفر يبقى مصدر
 * الحقيقة الوحيد، والتحديث المتفائل مجرد عرض مسبق لنتيجة متوقَّعة.
 *
 * الاستخدام داخل useMutation:
 *   onMutate: (vars) => applyOptimistic(queryClient, [{ queryKey, update }]),
 *   onError: (_e, _v, snapshot) => rollbackOptimistic(queryClient, snapshot),
 *   onSettled: () => invalidate...,
 */

export type OptimisticSnapshot = Array<[QueryKey, unknown]>

export interface OptimisticTarget {
  /** يطابق كل الاستعلامات التي تبدأ بهذا المفتاح (نفس مطابقة invalidateQueries). */
  queryKey: QueryKey
  /** true: هذا المفتاح بالضبط فقط (بدون الاستعلامات المتفرعة منه). */
  exact?: boolean
  /** يُستدعى لكل استعلام مطابق فيه بيانات — يرجع البيانات الجديدة (أو نفسها بلا تغيير). */
  update: (data: unknown) => unknown
}

export async function applyOptimistic(
  queryClient: QueryClient,
  targets: OptimisticTarget[],
): Promise<OptimisticSnapshot> {
  // إلغاء أي جلب جارٍ لنفس البيانات حتى لا يكتب نتيجة قديمة فوق التحديث المتفائل.
  await Promise.all(
    targets.map((t) => queryClient.cancelQueries({ queryKey: t.queryKey, exact: t.exact })),
  )
  const snapshot: OptimisticSnapshot = []
  for (const target of targets) {
    for (const [key, data] of queryClient.getQueriesData({ queryKey: target.queryKey, exact: target.exact })) {
      if (data === undefined) continue
      snapshot.push([key, data])
      queryClient.setQueryData(key, target.update(data))
    }
  }
  return snapshot
}

export function rollbackOptimistic(queryClient: QueryClient, snapshot: OptimisticSnapshot | undefined) {
  if (!snapshot) return
  for (const [key, data] of snapshot) queryClient.setQueryData(key, data)
}

/** حذف عنصر من كل قائمة (مصفوفة) مطابقة — العناصر غير المصفوفات (صفحات التفاصيل) تبقى كما هي. */
export function removeFromLists<T>(match: (item: T) => boolean) {
  return (data: unknown) => (Array.isArray(data) ? (data as T[]).filter((item) => !match(item)) : data)
}

/** تعديل عنصر داخل كل قائمة مطابقة، وفي كائن التفاصيل نفسه لو كان هو العنصر المقصود. */
export function patchEverywhere<T extends object>(match: (item: T) => boolean, patch: (item: T) => T) {
  return (data: unknown) => {
    if (Array.isArray(data)) return (data as T[]).map((item) => (match(item) ? patch(item) : item))
    if (data && typeof data === 'object' && match(data as T)) return patch(data as T)
    return data
  }
}
