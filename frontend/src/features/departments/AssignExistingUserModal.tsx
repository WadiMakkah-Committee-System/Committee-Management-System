import { useEffect, useMemo, useState } from 'react'
import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import type { User } from '@/types'
import { DepartmentUserPicker } from './DepartmentUserPicker'

interface AssignExistingUserModalProps {
  open: boolean
  onClose: () => void
  /** كل المستخدمين بالنظام — يُستبعد منها من هو أصلاً بهذه الإدارة (candidates بالخارج). */
  candidates: User[]
  onAssign: (userIds: string[]) => void
  loading?: boolean
  serverError?: string | null
  /**
   * التحديد الحالي — مُتحكَّم به من الصفحة الأم (DepartmentDetailPage) وليس
   * حالة داخلية، لأنه بعد فشل جزئي (بعض المستخدمين نجح والبعض فشل) تحتاج
   * الصفحة الأم إعادة ضبط التحديد ليقتصر على من فشل فقط، بدل ما يضل
   * المودال محتفظ بكل التحديد الأصلي ويعيد إرسال الطلب لمن نجح من قبل
   * أيضًا عند إعادة المحاولة (ملاحظة مراجعة CodeRabbit على PR #55).
   */
  selectedIds: string[]
  onSelectedIdsChange: (ids: string[]) => void
  /**
   * اسم الإدارة المستهدَفة — تُعرض بنص تأكيد النقل أدناه. طلب صريح من
   * المستخدمة 2026-09-22: هذه النافذة تسمح أيضًا بـ"نقل" مستخدم موجود
   * أصلاً بإدارة أخرى (وليس فقط إضافة مين بلا إدارة)، فلازم تأكيد واضح
   * قبل تنفيذ النقل الفعلي (PATCH يغيّر dep_id) بدل تنفيذه صامتًا.
   */
  targetDepartmentName: string
}

/**
 * إضافة مستخدم (أو أكثر) **موجود مسبقًا** لهذه الإدارة — بديل لفتح نموذج
 * تسجيل مستخدم جديد بالكامل (قرار المستخدمة 2026-09-13: زر "إضافة
 * مستخدم" بصفحة تفاصيل الإدارة كان يفتح UserFormModal دائمًا، حتى لو
 * المستخدم المطلوب إضافته موجود أصلاً بالنظام بإدارة أخرى أو بدون إدارة).
 *
 * التنفيذ الفعلي لعملية النقل هو PATCH /users/{id} بحقل dep_id فقط —
 * نفس الـendpoint المستخدَم أصلاً بتعديل بيانات مستخدم (useUpdateUser).
 * القائمة هنا Multi-select عبر Checkboxes (بنفس نمط MemberPicker
 * بوحدة اللجان) — طلب صريح من المستخدمة 2026-09-21: الاختيار الأحادي
 * (Radio) كان يفرض تكرار فتح النافذة والضغط على "إضافة" لكل مستخدم على
 * حدة عند إضافة عدة أعضاء دفعة واحدة لنفس الإدارة. onAssign يستقبل الآن
 * مصفوفة معرّفات، وتتولى الصفحة المستدعية (DepartmentDetailPage) تنفيذ
 * PATCH لكل مستخدم على حدة بالتتابع.
 *
 * تحديث 2026-09-22 (طلب صريح من المستخدمة): بما أن هذه النافذة تسمح
 * بنقل مستخدم من إدارة أخرى (لا تقتصر على مين بلا إدارة)، أُضيف تأكيد
 * صريح (ConfirmDialog) يظهر مرة واحدة عند الضغط على "إضافة" — وليس عند
 * كل تحديد مربع على حدة — يسرد أسماء مين سيُنقَل فعليًا من إدارته
 * الحالية قبل تنفيذ العملية. لا يظهر التأكيد إطلاقًا لو كل المحدَّدين
 * بلا إدارة أصلًا.
 */
export function AssignExistingUserModal({
  open,
  onClose,
  candidates,
  onAssign,
  loading,
  serverError,
  selectedIds,
  onSelectedIdsChange,
  targetDepartmentName,
}: AssignExistingUserModalProps) {
  const [confirmOpen, setConfirmOpen] = useState(false)
  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds])

  // إعادة ضبط تأكيد النقل عند كل فتح جديد للنافذة — الأب يتحكم بـ open
  // مباشرة (قد يُغلقها بعد نجاح الإضافة بدون المرور بـhandleClose هنا).
  useEffect(() => {
    if (open) setConfirmOpen(false)
  }, [open])

  const usersToMove = useMemo(
    () => candidates.filter((u) => selectedSet.has(u.user_id) && u.department),
    [candidates, selectedSet],
  )

  function handleClose() {
    setConfirmOpen(false)
    onSelectedIdsChange([])
    onClose()
  }

  function handleAssignClick() {
    if (selectedIds.length === 0) return
    if (usersToMove.length > 0) {
      setConfirmOpen(true)
      return
    }
    onAssign(selectedIds)
  }

  function handleConfirmMove() {
    setConfirmOpen(false)
    onAssign(selectedIds)
  }

  const moveConfirmDescription =
    usersToMove.length > 0
      ? `سيتم نقل الأعضاء التالية أسماؤهم من إداراتهم الحالية إلى إدارة "${targetDepartmentName}": ` +
        usersToMove
          .map((u) => `${u.first_name} ${u.last_name} (من إدارة ${u.department!.name})`)
          .join('، ') +
        '. هل أنت متأكد من المتابعة؟'
      : ''

  return (
    <>
      <Modal
        open={open}
        onClose={handleClose}
        title="إضافة مستخدمين إلى الإدارة"
        description="ابحث عن مستخدمين مسجَّلين بالنظام مسبقًا واختر واحدًا أو أكثر لإضافتهم لهذه الإدارة دفعة واحدة — لإنشاء مستخدم جديد بالكامل استخدم صفحة المستخدمين."
        footer={
          <>
            <Button variant="secondary" onClick={handleClose}>
              إلغاء
            </Button>
            <Button onClick={handleAssignClick} disabled={selectedIds.length === 0 || loading} loading={loading}>
              {selectedIds.length > 0 ? `إضافة (${selectedIds.length}) إلى الإدارة` : 'إضافة إلى الإدارة'}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          {serverError && (
            <p className="rounded-sm border border-danger/30 bg-danger/5 px-3 py-2 text-xs font-medium text-danger">
              {serverError}
            </p>
          )}

          <DepartmentUserPicker
            candidates={candidates}
            selectedIds={selectedIds}
            onSelectedIdsChange={onSelectedIdsChange}
          />
        </div>
      </Modal>

      <ConfirmDialog
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        onConfirm={handleConfirmMove}
        title="تأكيد نقل الأعضاء"
        description={moveConfirmDescription}
        confirmLabel="تأكيد النقل"
        variant="primary"
        loading={loading}
      />
    </>
  )
}
