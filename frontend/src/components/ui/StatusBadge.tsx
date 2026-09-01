import type { ReactNode } from 'react'
import {
  CheckCircle2,
  PauseCircle,
  ShieldCheck,
  User2,
  Crown,
  Briefcase,
  Sparkles,
  FileEdit,
  Send,
  Eye,
  Undo2,
  Clock3,
  XCircle,
  CalendarClock,
  Video,
  Archive,
} from 'lucide-react'
import { cn, roleLabel } from '@/lib/utils'
import type { CommitteeRequestStatus, CommitteeRoleSlug, MeetingStatus, RoleSummary, SystemRoleName, UserStatus } from '@/types'

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
export function RoleBadge({ role }: { role: RoleSummary | null }) {
  // مراجعة لاما 2026-08-30: مستخدم بلا دور مُعيَّن (role=null) حالة صالحة الآن.
  if (!role) {
    return (
      <Badge tone="neutral" icon={<Sparkles size={13} />}>
        {roleLabel(null)}
      </Badge>
    )
  }
  const tone = SYSTEM_ROLE_TONE[role.name as SystemRoleName] ?? 'info'
  const icon = SYSTEM_ROLE_ICON[role.name as SystemRoleName] ?? <Sparkles size={13} />
  return (
    <Badge tone={tone} icon={icon}>
      {roleLabel(role)}
    </Badge>
  )
}

/** تسميات وألوان حالات طلب تشكيل اللجنة — تطابق CommitteeRequestStatus (راجعي types/index.ts). */
const COMMITTEE_REQUEST_STATUS_META: Record<
  CommitteeRequestStatus,
  { label: string; tone: BadgeTone; icon: ReactNode }
> = {
  draft: { label: 'مسودة', tone: 'neutral', icon: <FileEdit size={13} /> },
  submitted: { label: 'مُرسَل', tone: 'info', icon: <Send size={13} /> },
  under_review: { label: 'قيد المراجعة', tone: 'info', icon: <Eye size={13} /> },
  returned: { label: 'مُعاد للتعديل', tone: 'warning', icon: <Undo2 size={13} /> },
  pending_approval: { label: 'بانتظار الاعتماد', tone: 'warning', icon: <Clock3 size={13} /> },
  approved: { label: 'معتمد', tone: 'success', icon: <CheckCircle2 size={13} /> },
  rejected: { label: 'مرفوض', tone: 'danger', icon: <XCircle size={13} /> },
}

export function CommitteeRequestStatusBadge({ status }: { status: CommitteeRequestStatus }) {
  const meta = COMMITTEE_REQUEST_STATUS_META[status]
  return (
    <Badge tone={meta.tone} icon={meta.icon}>
      {meta.label}
    </Badge>
  )
}

/**
 * دور اللجنة (رئيس/عضو) — مراجعة لاما 2026-09-01: "لما الشخص يدخل لجنته
 * يعرف اذا هو رئيس لجنة او عضو لجنة". تُستخدم بصفحة تفاصيل اللجنة لكل
 * من: شارة بارزة بأعلى الصفحة توضّح دور المستخدم الحالي نفسه، وشارة بجانب
 * كل عضو بقائمة الأعضاء.
 */
const COMMITTEE_ROLE_META: Record<'chair' | 'member', { label: string; tone: BadgeTone; icon: ReactNode }> = {
  chair: { label: 'رئيس اللجنة', tone: 'warning', icon: <Crown size={13} /> },
  member: { label: 'عضو اللجنة', tone: 'info', icon: <User2 size={13} /> },
}

export function CommitteeRoleBadge({ slug }: { slug: CommitteeRoleSlug }) {
  if (!slug) return null
  const meta = COMMITTEE_ROLE_META[slug]
  return (
    <Badge tone={meta.tone} icon={meta.icon}>
      {meta.label}
    </Badge>
  )
}

/** تسميات وألوان حالات الاجتماع — تطابق MeetingStatus (راجعي types/index.ts). */
const MEETING_STATUS_META: Record<MeetingStatus, { label: string; tone: BadgeTone; icon: ReactNode }> = {
  upcoming: { label: 'قادم', tone: 'info', icon: <CalendarClock size={13} /> },
  ongoing: { label: 'جارٍ', tone: 'success', icon: <Video size={13} /> },
  finished: { label: 'منتهٍ', tone: 'neutral', icon: <CheckCircle2 size={13} /> },
  recorded: { label: 'مسجَّل', tone: 'warning', icon: <Archive size={13} /> },
}

export function MeetingStatusBadge({ status }: { status: MeetingStatus }) {
  const meta = MEETING_STATUS_META[status]
  return (
    <Badge tone={meta.tone} icon={meta.icon}>
      {meta.label}
    </Badge>
  )
}
