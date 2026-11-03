import type { Reaction } from '@azure/communication-calling'

/** رموز تفاعلات Teams (قرار لاما 2026-11-03) — مشتركة بين البطاقات وزر التفاعلات. */
export const REACTION_EMOJI: Record<Reaction, string> = {
  like: '👍',
  heart: '❤️',
  laugh: '😂',
  surprised: '😮',
  applause: '👏',
}
