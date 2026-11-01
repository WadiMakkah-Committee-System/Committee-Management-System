import type { QueryClient, QueryKey } from '@tanstack/react-query'

/**
 * بيانات أولية لصفحة التفاصيل من قائمة محمَّلة أصلًا (تحسين أداء 2026-10-25).
 *
 * قوائم القرارات/المهام/الوثائق/اللجان ترجع **نفس شكل** صفحة التفاصيل بالضبط
 * (DecisionOut/TaskOut/DocumentOut/CommitteeOut بالباك-إند). لما يفتح المستخدم
 * عنصرًا من القائمة، نعرضه فورًا من القائمة بدل طلب جديد للسيرفر:
 * - لو القائمة حديثة (ضمن staleTime) → لا طلب إطلاقًا.
 * - لو قديمة → تظهر فورًا ثم تتحدّث بطلب بالخلفية (سلوك React Query العادي
 *   مع initialDataUpdatedAt).
 * - لو العنصر غير موجود بأي قائمة → طلب عادي كالسابق.
 */
export function seedFromLists<T>(
  queryClient: QueryClient,
  listKey: QueryKey,
  match: (item: T) => boolean,
  options?: { exact?: boolean },
): { initialData: () => T | undefined; initialDataUpdatedAt: () => number | undefined } {
  let found: { item: T; updatedAt: number } | undefined
  const lookup = () => {
    found = undefined
    for (const [key, data] of queryClient.getQueriesData<unknown>({ queryKey: listKey, exact: options?.exact })) {
      if (!Array.isArray(data)) continue
      const item = (data as T[]).find(match)
      if (!item) continue
      const updatedAt = queryClient.getQueryState(key)?.dataUpdatedAt ?? 0
      // أحدث قائمة تحتوي العنصر (الوثائق مثلًا لها قائمة لكل فلتر).
      if (!found || updatedAt > found.updatedAt) found = { item, updatedAt }
    }
    return found
  }
  return {
    initialData: () => lookup()?.item,
    initialDataUpdatedAt: () => found?.updatedAt,
  }
}
