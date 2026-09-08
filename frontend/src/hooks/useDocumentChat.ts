import { useMutation } from '@tanstack/react-query'
import * as documentChatApi from '@/api/documentChat'

/**
 * شات وثيقة واحدة — كل سؤال مستقل (بلا تاريخ محادثة محفوظ بالخادم، قرار
 * مقصود لمرحلة أولى بسيطة)؛ الواجهة تحتفظ بسجل الأسئلة/الأجوبة محليًا
 * فقط (راجعي DocumentChatPanel.tsx).
 */
export function useAskDocument() {
  return useMutation({
    mutationFn: ({ documentId, question }: { documentId: string; question: string }) =>
      documentChatApi.askDocument(documentId, question),
  })
}

/** نفس فكرة useAskDocument أعلاه، لكن عبر كل الوثائق المصرَّح للمستخدم برؤيتها. */
export function useAskDocuments() {
  return useMutation({
    mutationFn: (question: string) => documentChatApi.askDocuments(question),
  })
}
