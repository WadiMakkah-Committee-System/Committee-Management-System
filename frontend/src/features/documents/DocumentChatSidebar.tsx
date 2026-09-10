import { MessageSquare, Plus } from 'lucide-react'
import type { DocumentChatSession } from '@/hooks/useDocumentChat'
import { Button } from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import { cn, formatDateTime } from '@/lib/utils'

/**
 * الهدف:
 * سجل محادثات "البحث الذكي" العامة (Sidebar كامل، بنمط ChatGPT) —
 * تُستخدَم فقط بصفحة DocumentsSmartSearchPage جنب DocumentChatPanel
 * (اللي تُمرَّر لها hideHistoryToggle عشان ما يتكرر نفس السجل مرتين
 * بقائمة مضغوطة داخل هيدرها كمان). راجعي hooks/useDocumentChat.ts
 * لمصدر البيانات (session مشترك بين المكوّنين).
 */
export function DocumentChatSidebar({ session, className }: { session: DocumentChatSession; className?: string }) {
  const { conversations, conversationsLoading, conversationId, loadConversation, startNew } = session

  return (
    <div className={cn('flex w-64 shrink-0 flex-col gap-3 overflow-hidden rounded-md border border-border-default bg-bg-surface p-3', className)}>
      <Button variant="secondary" icon={<Plus size={15} />} onClick={startNew} className="w-full justify-center">
        محادثة جديدة
      </Button>

      <div className="-mx-1 flex-1 overflow-y-auto px-1">
        {conversationsLoading ? (
          <div className="flex justify-center py-6">
            <Spinner size={16} />
          </div>
        ) : conversations.length === 0 ? (
          <p className="px-2 py-6 text-center text-[12px] text-text-muted">ما فيه محادثات سابقة بعد</p>
        ) : (
          <div className="flex flex-col gap-1">
            {conversations.map((c) => (
              <button
                key={c.conversation_id}
                onClick={() => loadConversation(c.conversation_id)}
                className={cn(
                  'flex items-start gap-2 rounded-sm px-2.5 py-2 text-right transition-colors hover:bg-bg-elevated',
                  c.conversation_id === conversationId && 'bg-bg-elevated',
                )}
              >
                <MessageSquare size={14} className="mt-0.5 shrink-0 text-text-muted" />
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="truncate text-[12.5px] font-medium text-text-primary">
                    {c.title ?? 'محادثة بلا عنوان'}
                  </span>
                  <span className="text-[10.5px] text-text-muted">{formatDateTime(c.updated_at)}</span>
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
