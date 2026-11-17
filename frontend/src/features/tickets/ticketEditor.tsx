import { forwardRef, memo, useImperativeHandle, useLayoutEffect, useMemo, useRef, type ReactNode } from 'react'
import { EditorContent, useEditor, useEditorState, type Editor } from '@tiptap/react'
import { Placeholder } from '@tiptap/extensions'
import { renderToReactElement } from '@tiptap/static-renderer/pm/react'
import { Bold, Italic, List, ListOrdered, Underline } from 'lucide-react'
import { cn } from '@/lib/utils'
import { ticketPlainText } from './ticketContent'
import { TICKET_EDITOR_EXTENSIONS } from './ticketEditorExtensions'
import type { TicketDoc } from '@/types/tickets'

/**
 * الهدف: عرض محتوى رسالة (مستند TipTap) للقراءة بدون إنشاء محرر لكل رسالة.
 *
 * يستخدم @tiptap/static-renderer (من حزمة TipTap الرسمية): يحوّل المستند إلى
 * عناصر React مباشرة — بدون HTML خام (لا dangerouslySetInnerHTML)، فالنص يُهرَّب
 * تلقائيًا ولا مجال لحقن سكربت. memo: الرسائل ما تتغيّر بعد الإرسال.
 *
 * المدخلات: doc — المستند كما يرجعه الباك-إند.
 * الأخطاء: لو المستند فيه عنصر خارج الامتدادات (من عميل API آخر مثلًا) يُعرض
 * نصه المجرّد بدل ما تنكسر المحادثة.
 */
export const TicketRichText = memo(function TicketRichText({ doc, className }: { doc: TicketDoc; className?: string }) {
  const rendered = useMemo<ReactNode>(() => {
    try {
      return renderToReactElement({ content: doc, extensions: TICKET_EDITOR_EXTENSIONS })
    } catch {
      return <p className="whitespace-pre-line">{ticketPlainText(doc)}</p>
    }
  }, [doc])
  return <div className={cn('ticket-rich', className)}>{rendered}</div>
})

/** أوامر يستدعيها صندوق الكتابة على المحرر (تفريغ بعد الإرسال، تركيز). */
export interface TicketEditorHandle {
  clear: () => void
  focus: () => void
}

interface TicketEditorProps {
  /** يُستدعى مع المستند الجديد (null لو صار فاضي) عند كل تعديل. */
  onChange: (doc: TicketDoc | null) => void
  /** Ctrl/⌘ + Enter — اختصار الإرسال (Enter وحده سطر جديد). */
  onSubmitShortcut?: () => void
  placeholder?: string
  ariaLabel: string
  invalid?: boolean
  /** ارتفاع منطقة الكتابة الأدنى (وصف التذكرة أطول من الرد). */
  minHeightClass?: string
  /** عناصر إضافية بآخر شريط الأدوات (زر الإرفاق مثلًا). */
  toolbarEnd?: ReactNode
}

/**
 * الهدف:
 * محرر نص غني لكتابة وصف التذكرة والردود — TipTap (معتمد بالمواصفات، القسم 7).
 *
 * المسؤولية: الكتابة والتنسيق فقط؛ حالة المحرر داخلية فالكتابة ما تعيد رسم
 * المحادثة (المشكلة اللي لُوحظت بمحادثة الاجتماع). الأب يقرأ المستند عبر onChange.
 *
 * المدخلات: راجعي TicketEditorProps. المخرجات (ref): clear() وfocus().
 */
