import { Circle, CircleCheck, CircleX } from 'lucide-react'
import { cn } from '@/lib/utils'
import { PASSWORD_RULES } from './passwordPolicy'

interface PasswordRulesChecklistProps {
  /** كلمة المرور الجديدة كما تُكتب الآن. */
  password: string
  /** بعد محاولة حفظ فاشلة: القواعد غير المتحققة تظهر بلون الخطأ. */
  showUnmet?: boolean
  id?: string
}

/**
 * الهدف:
 * قائمة قواعد كلمة المرور تحت خانة كلمة المرور الجديدة — كل قاعدة تتحول
 * لعلامة ✓ خضراء أول ما تتحقق أثناء الكتابة (طلب صاحب المشروع 2026-11-10).
 *
 * المستخدِمون: ForgotPasswordPage (FR-UM-018) وChangePasswordModal (FR-UM-016).
 *
 * المدخلات: password (القيمة الحالية)، showUnmet (تلوين غير المتحقق بالأحمر
 * بعد محاولة الحفظ)، id (لربطها بالخانة عبر aria-describedby).
 *
 * المخرجات/التأثيرات: عرض فقط — بلا حالة ولا استدعاءات. القواعد من
 * PASSWORD_RULES (نفس قواعد التحقق عند الحفظ ونفس سياسة الباك إند).
 *
 * الوصول: كل قاعدة معها نص مخفي "متحقق/غير متحقق" لقارئ الشاشة، بدون
 * aria-live حتى لا يُقرأ التغيير مع كل حرف.
 */
export function PasswordRulesChecklist({ password, showUnmet = false, id }: PasswordRulesChecklistProps) {
  return (
    <ul id={id} aria-label="قواعد كلمة المرور" className="-mt-2 flex flex-col gap-1">
      {PASSWORD_RULES.map((rule) => {
        const met = rule.test(password)
        const failed = !met && showUnmet
        const Icon = met ? CircleCheck : failed ? CircleX : Circle
        return (
          <li
            key={rule.id}
            data-rule={rule.id}
            data-met={met}
            className={cn(
              'flex items-center gap-2 text-xs transition-colors duration-200',
              met ? 'text-success' : failed ? 'text-danger' : 'text-text-muted',
            )}
          >
            <Icon size={14} className="shrink-0" aria-hidden="true" />
            <span>{rule.label}</span>
            <span className="sr-only">{met ? '— متحقق' : '— غير متحقق'}</span>
          </li>
        )
      })}
    </ul>
  )
}
