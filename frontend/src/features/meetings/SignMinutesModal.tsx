import { useRef, useState } from 'react'
import SignatureCanvas from 'react-signature-canvas'
import { BadgeCheck, Eraser } from 'lucide-react'
import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'
import { Skeleton } from '@/components/ui/Skeleton'
import { useToast } from '@/components/ui/Toast'
import { useSignMinutes } from '@/hooks/useMeetingMinutes'
import { useMySignature } from '@/hooks/useUserSignature'
import { extractErrorMessage, formatDateTime } from '@/lib/utils'

/**
 * الهدف:
 * نافذة التوقيع الإلكتروني على المحضر (لكل القوالب) — خياران:
 * 1) التوقيع بتوقيعي المحفوظ في المنصة (يظهر فقط لو عندي توقيع محفوظ) — الخادم
 *    يقرأ صورته بنفسه، فلا تُرسل من هنا.
 * 2) رسم التوقيع الآن، مع خيار "احفظه للمرات الجاية".
 *
 * المدخلات: open/onClose، meetingId، onSigned (بعد نجاح التوقيع).
 * التأثيرات الجانبية: POST /minutes/sign (وقد يحفظ "توقيعي" بالخادم).
 * الأخطاء: تظهر كـToast (النافذة تغطي جسم الصفحة).
 */

interface SignMinutesModalProps {
  open: boolean
  onClose: () => void
  meetingId: string
  onSigned?: () => void
}

export function SignMinutesModal({ open, onClose, meetingId, onSigned }: SignMinutesModalProps) {
  const padRef = useRef<SignatureCanvas>(null)
  const [saveForLater, setSaveForLater] = useState(false)
  const [drawn, setDrawn] = useState(false)
  const savedQuery = useMySignature(open)
  const signMutation = useSignMinutes()
  const { showToast } = useToast()
  const saved = savedQuery.data ?? null

  const finish = () => {
    padRef.current?.clear()
    setDrawn(false)
    setSaveForLater(false)
    onSigned?.()
    onClose()
  }

  const onError = (err: unknown) => showToast(extractErrorMessage(err), 'error')

  function signWithSaved() {
    signMutation.mutate({ meetingId, useSaved: true }, { onSuccess: finish, onError })
  }

  function signWithDrawing() {
    const pad = padRef.current
    if (!pad || pad.isEmpty()) {
      showToast('ارسم توقيعك داخل الإطار أولًا', 'info')
      return
    }
    // toDataURL مباشرة (لا getTrimmedCanvas — راجعي تعليق 2026-09-10 بصفحة المحضر).
    const image = pad.toDataURL('image/png')
    signMutation.mutate({ meetingId, signatureImage: image, saveForLater }, { onSuccess: finish, onError })
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="التوقيع الإلكتروني"
      description={saved ? 'وقّع بتوقيعك المحفوظ، أو ارسم توقيعًا جديدًا.' : 'ارسم توقيعك داخل الإطار أدناه، ثم اضغط حفظ التوقيع.'}
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
          <Button loading={signMutation.isPending} disabled={!drawn} onClick={signWithDrawing}>
            حفظ التوقيع
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {savedQuery.isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : saved ? (
          <div className="flex flex-col gap-3 rounded-md border border-border-default bg-bg-elevated p-3 sm:flex-row sm:items-center">
            <img
              src={saved.signature_image}
              alt="توقيعي المحفوظ"
              className="h-20 w-full rounded-sm border border-border-default bg-white object-contain sm:w-48"
            />
            <div className="flex flex-1 flex-col gap-2">
              <p className="text-xs text-text-muted">توقيعك المحفوظ — آخر تحديث {formatDateTime(saved.updated_at)}</p>
              <Button
                icon={<BadgeCheck size={15} />}
                loading={signMutation.isPending}
                onClick={signWithSaved}
                className="w-fit"
              >
                التوقيع بتوقيعي المحفوظ
              </Button>
            </div>
          </div>
        ) : null}

        <div>
          {saved && <p className="mb-2 text-xs font-medium text-text-muted">أو ارسم توقيعًا جديدًا:</p>}
          <div className="rounded-md border border-dashed border-border-default bg-white">
            <SignatureCanvas
              ref={padRef}
              penColor="#0f172a"
              onEnd={() => setDrawn(true)}
              canvasProps={{ className: 'h-48 w-full touch-none', 'aria-label': 'مساحة رسم التوقيع' }}
            />
          </div>
          <label className="mt-3 flex cursor-pointer items-center gap-2 text-sm text-text-secondary">
            <input
              type="checkbox"
              checked={saveForLater}
              onChange={(e) => setSaveForLater(e.target.checked)}
              className="h-4 w-4 accent-[var(--brand-primary)]"
            />
            {saved ? 'استبدل توقيعي المحفوظ بهذا التوقيع' : 'احفظه للمرات الجاية'}
          </label>
        </div>
      </div>
    </Modal>
  )
}
