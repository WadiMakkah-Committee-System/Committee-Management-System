/**
 * تحية بحسب وقت اليوم — منطق بسيط ومختبر بمعزل عن أي React لسهولة
 * الاختبار (راجعي dashboardGreeting.test.ts). يقابل روح متطلب SRS:
 * "توجيه المستخدم بعد تسجيل الدخول للوحة التحكم المناسبة له" — لمسة
 * ترحيبية شخصية أول ما يفتح لوحة تحكمه.
 */
export function getGreeting(now: Date = new Date()): string {
  const hour = now.getHours()
  if (hour < 5) return 'مساء الخير'
  if (hour < 12) return 'صباح الخير'
  if (hour < 17) return 'يومك سعيد'
  return 'مساء الخير'
}

/** اسم اليوم الميلادي الحالي بالعربية، للعرض أسفل التحية — بدون مكتبة تاريخ خارجية. */
export function formatTodayLabel(now: Date = new Date()): string {
  return new Intl.DateTimeFormat('ar-SA', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  }).format(now)
}
