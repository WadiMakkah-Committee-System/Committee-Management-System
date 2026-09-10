import { useQuery } from '@tanstack/react-query'
import * as dashboardApi from '@/api/dashboard'

export const dashboardKeys = {
  summary: ['dashboard', 'summary'] as const,
}

export function useDashboardSummary() {
  return useQuery({
    queryKey: dashboardKeys.summary,
    queryFn: dashboardApi.fetchDashboardSummary,
    // نفس الفكرة العامة لـuseUnreadCount بالإشعارات — بيانات لوحة التحكم
    // خفيفة ومفيد تحديثها دوريًا بدون تفاعل من المستخدم (اجتماع جديد،
    // قرار فُتح للتصويت... إلخ قد يصير من مستخدم آخر أثناء بقاء هذه
    // الصفحة مفتوحة).
    refetchInterval: 60_000,
  })
}
