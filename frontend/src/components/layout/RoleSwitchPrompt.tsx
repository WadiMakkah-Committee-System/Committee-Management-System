import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ArrowLeftRight, LayoutDashboard } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { notify } from '@/components/ui/Toast'
import { useSwitchActiveRole } from '@/hooks/useUsers'
import { extractErrorMessage, roleLabel } from '@/lib/utils'
import type { RoleSummary } from '@/types'

interface RoleSwitchPromptProps {
  /** الدور الحالي (اللي لا يفتح الصفحة). */
  currentRole: RoleSummary | null
  /** أدوار المستخدم الأخرى اللي تفتحها — otherRolesGrantingAccess(). */
  candidates: RoleSummary[]
}

/**
 * الهدف:
 * بدل تحويل المستخدم متعدد الأدوار بصمت لما يفتح صفحة (أو إشعارًا) تتبع
 * دورًا آخر من أدواره، توضّح له السبب وتعرض زر التبديل لذلك الدور مباشرة
 * — تعدد الأدوار، migration 0046 (شرط متفق عليه بخطة الميزة).
 *
 * المسؤولية: عرض الرسالة + أزرار التبديل. بعد التبديل يبقى على نفس الصفحة
 * (ProtectedRoute يعيد التقييم بالدور الجديد تلقائيًا).
 *
 * التأثيرات الجانبية: POST /users/me/active-role عبر useSwitchActiveRole.
 *
 * الصلاحيات: عرض فقط — الباك-إند يرفض أي تبديل لدور غير مسند، وكل بيانات
 * الصفحة نفسها تُفحص بالدور الجديد بعد التبديل.
 */
export function RoleSwitchPrompt({ currentRole, candidates }: RoleSwitchPromptProps) {
  const navigate = useNavigate()
  const switchMutation = useSwitchActiveRole()

  async function switchTo(roleId: string) {
    try {
      await switchMutation.mutateAsync(roleId)
    } catch (error) {
      notify(extractErrorMessage(error), 'error')
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
      className="mx-auto mt-10 flex max-w-lg flex-col items-center gap-4 rounded-md border border-border-default bg-bg-surface px-6 py-10 text-center"
    >
      <span className="flex h-14 w-14 items-center justify-center rounded-2xl border border-border-default bg-brand-primary/[0.06] text-brand-primary">
        <ArrowLeftRight size={24} />
      </span>
      <div className="flex flex-col gap-1.5">
        <h1 className="text-base font-semibold text-text-primary">هذه الصفحة تتبع دورًا آخر من أدوارك</h1>
        <p className="text-sm leading-relaxed text-text-muted">
          دورك الحالي «{roleLabel(currentRole)}» لا يملك صلاحية فتحها. بدّل إلى الدور المناسب للمتابعة.
        </p>
      </div>
      <div className="flex flex-wrap justify-center gap-2">
        {candidates.map((role) => (
          <Button
            key={role.role_id}
            icon={<ArrowLeftRight size={16} />}
            loading={switchMutation.isPending && switchMutation.variables === role.role_id}
            disabled={switchMutation.isPending}
            onClick={() => switchTo(role.role_id)}
          >
            التبديل إلى «{roleLabel(role)}»
          </Button>
        ))}
        <Button variant="ghost" icon={<LayoutDashboard size={16} />} onClick={() => navigate('/dashboard')}>
          لوحة التحكم
        </Button>
      </div>
    </motion.div>
  )
}
