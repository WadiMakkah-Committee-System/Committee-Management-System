import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as documentsApi from '@/api/documents'
import type { DocumentUpdatePayload } from '@/types'

export const documentsKeys = {
  all: ['documents'] as const,
  list: (params: documentsApi.ListDocumentsParams) => ['documents', 'list', params] as const,
  detail: (documentId: string) => ['documents', documentId] as const,
  publishTargets: ['documents', 'publish-targets'] as const,
}

function invalidateDocumentsList(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: documentsKeys.all })
}

export function useDocuments(params: documentsApi.ListDocumentsParams = {}) {
  return useQuery({
    queryKey: documentsKeys.list(params),
    queryFn: () => documentsApi.fetchDocuments(params),
  })
}

export function useDocumentDetail(documentId: string | undefined) {
  return useQuery({
    queryKey: documentsKeys.detail(documentId ?? ''),
    queryFn: () => documentsApi.fetchDocument(documentId as string),
    enabled: !!documentId,
  })
}

/** راجعي fetchDocumentPublishTargets — الإدارات واللجان المتاحة للمستخدم الحالي عند رفع/تعديل وثيقة فقط (مبدأ أقل صلاحية ممكنة). */
export function useDocumentPublishTargets() {
  return useQuery({
    queryKey: documentsKeys.publishTargets,
    queryFn: () => documentsApi.fetchDocumentPublishTargets(),
  })
}

export function useUploadDocument() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: documentsApi.DocumentUploadInput) => documentsApi.uploadDocument(input),
    onSuccess: () => invalidateDocumentsList(queryClient),
  })
}

export function useUpdateDocument() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ documentId, payload }: { documentId: string; payload: DocumentUpdatePayload }) =>
      documentsApi.updateDocument(documentId, payload),
    onSuccess: (_data, variables) => {
      invalidateDocumentsList(queryClient)
      queryClient.invalidateQueries({ queryKey: documentsKeys.detail(variables.documentId) })
    },
  })
}

export function useDeleteDocument() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (documentId: string) => documentsApi.deleteDocument(documentId),
    onSuccess: () => invalidateDocumentsList(queryClient),
  })
}

/**
 * التحميل ليس عملية تُغيّر بيانات (لا Invalidation)، لكنها Mutation لا Query
 * لأنها Side Effect صريح (تنزيل ملف) يُشغَّل بفعل المستخدم (زر)، وتحتاج
 * isPending لتعطيل الزر أثناء التحميل — بعكس useQuery المصمَّم للقراءة
 * التلقائية عند التركيب (mount).
 */
export function useDownloadDocument() {
  return useMutation({
    mutationFn: ({ documentId, fileName }: { documentId: string; fileName: string }) =>
      documentsApi.downloadDocument(documentId, fileName),
  })
}
