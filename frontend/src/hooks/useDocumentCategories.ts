import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as documentCategoriesApi from '@/api/documentCategories'
import { documentsKeys } from '@/hooks/useDocuments'
import type { DocumentCategoryCreatePayload, DocumentCategoryUpdatePayload } from '@/types'

export const documentCategoriesKeys = {
  all: ['documentCategories'] as const,
}

/**
 * أي تعديل/حذف لتصنيف قد يغيّر اسمه أو يزيله من قوائم الوثائق نفسها
 * (category المضمَّن داخل DocumentOut) — لذلك تُبطَل قائمة الوثائق أيضًا،
 * بنفس فكرة invalidateUserRelatedQueries في useUsers.ts.
 */
function invalidateCategoryRelatedQueries(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: documentCategoriesKeys.all })
  queryClient.invalidateQueries({ queryKey: documentsKeys.all })
}

export function useDocumentCategories() {
  return useQuery({
    queryKey: documentCategoriesKeys.all,
    queryFn: documentCategoriesApi.fetchDocumentCategories,
  })
}

export function useCreateDocumentCategory() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: DocumentCategoryCreatePayload) =>
      documentCategoriesApi.createDocumentCategory(payload),
    onSuccess: () => invalidateCategoryRelatedQueries(queryClient),
  })
}

export function useUpdateDocumentCategory() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      categoryId,
      payload,
    }: {
      categoryId: string
      payload: DocumentCategoryUpdatePayload
    }) => documentCategoriesApi.updateDocumentCategory(categoryId, payload),
    onSuccess: () => invalidateCategoryRelatedQueries(queryClient),
  })
}

export function useDeleteDocumentCategory() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (categoryId: string) => documentCategoriesApi.deleteDocumentCategory(categoryId),
    onSuccess: () => invalidateCategoryRelatedQueries(queryClient),
  })
}
