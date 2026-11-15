import { useRef, useState } from 'react'
import SignatureCanvas from 'react-signature-canvas'
import { Eraser, PenLine, Trash2 } from 'lucide-react'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Modal } from '@/components/ui/Modal'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { Skeleton } from '@/components/ui/Skeleton'
import { ErrorState } from '@/components/ui/ErrorState'
import { useToast } from '@/components/ui/Toast'
import { useDeleteMySignature, useMySignature, useSaveMySignature } from '@/hooks/useUserSignature'
import { extractErrorMessage, formatDateTime } from '@/lib/utils'

/**
 * الهدف:
 * "توقيعي" في الملف الشخصي — المستخدم يرسم توقيعه ويحفظه في المنصة، ويقدر
 * يغيّره أو يحذفه، فيوقّع به المحاضر مباشرة بدل رسمه كل مرة (قرار صاحب
 * المشروع 2026-11-15).
 *
 * الحالات: تحميل، خطأ (مع إعادة المحاولة)، فارغ (بلا توقيع)، موجود. الحذف
 * يطلب تأكيدًا. التوقيعات السابقة على المحاضر لا تتأثر بالتغيير أو الحذف.
 * الصلاحيات: المستخدم نفسه فقط (الخادم يحدده من التوكن).
 */
export function MySignatureCard() {
  const query = useMySignature()
  const saveMutation = useSaveMySignature()
  const deleteMutation = useDeleteMySignature()
  const { showToast } = useToast()
  const padRef = useRef<SignatureCanvas>(null)
  const [drawOpen, setDrawOpen] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [drawn, setDrawn] = useState(false)
  const saved = query.data ?? null

  function save() {
    const pad = padRef.current
    if (!pad || pad.isEmpty()) return
    saveMutation.mutate(pad.toDataURL('image/png'), {
      onSuccess: () => {
        setDrawOpen(false)
        setDrawn(false)
        showToast('تم حفظ توقيعك')
      },
      onError: (err) => showToast(extractErrorMessage(err), 'error'),
    })
  }

  function remove() {
    deleteMutation.mutate(undefined, {
      onSuccess: () => {
        setConfirmDelete(false)
        showToast('تم حذف توقيعك المحفوظ')
      },
      onError: (err) => showToast(extractErrorMessage(err), 'error'),
    })
  }

  return (
    <Card>
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-text-primary">توقيعي</h3>
          <p className="mt-0.5 text-xs text-text-muted">احفظ توقيعك هنا لتوقّع به المحاضر مباشرة بدل رسمه كل مرة.</p>
        </div>
        {saved && (
          <div className="flex shrink-0 gap-2">
            <Button size="sm" variant="secondary" icon={<PenLine size={14} />} onClick={() => setDrawOpen(true)}>
              تغيير
            </Button>
            <Button size="sm" variant="ghost" icon={<Trash2 size={14} />} onClick={() => setConfirmDelete(true)}>
              حذف
            </Button>
          </div>
        )}
      </div>

      {query.isLoading ? (
        <Skeleton className="h-28 w-full" />
      ) : query.isError ? (
        <ErrorState title="تعذّر تحميل توقيعك" onRetry={() => query.refetch()} />
      ) : saved ? (
        <div className="flex flex-col items-center gap-2 rounded-md border border-border-default bg-white p-3">
          <img src={saved.signature_image} alt="توقيعي المحفوظ" className="h-28 w-full max-w-sm object-contain" />
          <p className="text-[11px] text-text-muted">آخر تحديث: {formatDateTime(saved.updated_at)}</p>
        </div>
      ) : (
        <div className="flex flex-col items-center gap-3 rounded-md border border-dashed border-border-default px-4 py-8 text-center">
          <p className="text-sm text-text-secondary">ما عندك توقيع محفوظ بعد.</p>
          <Button icon={<PenLine size={15} />} onClick={() => setDrawOpen(true)}>
            رسم توقيعي
          </Button>
        </div>
      )}

      <Modal
        open={drawOpen}
        onClose={() => setDrawOpen(false)}
        title={saved ? 'تغيير توقيعي' : 'رسم توقيعي'}
        description="ارسم توقيعك داخل الإطار، ثم اضغط حفظ."
        footer={
          <>
            <Button
              variant="ghost"
              icon={<Eraser size={14} />}
              onClick={() => {
                padRef.current?.clear()
                setDrawn(false)
              }}
            >
              مسح
            </Button>
            <Button loading={saveMutation.isPending} disabled={!drawn} onClick={save}>
              حفظ
            </Button>
          </>
        }
      >
        <div className="rounded-md border border-dashed border-border-default bg-white">
          <SignatureCanvas
            ref={padRef}
            penColor="#0f172a"
            onEnd={() => setDrawn(true)}
            canvasProps={{ className: 'h-48 w-full touch-none', 'aria-label': 'مساحة رسم التوقيع' }}
          />
        </div>
      </Modal>

      <ConfirmDialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        onConfirm={remove}
        title="حذف توقيعي المحفوظ؟"
        description="المحاضر اللي وقّعتها سابقًا لا تتأثر. تقدر ترسم توقيعًا جديدًا في أي وقت."
        confirmLabel="حذف"
        loading={deleteMutation.isPending}
      />
    </Card>
  )
}
