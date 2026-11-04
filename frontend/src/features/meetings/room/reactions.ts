import type { ReactionType } from '@/hooks/useMeetingRealtime'

/** رموز التفاعلات (قرار لاما 2026-11-03) — مشتركة بين البطاقات وزر التفاعلات.
 * بعد الرجوع لـAgora (2026-11-04) تنبث عبر القناة اللحظية (room.signal). */
export const REACTION_EMOJI: Record<ReactionType, string> = {
  like: '👍',
  heart: '❤️',
  laugh: '😂',
  surprised: '😮',
  applause: '👏',
}
