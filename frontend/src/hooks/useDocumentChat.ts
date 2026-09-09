import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as documentChatApi from '@/api/documentChat'
import { extractErrorMessage } from '@/lib/utils'
import type { DocumentChatMessage, DocumentChatSource } from '@/types'

export const documentChatKeys = {
  all: ['document-chat'] as const,
  conversations: (documentId?: string) => ['document-chat', 'conversations', documentId ?? 'global'] as const,
}

export function useAskDocument() {
  return useMutation({
    mutationFn: ({
      documentId,
      question,
      conversationId,
    }: {
      documentId: string
      question: string
      conversationId?: string
    }) => documentChatApi.askDocument(documentId, question, conversationId),
  })
}

export function useAskDocuments() {
  return useMutation({
    mutationFn: ({ question, conversationId }: { question: string; conversationId?: string }) =>
      documentChatApi.askDocuments(question, conversationId),
  })
}

/** قائمة محادثات Sidebar — راجعي documentChatApi.listConversations. */
export function useDocumentChatConversations(documentId?: string) {
  return useQuery({
    queryKey: documentChatKeys.conversations(documentId),
    queryFn: () => documentChatApi.listConversations(documentId),
  })
}

export interface ChatTurn {
  id: string
  question: string
  answer?: string
  sources?: DocumentChatSource[]
  status: 'pending' | 'done' | 'error'
  errorMessage?: string
}

/** يحوّل رسائل محادثة محفوظة (تسلسل مسطَّح user/assistant) لأزواج
 * سؤال/جواب (ChatTurn) — نفس شكل العرض المستخدَم أثناء المحادثة الحية. */
function messagesToTurns(messages: DocumentChatMessage[]): ChatTurn[] {
  const turns: ChatTurn[] = []
  let current: ChatTurn | null = null
  for (const message of messages) {
    if (message.role === 'user') {
      current = { id: message.message_id, question: message.content, status: 'done' }
      turns.push(current)
    } else if (current) {
      current.answer = message.content
      current.sources = message.sources ?? undefined
    }
  }
  return turns
}

/**
 * الهدف:
 * "دماغ" لوحة/صفحة البحث الذكي — يجمّع حالة المحادثة الحالية (الأسئلة
 * والأجوبة المعروضة، معرّف المحادثة النشطة) مع قائمة المحادثات المحفوظة
 * وعمليات التنقل بينها (فتح محادثة قديمة / بدء محادثة جديدة)، بمكان
 * واحد يُستخدَم من DocumentChatPanel (اللوحة نفسها) وDocumentChatSidebar
 * (قائمة السجل) معًا — راجعي features/documents/DocumentChatPanel.tsx
 * وDocumentChatSidebar.tsx.
 */
export function useDocumentChatSession(documentId?: string) {
  const queryClient = useQueryClient()
  const askDocument = useAskDocument()
  const askDocuments = useAskDocuments()
  const conversationsQuery = useDocumentChatConversations(documentId)

  const [conversationId, setConversationId] = useState<string | null>(null)
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [isLoadingConversation, setIsLoadingConversation] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  function startNew() {
    setConversationId(null)
    setTurns([])
    setLoadError(null)
  }

  async function loadConversation(id: string) {
    if (id === conversationId) return
    setIsLoadingConversation(true)
    setLoadError(null)
    try {
      const detail = await documentChatApi.getConversation(id, documentId)
      setConversationId(detail.conversation_id)
      setTurns(messagesToTurns(detail.messages))
    } catch (err) {
      setLoadError(extractErrorMessage(err))
    } finally {
      setIsLoadingConversation(false)
    }
  }

  function sendQuestion(question: string) {
    const trimmed = question.trim()
    if (!trimmed) return

    const turnId = crypto.randomUUID()
    setTurns((prev) => [...prev, { id: turnId, question: trimmed, status: 'pending' }])

    const mutation = documentId
      ? askDocument.mutateAsync({ documentId, question: trimmed, conversationId: conversationId ?? undefined })
      : askDocuments.mutateAsync({ question: trimmed, conversationId: conversationId ?? undefined })

    mutation
      .then((res) => {
        setTurns((prev) =>
          prev.map((t) =>
            t.id === turnId ? { ...t, status: 'done' as const, answer: res.answer, sources: res.sources } : t,
          ),
        )
        setConversationId(res.conversation_id)
        queryClient.invalidateQueries({ queryKey: documentChatKeys.conversations(documentId) })
      })
      .catch((err: unknown) => {
        setTurns((prev) =>
          prev.map((t) =>
            t.id === turnId ? { ...t, status: 'error' as const, errorMessage: extractErrorMessage(err) } : t,
          ),
        )
      })
  }

  return {
    documentId,
    conversationId,
    turns,
    sendQuestion,
    startNew,
    loadConversation,
    isLoadingConversation,
    loadError,
    isSending: askDocument.isPending || askDocuments.isPending,
    conversations: conversationsQuery.data ?? [],
    conversationsLoading: conversationsQuery.isLoading,
  }
}

export type DocumentChatSession = ReturnType<typeof useDocumentChatSession>
