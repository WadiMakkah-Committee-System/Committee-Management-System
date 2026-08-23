import type { ReactNode } from 'react'
import { CheckCircle2, PauseCircle, ShieldCheck, User2, Crown, Briefcase, Sparkles } from 'lucide-react'
import { cn, roleLabel } from '@/lib/utils'
import type { RoleSummary, SystemRoleName, UserStatus } from '@/types'

type BadgeTone = 'success' | 'warning' | 'danger' | 'info' | 'neutral'

const TONE_CLASSES: Record<BadgeTone, string> = {
  success: 'bg-success-bg text-success border-success-border/30',
  warning: 'bg-warning-bg text-warning border-warning-border/30',
  danger: 'bg-danger-bg text-danger border-danger-border/30',
  info: 'bg-info-bg text-info border-info-border/30',
  neutral: 'bg-neutral-bg text-neutral border-neutral-border/30',
}

function Badge({ tone, icon, children }: { tone: BadgeTone; icon?: ReactNode; children: ReactNode }) {
  return (
    <span
      className={cn(
        'inline-flex w-fit items-center gap-1.5 rounded-xs border px-2 py-1 text-xs font-semibold',
        TONE_CLASSES[tone],
      )}
    >
      {icon}
      {children}
    </span>
  )
}

export function UserStatusBadge({ status }: { status: UserStatus }) {
  return status === 'active' ? (
    <Badge tone="success" icon={<CheckCircle2 size={13} />}>
      نشط
    </Badge>
  ) : (
    <Badge tone="neutral" icon={<PauseCircle size={13} />}>
      موقوف
    </Badge>
  )
}

const SYSTEM_ROLE_TONE: Record<SystemRoleName, BadgeTone> = {
  super_admin: 'danger',
  admin: 'info',
  executive_president: 'warning',
  executive_office_manager: 'neutral',
  executive_office_secretary: 'neutral',
}

const SYSTEM_ROLE_ICON: Record<SystemRoleName, ReactNode> = {
  super_admin: <ShieldCheck size={13} />,
  admin: <User2 size={13} />,
  executive_president: <Crown size={13} />,
  executive_office_manager: <Briefcase size={13} />,
  executive_office_secretary: <Briefcase size={13} />,
}

/** شارة الدور — تدعم الأدوار النظامية (ألوان/أيقونات ثابتة) والمخصَّصة (لون محايد + أيقونة عامة). */
export function RoleBadge({ role }: { role: RoleSummary }) {
  const tone = SYSTEM_ROLE_TONE[role.name as SystemRoleName] ?? 'info'
  const icon = SYSTEM_ROLE_ICON[role.name as SystemRoleName] ?? <Sparkles size={13} />
  return (
    <Badge tone={tone} icon={icon}>
      {roleLabel(role)}
    </Badge>
  )
}
