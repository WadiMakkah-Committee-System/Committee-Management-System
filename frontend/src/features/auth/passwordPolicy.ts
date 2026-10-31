import { z } from 'zod'

/**
 * الهدف:
 * قاعدة تحقق موحّدة لكلمة المرور الجديدة بالواجهة — نفس سياسة الباك إند
 * (validate_password_policy بـ app/core/security.py): 8 أحرف على الأقل،
 * حرف كبير، حرف صغير، ورقم.
 *
 * المستخدِمون: ChangePasswordModal (FR-UM-016) وForgotPasswordPage (FR-UM-018).
 * ملاحظة: تحقق الواجهة لتجربة المستخدم فقط — الفرض الحقيقي في الباك إند.
 */
export const newPasswordSchema = z
  .string()
  .min(8, 'يجب أن تحتوي على 8 أحرف على الأقل')
  .regex(/[A-Z]/, 'يجب أن تحتوي على حرف كبير')
  .regex(/[a-z]/, 'يجب أن تحتوي على حرف صغير')
  .regex(/[0-9]/, 'يجب أن تحتوي على رقم')

/** نص المساعدة الظاهر تحت خانة كلمة المرور الجديدة. */
export const NEW_PASSWORD_HINT = '8 أحرف على الأقل، حرف كبير وصغير ورقم'
