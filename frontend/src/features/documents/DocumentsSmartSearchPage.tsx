import { DocumentChatPanel } from './DocumentChatPanel'

/**
 * صفحة "البحث الذكي" العامة — تبحث وتجيب من كل الوثائق التي يملك المستخدم
 * صلاحية رؤيتها (documents.search_all_agent)، عبر POST /documents/ask.
 * التصفية حسب نطاق الرؤية (can_view_document) تتم بالكامل في الباك-إند
 * قبل وصول أي محتوى لـGemini — راجعي DocumentChatPanel.tsx للتفاصيل.
 */
export function DocumentsSmartSearchPage() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-bold text-text-primary">البحث الذكي</h1>
        <p className="mt-1 text-sm text-text-muted">اسأل عن أي وثيقة تملك صلاحية الاطلاع عليها، وسيبحث النظام في كل الوثائق المسموح لك بها</p>
      </div>

      <DocumentChatPanel className="h-[calc(100vh-220px)] min-h-[480px]" />
    </div>
  )
}
