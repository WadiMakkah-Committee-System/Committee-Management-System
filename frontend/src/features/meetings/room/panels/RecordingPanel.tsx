import { useEffect, useRef } from 'react'
import { AlertTriangle, FileAudio, Mic, Square } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { EmptyState } from '@/components/ui/EmptyState'
import { useToast } from '@/components/ui/Toast'
import { useMeetingRecording } from '@/hooks/useMeetings'
import { extractErrorMessage, formatDateTime } from '@/lib/utils'
import type { useAudioRecorder } from '../useAudioRecorder'

/**
 * لوحة "التسجيل الصوتي" داخل غرفة الاجتماع — تسجيل صوتي حقيقي بالمتصفح
 * (MediaRecorder API، وليس محاكاة) يُرفع لنفس Endpoint الفعلي المبني
 * بالباك-إند (app/services/meeting_service.py::upload_recording). التسجيل
 * نفسه (start/stop) لا يملك حالته هنا محليًا — مرفوع لمستوى
 * MeetingRoom.tsx (useAudioRecorder) لأن زر "تسجيل" بشريط التحكم السفلي
 * (MeetingControls.tsx) وشارة "جاري التسجيل" أعلى الفيديو
 * (MeetingStage.tsx) يحتاجان نفس المصدر الحي لحالة التسجيل — هذه اللوحة
 * تستهلك تلك الحالة عبر prop بدل امتلاكها.
 *
 * تعديل لاما 2026-09-06 (طلب صريح: "مربع مسودة الذكاء الاصطناعي المفترض
 * يحذف لان ماله داعي"): قسم "مسودة الذكاء الاصطناعي" الذي كان هنا سابقًا
 * حُذف بالكامل — المسودة الآن مكانها الوحيد صفحة تفاصيل الاجتماع
 * (MeetingDetailPage.tsx، قسم "التسجيل والمسودة") التي تبقى مفتوحة قبل
 * وبعد انتهاء الاجتماع، بخلاف هذه الغرفة التي تُغلق تلقائيًا بعد الانتهاء.
 */
export function RecordingPanel({
  meetingId,
  recorder,
}: {
  meetingId: string
  /** حالة التسجيل الحقيقية — مصدر واحد مشترك مع MeetingControls/MeetingStage،
   * مُنشَأة مرة واحدة بـMeetingRoom.tsx (راجعي room/useAudioRecorder.ts). */
  recorder: ReturnType<typeof useAudioRecorder>
}) {
  const { showToast } = useToast()
  const recordingQuery = useMeetingRecording(meetingId)

  // رسالة خطأ الرفع تظهر توستًا مرة واحدة فقط لكل فشل (لا نكرر التوست
  // بكل render طالما uploadError نفسه لم يتغيّر).
  const shownUploadErrorRef = useRef<unknown>(null)
  useEffect(() => {
    if (recorder.uploadError && recorder.uploadError !== shownUploadErrorRef.current) {
      shownUploadErrorRef.current = recorder.uploadError
      showToast(extractErrorMessage(recorder.uploadError), 'error')
    }
  }, [recorder.uploadError, showToast])

  useEffect(() => {
    if (recorder.micError) showToast(recorder.micError, 'error')
  }, [recorder.micError, showToast])

  const forbidden =
    (recordingQuery.error as { response?: { status?: number } } | undefined)?.response?.status === 403

  if (forbidden) {
    return (
      <div className="p-4">
        <EmptyState
          icon={<AlertTriangle size={22} />}
          title="لا صلاحية"
          description="ليست لديك صلاحية تسجيل هذا الاجتماع أو الاطلاع على مسودته."
        />
      </div>
    )
  }

  const recording = recordingQuery.data

  const minutes = String(Math.floor(recorder.elapsedSeconds / 60)).padStart(2, '0')
  const seconds = String(recorder.elapsedSeconds % 60).padStart(2, '0')

  return (
    <div className="flex flex-col gap-4 p-4">
      <section className="rounded-md border border-border-default bg-bg-surface p-4">
        <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-text-primary">
          <Mic size={16} className="text-brand-primary" />
          التسجيل الصوتي
        </h3>

        {recorder.isRecording ? (
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="h-2.5 w-2.5 animate-live-dot-pulse rounded-full bg-danger" />
              <span className="font-mono text-sm text-danger">
                {minutes}:{seconds}
              </span>
            </div>
            <Button size="sm" variant="danger" icon={<Square size={14} />} onClick={recorder.stop}>
              إيقاف ورفع
            </Button>
          </div>
        ) : (
          <Button
            size="sm"
            variant="secondary"
            icon={<Mic size={14} />}
            onClick={recorder.start}
            loading={recorder.isUploading}
          >
            بدء التسجيل
          </Button>
        )}

        {recording && !recorder.isRecording && (
          <div className="mt-3 flex items-center gap-2 rounded-sm bg-bg-elevated px-3 py-2 text-xs text-text-secondary">
            <FileAudio size={14} />
            <span className="truncate">{recording.file_name}</span>
            <span className="mr-auto shrink-0 text-text-muted">{formatDateTime(recording.recorded_at)}</span>
          </div>
        )}

        <p className="mt-3 text-xs text-text-muted">
          ستجدين التسجيل والمسودة الكاملة بصفحة تفاصيل هذا الاجتماع بعد انتهائه (قسم "التسجيل والمسودة").
        </p>
      </section>
    </div>
  )
}
