import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as signatureApi from '@/api/userSignature'

/** مفتاح الـcache — نفسه يُبطَل من useSignMinutes عند "احفظه للمرات الجاية". */
export const mySignatureKey = ['users', 'me', 'signature'] as const

/**
 * الهدف: توقيعي المحفوظ (null لو ما عندي).
 * enabled: false للضيوف (ما لهم توقيع محفوظ — الخادم يرجع 403).
 */
export function useMySignature(enabled = true) {
  return useQuery({
    queryKey: mySignatureKey,
    queryFn: signatureApi.fetchMySignature,
    enabled,
    retry: false,
  })
}

/** حفظ/استبدال توقيعي. */
export function useSaveMySignature() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (signatureImage: string) => signatureApi.saveMySignature(signatureImage),
    onSuccess: (saved) => queryClient.setQueryData(mySignatureKey, saved),
  })
}

/** حذف توقيعي. */
export function useDeleteMySignature() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: signatureApi.deleteMySignature,
    onSuccess: () => queryClient.setQueryData(mySignatureKey, null),
  })
}
