import { Plus } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { MinutesSection, MinutesSignature } from '@/types'
import {
  AgendaBlock,
  ClosingBlock,
  GuestsBlock,
  HeaderBlock,
  MembersBlock,
  RichBlock,
  SignaturesBlock,
  TextBlock,
  TitleBlock,
  TopicBlock,
  type BlockProps,
} from './blocks'
import { kindOf } from './types'

/**
 * الهدف:
 * محضر "القالب العام" كمستند بشكل محضر وادي مكة الأصلي (ورقة بيضاء، خط نسخ،
 * ترويسة بالشعار، جداول برأس رمادي، تذييل الورق الرسمي) — يعمل بوضعين:
 * - edit: كل الخانات تُعدَّل في مكانها (الحفظ مسؤولية المستدعي عبر onSectionChange).
 * - view: نص المستند فقط (عرض المحضر، المراجعة، الطباعة).
 *
 * المدخلات:
 * - sections: أقسام المحضر بالترتيب.
 * - signatures: حالة توقيعات المحضر (من الخادم فقط).
 * - lockedBy: يرجع اسم عضو آخر يحرر القسم الآن (القسم يصير للقراءة فقط مؤقتًا).
 * - onDeleteSection / onAddTopic: عمليات هيكلية (حفظ كامل) — تُخفى لو غير ممرّرة.
 * - compact: داخل لوحة الاجتماع الضيقة (هوامش أصغر).
 */

interface GeneralMinutesDocumentProps {
  sections: MinutesSection[]
  mode: 'edit' | 'view'
  signatures: MinutesSignature[]
  onSectionChange?: (next: MinutesSection) => void
  onFocusSection?: (sectionId: string) => void
  lockedBy?: (sectionId: string) => string | null
  onDeleteSection?: (sectionId: string) => void
  onAddTopic?: () => void
  compact?: boolean
}

export function GeneralMinutesDocument({
  sections,
  mode,
  signatures,
  onSectionChange,
  onFocusSection,
  lockedBy,
  onDeleteSection,
  onAddTopic,
  compact,
}: GeneralMinutesDocumentProps) {
  const ordered = [...sections].sort((a, b) => a.order - b.order)
  const lastTopicIndex = ordered.map((s) => kindOf(s)).lastIndexOf('topic')

  return (
    <article
      className={cn('minutes-paper mx-auto', compact ? 'minutes-paper-compact' : 'max-w-[52rem]')}
      dir="rtl"
      aria-label="محضر الاجتماع"
    >
      {ordered.map((section, index) => {
        const kind = kindOf(section)
        if (kind === 'meta') return null
        const editor = lockedBy?.(section.id) ?? null
        const editable = mode === 'edit' && !editor && !!onSectionChange
        const props: BlockProps = {
          section,
          editable,
          onChange: (next) => onSectionChange?.(next),
          onFocus: () => onFocusSection?.(section.id),
        }
        let block
        switch (kind) {
          case 'header':
            block = <HeaderBlock {...props} />
            break
          case 'title':
            block = <TitleBlock {...props} />
            break
          case 'rich':
            block = <RichBlock {...props} />
            break
          case 'members_table':
            block = <MembersBlock {...props} />
            break
          case 'guests_table':
            block = <GuestsBlock {...props} />
            break
          case 'agenda_table':
            block = <AgendaBlock {...props} />
            break
          case 'topic':
            block = (
              <TopicBlock
                {...props}
                onDelete={mode === 'edit' && onDeleteSection && !editor ? () => onDeleteSection(section.id) : undefined}
              />
            )
            break
          case 'closing':
            block = <ClosingBlock {...props} />
            break
          case 'signatures':
            block = <SignaturesBlock {...props} signatures={signatures} />
            break
          default:
            block = <TextBlock {...props} />
        }
        return (
          <div key={section.id} className={cn('relative', editor && 'minutes-block-locked')}>
            {editor && (
              <div className="absolute -top-3 left-0 z-10 rounded-xs bg-info-bg px-2 py-0.5 font-sans text-[11px] font-medium text-info">
                {editor} يحرر هذا الجزء الآن
              </div>
            )}
            {block}
            {mode === 'edit' && onAddTopic && (index === lastTopicIndex || (lastTopicIndex === -1 && kind === 'rich' && section.data?.role === 'discussion')) && (
              <button
                type="button"
                onClick={onAddTopic}
                className="mt-4 flex items-center gap-1.5 rounded-xs px-2 py-1 font-sans text-xs font-medium text-brand-primary hover:bg-brand-primary/5"
              >
                <Plus size={14} /> إضافة موضوع
              </button>
            )}
          </div>
        )
      })}
      <img src="/letterhead-footer.png" alt="" aria-hidden className="minutes-paper-footer mt-12 w-full" />
    </article>
  )
}
