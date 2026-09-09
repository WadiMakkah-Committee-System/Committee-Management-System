import { apiClient } from '@/lib/apiClient'
import type { DocumentChatConversation, DocumentChatConversationDetail, DocumentChatResponse } from '@/types'

/**
 * الهدف: طبقة اتصال بميزة "البحث الذكي" داخل الوثائق — تقابل
 * POST /documents/{document_id}/ask وPOST /documents/ask ونقاط قوائم/تفاصيل
 * المحادثات المحفوظة في backend/app/api/v1/documents.py. راجعي رأس
 * db/migrations/0029_documents_semantic_search.sql و
 * db/migrations/0030_document_chat_conversations.sql للقرار الكامل.
 *
 * سؤال مقيَّد بوثيقة واحدة (الإجابة من محتوى تلك الوثيقة فقط) — يحتاج
 * documents.view فقط، لأنه لا يكشف شيئًا لا يقدر المستخدم يشوفه أصلًا
 * بفتح الوثيقة نفسها. conversationId: غير مُعطى = محادثة جديدة، مُعطى =
 * استمرار محادثة قائمة (راجعي answer_question بالباك-إند).
 */
export async function askDocument(
  documentId: string,
  question: string,
  conversationId?: string,
): Promise<DocumentChatResponse> {
  const { data } = await apiClient.post<DocumentChatResponse>(`/documents/${documentId}/ask`, {
    question,
    conversation_id: conversationId ?? null,
  })
  return data
}

/**
 * سؤال عام يشمل كل الوثائق المصرَّح للمستخدم برؤيتها — يحتاج صلاحية
 * documents.search_all_agent إضافةً لـdocuments.view (بوابة استخدام
 * منفصلة عن نطاق الرؤية نفسه — راجعي can_view_document بالباك-إند).
 */
export async function askDocuments(question: string, conversationId?: string): Promise<DocumentChatResponse> {
  const { data } = await apiClient.post<DocumentChatResponse>('/documents/ask', {
    question,
    conversation_id: conversationId ?? null,
  })
  return data
}

/**
 * قائمة محادثات المستخدم الحالي — بنفس النطاق بالضبط (documentId مُعطى:
 * محادثات تلك الوثيقة، غير مُعطى: محادثات الشات العام)، الأحدث نشاطًا
 * أولًا — تغذّي الـSidebar.
 */
export async function listConversations(documentId?: string): Promise<DocumentChatConversation[]> {
  const url = documentId ? `/documents/${documentId}/conversations` : '/documents/conversations'
  const { data } = await apiClient.get<DocumentChatConversation[]>(url)
  return data
}

/** تفاصيل محادثة واحدة + كامل رسائلها — عند فتحها من الـSidebar. */
export async function getConversation(
  conversationId: string,
  documentId?: string,
): Promise<DocumentChatConversationDetail> {
  const url = documentId
    ? `/documents/${documentId}/conversations/${conversationId}`
    : `/documents/conversations/${conversationId}`
  const { data } = await apiClient.get<DocumentChatConversationDetail>(url)
  return data
}
