import { describe, expect, it } from 'vitest'
import { notificationLinkPath } from './notificationDisplay'
import type { Notification } from '@/types'

describe('notificationLinkPath — التذاكر', () => {
  it('إشعار التذكرة يفتح صفحتها (نفس الرابط للطرفين)', () => {
    const notification = { related_entity_type: 'ticket', related_entity_id: 't-42' } as Notification
    expect(notificationLinkPath(notification)).toBe('/tickets/t-42')
  })
})
