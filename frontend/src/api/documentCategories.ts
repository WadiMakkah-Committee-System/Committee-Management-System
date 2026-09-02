import { apiClient } from '@/lib/apiClient'
import type { DocumentCategory, DocumentCategoryCreatePayload, DocumentCategoryUpdatePayload } from '@/types'

/**
 * الهدف: طبقة اتصال بـ /document-categories (تصنيفات الوثائق) — تقابل
 * categories_router في backend/app/api/v1/documents.py.
 */

export async function fetchDocumentCategories(): Promise<DocumentCategory[]> {
  const { data } = await apiClient.get<DocumentCategory[]>('/document-categories')
  return data
}

export async function createDocumentCategory(
  payload: DocumentCategoryCreatePayload,
): Promise<DocumentCategory> {
  const { data } = await apiClient.post<DocumentCategory>('/document-categories', payload)
  return data
}

export async function updateDocumentCategory(
  categoryId: string,
  payload: DocumentCategoryUpdatePayload,
): Promise<DocumentCategory> {
  const { data } = await apiClient.patch<DocumentCategory>(`/document-categories/${categoryId}`, payload)
  return data
}

export async function deleteDocumentCategory(categoryId: string): Promise<void> {
  await apiClient.delete(`/document-categories/${categoryId}`)
}
