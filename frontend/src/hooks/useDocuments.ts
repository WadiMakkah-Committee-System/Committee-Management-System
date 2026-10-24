import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as documentsApi from '@/api/documents'
import type { Document, DocumentUpdatePayload } from '@/types'
import { applyOptimistic, removeFromLists, rollbackOptimistic } from '@/lib/optimistic'

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

/** تحميل مسبق لتفاصيل وثيقة عند مرور الماوس على رابطها (تحسين أداء 2026-10-24). */
export function usePrefetchDocument() {
  const queryClient = useQueryClient()
  return (documentId: string) =>
    queryClient.prefetchQuery({
      queryKey: documentsKeys.detail(documentId),
      queryFn: () => documentsApi.fetchDocument(documentId),
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
/** options.enabled: تُستخدم فقط داخل نموذج رفع/تعديل الوثيقة — لا تُجلب إلا عند فتحه. */
export function useDocumentPublishTargets(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: documentsKeys.publishTargets,
    queryFn: () => documentsApi.fetchDocumentPublishTargets(),
    enabled: options?.enabled ?? true,
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
    // تحديث متفائل: الوثيقة تختفي من كل قوائم الوثائق (بكل فلاترها) فورًا.
    onMutate: (documentId) =>
      applyOptimistic(queryClient, [
        {
          queryKey: ['documents', 'list'],
          update: removeFromLists<Document>((d) => d.document_id === documentId),
        },
      ]),
    onError: (_err, _documentId, snapshot) => rollbackOptimistic(queryClient, snapshot),
    onSettled: () => invalidateDocumentsList(queryClient),
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
