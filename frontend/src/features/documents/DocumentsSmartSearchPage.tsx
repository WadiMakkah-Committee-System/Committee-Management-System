import { useDocumentChatSession } from '@/hooks/useDocumentChat'
import { DocumentChatPanel } from './DocumentChatPanel'
import { DocumentChatSidebar } from './DocumentChatSidebar'

/**
 * صفحة "البحث الذكي" العامة — تبحث وتجيب من كل الوثائق التي يملك المستخدم
 * صلاحية رؤيتها (documents.search_all_agent)، عبر POST /documents/ask.
 * التصفية حسب نطاق الرؤية (can_view_document) تتم بالكامل في الباك-إند
 * قبل وصول أي محتوى لـGemini — راجعي DocumentChatPanel.tsx للتفاصيل.
 *
 * تخطيط بنمط ChatGPT (طلب صريح من المستخدمة 2026-09-09: حفظ المحادثات
 * وعرضها بـSidebar): useDocumentChatSession جلسة واحدة مشتركة بين
 * DocumentChatSidebar (سجل المحادثات كامل) وDocumentChatPanel (اللوحة
 * نفسها، مع إخفاء قائمة السجل المضغوطة بهيدرها عبر hideHistoryToggle
 * لأنها مكرّرة هنا مع الـSidebar الكامل أصلاً).
 */
export function DocumentsSmartSearchPage() {
  const session = useDocumentChatSession()

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-bold text-text-primary">البحث الذكي</h1>
        <p className="mt-1 text-sm text-text-muted">اسأل عن أي وثيقة تملك صلاحية الاطلاع عليها، وسيبحث النظام في كل الوثائق المسموح لك بها</p>
      </div>

      <div className="flex gap-4">
        <DocumentChatSidebar session={session} className="h-[calc(100vh-220px)] min-h-[480px]" />
        <DocumentChatPanel
          session={session}
          hideHistoryToggle
          className="h-[calc(100vh-220px)] min-h-[480px] flex-1"
        />
      </div>
    </div>
  )
}