export const TicketEditor = forwardRef<TicketEditorHandle, TicketEditorProps>(function TicketEditor(
  { onChange, onSubmitShortcut, placeholder, ariaLabel, invalid, minHeightClass = 'min-h-24', toolbarEnd },
  ref,
) {
  // آخر نسخة من الدوال للمحرر (يُنشأ مرة واحدة) — تُحدَّث بعد كل رسم لا أثناءه.
  const onChangeRef = useRef(onChange)
  const onSubmitRef = useRef(onSubmitShortcut)
  useLayoutEffect(() => {
    onChangeRef.current = onChange
    onSubmitRef.current = onSubmitShortcut
  })

  const editor = useEditor({
    extensions: [...TICKET_EDITOR_EXTENSIONS, Placeholder.configure({ placeholder: placeholder ?? '' })],
    content: '',
    editorProps: {
      attributes: {
        dir: 'rtl',
        role: 'textbox',
        'aria-multiline': 'true',
        'aria-label': ariaLabel,
        class: cn('ticket-rich ticket-rich-editable max-h-72 overflow-y-auto px-3 py-2.5 focus:outline-none', minHeightClass),
      },
      handleKeyDown: (_view, event) => {
        if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
          onSubmitRef.current?.()
          return true
        }
        return false
      },
    },
    onUpdate: ({ editor: current }) => {
      onChangeRef.current(current.isEmpty ? null : (current.getJSON() as TicketDoc))
    },
  })

  useImperativeHandle(
    ref,
    () => ({
      clear: () => {
        editor?.commands.clearContent(true)
      },
      focus: () => {
        editor?.commands.focus()
      },
    }),
    [editor],
  )

  return (
    <div
      className={cn(
        'overflow-hidden rounded-sm border bg-bg-surface transition-[border-color,box-shadow] duration-200 focus-within:ring-4 focus-within:ring-brand-accent/15',
        invalid ? 'border-danger' : 'border-border-default focus-within:border-brand-primary',
      )}
    >
      {editor && <EditorToolbar editor={editor} end={toolbarEnd} />}
      <EditorContent editor={editor} />
    </div>
  )
})

/** زر بشريط الأدوات — mousedown بدل click حتى لا يضيع التركيز من المحرر. */
function ToolButton({
  label,
  active,
  onClick,
  children,
}: {
  label: string
  active?: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-pressed={active}
      onMouseDown={(e) => {
        e.preventDefault()
        onClick()
      }}
      className={cn(
        'flex h-7 w-7 items-center justify-center rounded-xs text-text-secondary transition-colors hover:bg-bg-elevated hover:text-text-primary',
        active && 'bg-brand-primary/12 text-brand-primary',
      )}
    >
      {children}
    </button>
  )
}

/** شريط التنسيق — يقرأ حالة الأزرار فقط (useEditorState) فما يعيد رسم المحرر. */
function EditorToolbar({ editor, end }: { editor: Editor; end?: ReactNode }) {
  const state = useEditorState({
    editor,
    selector: ({ editor: e }) => ({
      bold: e.isActive('bold'),
      italic: e.isActive('italic'),
      underline: e.isActive('underline'),
      bullet: e.isActive('bulletList'),
      ordered: e.isActive('orderedList'),
    }),
  })
  const chain = () => editor.chain().focus()
  return (
    <div
      role="toolbar"
      aria-label="أدوات التنسيق"
      className="flex items-center gap-0.5 border-b border-border-default bg-bg-elevated/50 px-1.5 py-1"
    >
      <ToolButton label="عريض" active={state.bold} onClick={() => chain().toggleBold().run()}>
        <Bold size={15} />
      </ToolButton>
      <ToolButton label="مائل" active={state.italic} onClick={() => chain().toggleItalic().run()}>
        <Italic size={15} />
      </ToolButton>
      <ToolButton label="تسطير" active={state.underline} onClick={() => chain().toggleUnderline().run()}>
        <Underline size={15} />
      </ToolButton>
      <span className="mx-0.5 h-5 w-px bg-border-default" aria-hidden />
      <ToolButton label="قائمة مرقمة" active={state.ordered} onClick={() => chain().toggleOrderedList().run()}>
        <ListOrdered size={15} />
      </ToolButton>
      <ToolButton label="نقاط" active={state.bullet} onClick={() => chain().toggleBulletList().run()}>
        <List size={15} />
      </ToolButton>
      {end && <div className="ms-auto flex items-center gap-1">{end}</div>}
    </div>
  )
}
