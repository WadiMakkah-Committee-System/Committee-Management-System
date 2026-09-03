import { apiClient } from '@/lib/apiClient'
import type { Document, DocumentPublishTargets, DocumentScopeFilter, DocumentUpdatePayload } from '@/types'

/**
 * الهدف: طبقة اتصال بـ /documents — تقابل router في
 * backend/app/api/v1/documents.py. رفع الملف (uploadDocument) الوحيد الذي
 * يرسل multipart/form-data بدل JSON، لأن الملف الفعلي يمر عبر الـ Backend
 * (وليس رابطًا موقّعًا مباشرًا لـ Supabase Storage).
 */

export interface ListDocumentsParams {
  q?: string
  category_id?: string
  /** عنصر التحكم المُقسَّم بأعلى صفحة الوثائق (الكل/عامة/إدارتي/لجاني/شورك معي) — راجعي DocumentScopeFilter. */
  scope?: DocumentScopeFilter
  /** لتصفية وثائق لجنة معيّنة فقط (قسم "وثائق اللجنة" بصفحة تفاصيل اللجنة). */
  committee_id?: string
}

export async function fetchDocuments(params: ListDocumentsParams = {}): Promise<Document[]> {
  const { data } = await apiClient.get<Document[]>('/documents', {
    params: {
      q: params.q || undefined,
      category_id: params.category_id || undefined,
      scope: params.scope || undefined,
      committee_id: params.committee_id || undefined,
    },
  })
  return data
}

export async function fetchDocument(documentId: string): Promise<Document> {
  const { data } = await apiClient.get<Document>(`/documents/${documentId}`)
  return data
}

/** الإدارات واللجان اللي يحق للمستخدم الحالي إتاحة وثيقة لها (مبدأ أقل صلاحية ممكنة) — تُستخدم في فورم الرفع/التعديل بدل القوائم الكاملة. */
export async function fetchDocumentPublishTargets(): Promise<DocumentPublishTargets> {
  const { data } = await apiClient.get<DocumentPublishTargets>('/documents/publish-targets')
  return data
}

/** بيانات نموذج رفع وثيقة جديدة — يُبنى منها FormData لأن الرفع multipart لا JSON. */
export interface DocumentUploadInput {
  file: File
  title: string
  description: string | null
  category_id: string | null
  is_public: boolean
  department_ids: string[]
  committee_ids: string[]
  user_ids: string[]
}

export async function uploadDocument(input: DocumentUploadInput): Promise<Document> {
  const formData = new FormData()
  formData.append('file', input.file)
  formData.append('title', input.title)
  if (input.description) formData.append('description', input.description)
  if (input.category_id) formData.append('category_id', input.category_id)
  formData.append('is_public', String(input.is_public))
  formData.append('department_ids', input.department_ids.join(','))
  formData.append('committee_ids', input.committee_ids.join(','))
  formData.append('user_ids', input.user_ids.join(','))

  // لا نمرر Content-Type يدويًا هنا عمدًا: axios/المتصفح يضبط
  // multipart/form-data مع الـ boundary الصحيح تلقائيًا عند اكتشاف أن
  // البيانات FormData — أي قيمة يدوية ستُفقد الـ boundary وتكسر الطلب.
  const { data } = await apiClient.post<Document>('/documents', formData)
  return data
}

export async function updateDocument(
  documentId: string,
  payload: DocumentUpdatePayload,
): Promise<Document> {
  const { data } = await apiClient.patch<Document>(`/documents/${documentId}`, payload)
  return data
}

export async function deleteDocument(documentId: string): Promise<void> {
  await apiClient.delete(`/documents/${documentId}`)
}

/**
 * يحمّل الوثيقة كـ Blob من الباك-إند ثم يُنزّلها في المعروضة أصلًا (fileName) بدل تحليل Content-Disposition يدويًا.
 */
export async function downloadDocument(documentId: string, fileName: string): Promise<void> {
  const response = await apiClient.get(`/documents/${documentId}/download`, { responseType: 'blob' })
  const url = window.URL.createObjectURL(response.data as Blob)
  const link = document.createElement('a')
  link.href = url
  link.download = fileName
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.URL.revokeObjectURL(url)
}
