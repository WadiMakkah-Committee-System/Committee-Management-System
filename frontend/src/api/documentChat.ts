import { apiClient } from '@/lib/apiClient'
import type { DocumentChatResponse } from '@/types'

/**
 * الهدف: طبقة اتصال بميزة "البحث الذكي" داخل الوثائق — تقابل
 * POST /documents/{document_id}/ask وPOST /documents/ask في
 * backend/app/api/v1/documents.py. راجعي رأس
 * db/migrations/0029_documents_semantic_search.sql للقرار الكامل.
 *
 * سؤال مقيَّد بوثيقة واحدة (الإجابة من محتوى تلك الوثيقة فقط) — يحتاج
 * documents.view فقط، لأنه لا يكشف شيئًا لا يقدر المستخدم يشوفه أصلًا
 * بفتح الوثيقة نفسها.
 */
export async function askDocument(documentId: string, question: string): Promise<DocumentChatResponse> {
  const { data } = await apiClient.post<DocumentChatResponse>(`/documents/${documentId}/ask`, { question })
  return data
}

/**
 * سؤال عام يشمل كل الوثائق المصرَّح للمستخدم برؤيتها — يحتاج صلاحية
 * documents.search_all_agent إضافةً لـdocuments.view (بوابة استخدام
 * منفصلة عن نطاق الرؤية نفسه — راجعي can_view_document بالباك-إند).
 */
export async function askDocuments(question: string): Promise<DocumentChatResponse> {
  const { data } = await apiClient.post<DocumentChatResponse>('/documents/ask', { question })
  return data
}
