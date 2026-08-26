import { apiClient } from '@/lib/apiClient'
import type { JobTitle, JobTitleCreatePayload, JobTitleUpdatePayload } from '@/types'

export async function fetchJobTitles(): Promise<JobTitle[]> {
  const { data } = await apiClient.get<JobTitle[]>('/job-titles')
  return data
}

export async function createJobTitle(payload: JobTitleCreatePayload): Promise<JobTitle> {
  const { data } = await apiClient.post<JobTitle>('/job-titles', payload)
  return data
}

export async function updateJobTitle(jobTitleId: string, payload: JobTitleUpdatePayload): Promise<JobTitle> {
  const { data } = await apiClient.patch<JobTitle>(`/job-titles/${jobTitleId}`, payload)
  return data
}

export async function deleteJobTitle(jobTitleId: string): Promise<void> {
  await apiClient.delete(`/job-titles/${jobTitleId}`)
}
