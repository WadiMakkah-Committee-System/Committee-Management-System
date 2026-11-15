import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { EditorContent, useEditor, useEditorState, type Editor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import { Table, TableCell, TableHeader, TableRow } from '@tiptap/extension-table'
import TextAlign from '@tiptap/extension-text-align'
import { Placeholder } from '@tiptap/extensions'
import {
  AlignCenter,
  AlignLeft,
  AlignRight,
  BetweenHorizontalStart,
  BetweenVerticalStart,
  Bold,
  Italic,
  List,
  ListOrdered,
  PanelTop,
  Rows3,
  Columns3,
  Table as TableIcon,
  TableCellsMerge,
  TableCellsSplit,
  Trash2,
  Underline,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import type { EditorDoc } from './types'

/**
 * الهدف:
 * محرر نصوص غني "مثل الوورد" لأقسام القالب العام (الحيثيات، القرار، المناقشة،
 * الفقرتان اليدويتان) — مبني على TipTap (MIT، بموافقة صاحب المشروع 2026-11-15).
 *
 * المسموح فقط (يطابق القائمة البيضاء بالخادم — minutes_general/editor_content.py):
 * فقرات، عناوين 1–3، قوائم مرقمة ونقطية، جداول (إضافة/حذف صفوف وأعمدة، دمج
 * وتقسيم خلايا، صف عناوين)، عريض/مائل/تسطير، ومحاذاة. أي عنصر آخر (روابط،
 * اقتباس، كود...) معطّل حتى لا يدخل بالنسخ واللصق فيرفضه الخادم.
 *
 * المدخلات:
 * - value: مستند المحرر (JSON) أو null للفارغ.
 * - onChange: يُستدعى مع المستند الجديد (أو null لو صار فارغًا) عند كل تعديل.
 * - placeholder: نص إرشادي رمادي يختفي عند الكتابة.
 * - editable: false ⇒ عرض فقط (نفس الشكل بلا شريط أدوات).
 * - onFocus: لإعلان "أحرر هذا القسم الآن" للبقية.
 *
 * التزامن: لو تغيّرت value من الخارج (تحديث لحظي من عضو آخر) والمحرر غير
 * مُركَّز، يُستبدل المحتوى بدون إطلاق onChange. أثناء الكتابة نتجاهلها حتى لا
 * يضيع ما يكتبه المستخدم.
 */

const EXTENSIONS = [
  StarterKit.configure({
    blockquote: false,
    codeBlock: false,
    code: false,
    horizontalRule: false,
    link: false,
    strike: false,
    heading: { levels: [1, 2, 3] },
  }),
  TextAlign.configure({ types: ['heading', 'paragraph'], alignments: ['right', 'center', 'left', 'justify'] }),
  Table.configure({ resizable: false, HTMLAttributes: { class: 'minutes-rich-table' } }),
  TableRow,
  TableHeader,
  TableCell,
]

interface RichTextEditorProps {
  value: EditorDoc | null
  onChange?: (doc: EditorDoc | null) => void
  placeholder?: string
  editable?: boolean
  onFocus?: () => void
  className?: string
  ariaLabel?: string
}

/** مقارنة مستندين (JSON) — للتزامن من الخارج فقط. */
function sameDoc(a: EditorDoc | null, b: EditorDoc | null): boolean {
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null)
}

export function RichTextEditor({
  value,
  onChange,
  placeholder,
  editable = true,
  onFocus,
  className,
  ariaLabel,
}: RichTextEditorProps) {
  // آخر نسخة من الدوال للمحرر (يُنشأ مرة واحدة) — تُحدَّث بعد كل رسم لا أثناءه.
  const onChangeRef = useRef(onChange)
  const onFocusRef = useRef(onFocus)
  useLayoutEffect(() => {
    onChangeRef.current = onChange
    onFocusRef.current = onFocus
  })
  const [focused, setFocused] = useState(false)

  const editor = useEditor({
    extensions: [...EXTENSIONS, Placeholder.configure({ placeholder: placeholder ?? '' })],
    content: value ?? '',
    editable,
    editorProps: {
      attributes: {
        dir: 'rtl',
        class: 'minutes-rich-content',
        ...(ariaLabel ? { 'aria-label': ariaLabel } : {}),
      },
    },
    onUpdate: ({ editor: current }) => {
      // تعديلات المستخدم فقط (والمحرر مُركَّز): المكتبة تعدّل المستند تلقائيًا عند
      // التحميل (مثل تصحيح بنية الجداول) — بدون هذا الشرط كانت تُطلق حفظًا لم
      // يطلبه أحد بمجرد فتح المحضر، فيتعارض مع نسخ الخادم (409).
      if (!current.isFocused) return
      onChangeRef.current?.(current.isEmpty ? null : current.getJSON())
    },
    onFocus: () => {
      setFocused(true)
      onFocusRef.current?.()
    },
    onBlur: () => setFocused(false),
  })

  useEffect(() => {
    if (!editor || editor.isDestroyed) return
    editor.setEditable(editable)
  }, [editor, editable])

  useEffect(() => {
    if (!editor || editor.isDestroyed || editor.isFocused) return
    const current = editor.isEmpty ? null : editor.getJSON()
    if (!sameDoc(current, value)) editor.commands.setContent(value ?? '', { emitUpdate: false })
  }, [editor, value])

  if (!editor) return null
  return (
    <div className={cn('minutes-rich', editable && 'minutes-rich-editable', focused && 'is-focused', className)}>
      {editable && focused && <Toolbar editor={editor} />}
      <EditorContent editor={editor} />
    </div>
  )
}

function ToolButton({
  label,
  active,
  disabled,
  onClick,
  children,
}: {
  label: string
  active?: boolean
  disabled?: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-pressed={active}
      disabled={disabled}
      // mousedown بدل click: يمنع ضياع التركيز من المحرر قبل تنفيذ الأمر.
      onMouseDown={(e) => {
        e.preventDefault()
        if (!disabled) onClick()
      }}
      className={cn(
        'flex h-7 w-7 items-center justify-center rounded-xs text-text-secondary transition-colors hover:bg-bg-elevated hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-40',
        active && 'bg-brand-primary/12 text-brand-primary',
      )}
    >
      {children}
    </button>
  )
}

function Divider() {
  return <span className="mx-0.5 h-5 w-px bg-border-default" aria-hidden />
}

/** شريط الأدوات — يظهر فوق المحرر المُركَّز فقط (حتى لا تزدحم الصفحة). */
function Toolbar({ editor }: { editor: Editor }) {
  const state = useEditorState({
    editor,
    selector: ({ editor: e }) => ({
      bold: e.isActive('bold'),
      italic: e.isActive('italic'),
      underline: e.isActive('underline'),
      bullet: e.isActive('bulletList'),
      ordered: e.isActive('orderedList'),
      right: e.isActive({ textAlign: 'right' }),
      center: e.isActive({ textAlign: 'center' }),
      left: e.isActive({ textAlign: 'left' }),
      inTable: e.isActive('table'),
      canMerge: e.can().mergeCells(),
      canSplit: e.can().splitCell(),
    }),
  })
  const chain = () => editor.chain().focus()
  return (
    <div
      className="minutes-rich-toolbar sticky top-2 z-10 mb-2 flex flex-wrap items-center gap-0.5 rounded-sm border border-border-default bg-bg-surface p-1 shadow-sm"
      role="toolbar"
      aria-label="أدوات التنسيق"
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
      <Divider />
      <ToolButton label="قائمة مرقمة" active={state.ordered} onClick={() => chain().toggleOrderedList().run()}>
        <ListOrdered size={15} />
      </ToolButton>
      <ToolButton label="نقاط" active={state.bullet} onClick={() => chain().toggleBulletList().run()}>
        <List size={15} />
      </ToolButton>
      <Divider />
      <ToolButton label="محاذاة يمين" active={state.right} onClick={() => chain().setTextAlign('right').run()}>
        <AlignRight size={15} />
      </ToolButton>
      <ToolButton label="توسيط" active={state.center} onClick={() => chain().setTextAlign('center').run()}>
        <AlignCenter size={15} />
      </ToolButton>
      <ToolButton label="محاذاة يسار" active={state.left} onClick={() => chain().setTextAlign('left').run()}>
        <AlignLeft size={15} />
      </ToolButton>
      <Divider />
      <ToolButton
        label="إدراج جدول"
        onClick={() => chain().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()}
      >
        <TableIcon size={15} />
      </ToolButton>
      {state.inTable && (
        <>
          <ToolButton label="إضافة صف" onClick={() => chain().addRowAfter().run()}>
            <BetweenHorizontalStart size={15} />
          </ToolButton>
          <ToolButton label="إضافة عمود" onClick={() => chain().addColumnAfter().run()}>
            <BetweenVerticalStart size={15} />
          </ToolButton>
          <ToolButton label="حذف الصف" onClick={() => chain().deleteRow().run()}>
            <Rows3 size={15} />
          </ToolButton>
          <ToolButton label="حذف العمود" onClick={() => chain().deleteColumn().run()}>
            <Columns3 size={15} />
          </ToolButton>
          <ToolButton label="دمج الخلايا" disabled={!state.canMerge} onClick={() => chain().mergeCells().run()}>
            <TableCellsMerge size={15} />
          </ToolButton>
          <ToolButton label="تقسيم الخلية" disabled={!state.canSplit} onClick={() => chain().splitCell().run()}>
            <TableCellsSplit size={15} />
          </ToolButton>
          <ToolButton label="صف العناوين" onClick={() => chain().toggleHeaderRow().run()}>
            <PanelTop size={15} />
          </ToolButton>
          <ToolButton label="حذف الجدول" onClick={() => chain().deleteTable().run()}>
            <Trash2 size={15} />
          </ToolButton>
        </>
      )}
    </div>
  )
}
