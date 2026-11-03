import type { CaptionLine } from './useTeamsEmbeddedCall'

/**
 * الترجمة النصية الحية تحت الفيديو (قرار لاما 2026-11-03): آخر سطور الكلام
 * باسم المتحدث — الجملة اللي لسا تنقال تظهر باهتة لين تكتمل.
 */
export function CaptionsOverlay({ lines, error }: { lines: CaptionLine[]; error: string | null }) {
  if (error) {
    return (
      <div className="pointer-events-none absolute inset-x-0 bottom-24 z-10 mx-auto w-fit max-w-[80%] rounded-md bg-black/75 px-3 py-1.5 text-center text-[12px] text-warning">
        {error}
      </div>
    )
  }
  if (lines.length === 0) return null
  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-24 z-10 mx-auto flex w-[min(720px,90%)] flex-col gap-1 rounded-md bg-black/75 px-4 py-2.5">
      {lines.slice(-3).map((line) => (
        <p key={line.id} className={line.final ? 'text-[14px] text-white' : 'text-[14px] text-white/60'}>
          <span className="font-semibold text-brand-accent">{line.speakerName}: </span>
          {line.text}
        </p>
      ))}
    </div>
  )
}
