import { apiClient } from '@/lib/apiClient'
import type { AuditLogPage } from '@/types'

export async function fetchAuditLogs(params: { limit?: number; offset?: number } = {}): Promise<AuditLogPage> {
  const { data } = await apiClient.get<AuditLogPage>('/audit-logs', { params })
  return data
}
