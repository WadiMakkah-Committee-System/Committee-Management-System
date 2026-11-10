import { z } from 'zod'

/**
 * الهدف:
 * قواعد كلمة المرور الجديدة بالواجهة — مصدر واحد لنفس سياسة الباك إند
 * (validate_password_policy بـ app/core/security.py): 8 أحرف على الأقل،
 * حرف كبير، حرف صغير، ورقم.
 *
 * المستخدِمون:
 * - newPasswordSchema: التحقق عند الحفظ (ChangePasswordModal — FR-UM-016،
 *   وForgotPasswordPage — FR-UM-018).
 * - PASSWORD_RULES: قائمة القواعد اللي تتحدّث أثناء الكتابة
 *   (PasswordRulesChecklist — 2026-11-10).
 *
 * ملاحظة: تحقق الواجهة لتجربة المستخدم فقط — الفرض الحقيقي في الباك إند.
 */
export interface PasswordRule {
  id: 'length' | 'uppercase' | 'lowercase' | 'digit'
  /** نص القاعدة بالقائمة. */
  label: string
  /** رسالة الخطأ عند الحفظ لو لم تتحقق. */
  message: string
  test: (value: string) => boolean
}

export const PASSWORD_RULES: readonly PasswordRule[] = [
  { id: 'length', label: '8 أحرف على الأقل', message: 'يجب أن تحتوي على 8 أحرف على الأقل', test: (v) => v.length >= 8 },
  { id: 'uppercase', label: 'حرف كبير (A-Z)', message: 'يجب أن تحتوي على حرف كبير', test: (v) => /[A-Z]/.test(v) },
  { id: 'lowercase', label: 'حرف صغير (a-z)', message: 'يجب أن تحتوي على حرف صغير', test: (v) => /[a-z]/.test(v) },
  { id: 'digit', label: 'رقم (0-9)', message: 'يجب أن تحتوي على رقم', test: (v) => /[0-9]/.test(v) },
]

/** التحقق عند الحفظ — أول قاعدة غير متحققة تظهر رسالتها تحت الخانة. */
export const newPasswordSchema = z.string().superRefine((value, ctx) => {
  const failed = PASSWORD_RULES.find((rule) => !rule.test(value))
  if (failed) ctx.addIssue({ code: 'custom', message: failed.message })
})
