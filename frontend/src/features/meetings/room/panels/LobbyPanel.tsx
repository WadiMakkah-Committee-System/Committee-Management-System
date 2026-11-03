import { useState } from 'react'
import { Check, DoorOpen, UserCheck, X } from 'lucide-react'
import { useToast } from '@/components/ui/Toast'
import type { LobbyParticipant } from '../useTeamsEmbeddedCall'

/**
 * الهدف (قرار لاما 2026-11-03): قسم "قاعة الانتظار" بغرفة الاجتماع — المنتظرون
 * للدخول (ضيوف بدون حساب Microsoft بالشركة) مع قبول/رفض لكل واحد، وقبول الكل.
 *
 * يظهر فقط لمن دخل الاجتماع بحساب Microsoft (هو اللي يقدر يقبل بـTeams).
 * أعضاء اللجنة اللي دخلوا من المنصة يُقبلون تلقائيًا (useTeamsEmbeddedCall)،
 * فاللي يبقون هنا غالبًا دخلوا برابط Teams من خارج المنصة.
 *
 * المدخلات: participants (لقطة المنتظرين)، onAdmit(key?) — بدون key = قبول الكل،
 * onReject(key). فشل العملية = حسابك ما عنده صلاحية القبول بـTeams.
 */
export function LobbyPanel({
  participants,
  onAdmit,
  onReject,
}: {
  participants: LobbyParticipant[]
  onAdmit: (key?: string) => Promise<void>
  onReject: (key: string) => Promise<void>
}) {
  const { showToast } = useToast()
  const [busyKey, setBusyKey] = useState<string | null>(null)

  async function run(key: string, action: () => Promise<void>) {
    setBusyKey(key)
    try {
      await action()
    } catch {
      showToast('ما تملك صلاحية السماح بالدخول — يسمح بها منظّم الاجتماع أو رئيس اللجنة', 'error')
    } finally {
      setBusyKey(null)
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between gap-2 border-b border-border-default p-3">
        <div>
          <p className="text-[13px] font-semibold text-text-primary">قاعة الانتظار</p>
          <p className="text-[11px] text-text-muted">أعضاء اللجنة يدخلون تلقائيًا — هنا الباقين</p>
        </div>
        {participants.length > 1 && (
          <button
            type="button"
            disabled={busyKey !== null}
            onClick={() => void run('*', () => onAdmit())}
            className="flex shrink-0 items-center gap-1 rounded-md bg-brand-primary px-2.5 py-1.5 text-[11px] font-semibold text-white transition-all hover:brightness-110 disabled:opacity-60"
          >
            <UserCheck size={13} />
            قبول الكل
          </button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-2">
        {participants.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-10 text-center text-text-muted">
            <DoorOpen size={26} className="opacity-50" />
            <p className="text-xs">ما فيه أحد ينتظر الحين</p>
          </div>
        ) : (
          participants.map((p) => (
            <div key={p.key} className="flex items-center gap-2.5 rounded-md px-2 py-2 hover:bg-bg-elevated">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-warning-bg text-[12px] font-bold text-warning">
                {p.name.trim().charAt(0) || '؟'}
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13px] font-semibold text-text-primary">{p.name}</p>
                <p className="text-[11px] text-text-muted">ينتظر الدخول</p>
              </div>
              <button
                type="button"
                title="قبول"
                disabled={busyKey !== null}
                onClick={() => void run(p.key, () => onAdmit(p.key))}
                className="flex h-8 w-8 items-center justify-center rounded-full bg-success-bg text-success transition-colors hover:brightness-95 disabled:opacity-60"
              >
                <Check size={15} />
              </button>
              <button
                type="button"
                title="رفض"
                disabled={busyKey !== null}
                onClick={() => void run(p.key, () => onReject(p.key))}
                className="flex h-8 w-8 items-center justify-center rounded-full bg-danger-bg text-danger transition-colors hover:brightness-95 disabled:opacity-60"
              >
                <X size={15} />
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
