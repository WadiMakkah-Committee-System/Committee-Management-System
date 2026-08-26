import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as jobTitlesApi from '@/api/jobTitles'
import { usersKeys } from '@/hooks/useUsers'
import type { JobTitleCreatePayload, JobTitleUpdatePayload } from '@/types'

export const jobTitlesKeys = {
  all: ['job-titles'] as const,
}

export function useJobTitles() {
  return useQuery({ queryKey: jobTitlesKeys.all, queryFn: jobTitlesApi.fetchJobTitles })
}

export function useCreateJobTitle() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: JobTitleCreatePayload) => jobTitlesApi.createJobTitle(payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: jobTitlesKeys.all }),
  })
}

export function useUpdateJobTitle() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ jobTitleId, payload }: { jobTitleId: string; payload: JobTitleUpdatePayload }) =>
      jobTitlesApi.updateJobTitle(jobTitleId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: jobTitlesKeys.all })
      // قد يتغيّر اسم المسمى الوظيفي المضمَّن ضمن بيانات المستخدمين المرتبطين به.
      queryClient.invalidateQueries({ queryKey: usersKeys.all })
    },
  })
}

export function useDeleteJobTitle() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (jobTitleId: string) => jobTitlesApi.deleteJobTitle(jobTitleId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: jobTitlesKeys.all }),
  })
}
