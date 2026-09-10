import { apiClient } from '@/lib/apiClient'
import type { DashboardSummary } from '@/types'

/** وحدة "لوحة التحكم" — تقابل app/api/v1/dashboard.py بالباك-إند (مسار واحد فقط). */
export async function fetchDashboardSummary(): Promise<DashboardSummary> {
  const { data } = await apiClient.get<DashboardSummary>('/dashboard/summary')
  return data
}
