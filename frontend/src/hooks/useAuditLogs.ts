import { useQuery } from '@tanstack/react-query'
import * as auditLogsApi from '@/api/auditLogs'

export function useAuditLogs(params: { limit?: number; offset?: number } = {}) {
  return useQuery({
    queryKey: ['audit-logs', params],
    queryFn: () => auditLogsApi.fetchAuditLogs(params),
  })
}
