import { Building2, Calendar, KeyRound, Mail, ShieldCheck, User } from 'lucide-react'
import { useMe } from '@/hooks/useUsers'
import { Card } from '@/components/ui/Card'
import { Avatar } from '@/components/ui/Avatar'
import { UserStatusBadge, RoleBadge } from '@/components/ui/StatusBadge'
import { PageSpinner } from '@/components/ui/Spinner'
import { ErrorState } from '@/components/ui/ErrorState'
import { ROLE_LABELS, formatDateTime } from '@/lib/utils'

function InfoRow({ icon, label, value }: { icon: React.ReactNode; label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3 border-b border-border-default py-3.5 last:border-0">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-sm bg-bg-elevated text-text-muted">
        {icon}
      </div>
      <div className="flex flex-1 items-center justify-between gap-4">
        <span className="text-sm text-text-muted">{label}</span>
        <span className="text-sm font-medium text-text-primary">{value}</span>
      </div>
    </div>
  )
}

export function ProfilePage() {
  const { data: me, isLoading, isError, refetch } = useMe()

  if (isLoading) return <PageSpinner />
  if (isError || !me) return <ErrorState onRetry={() => refetch()} />

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <div>
        <h1 className="text-xl font-bold text-text-primary">الملف الشخصي</h1>
        <p className="mt-1 text-sm text-text-muted">بياناتك الشخصية وإدارتك في النظام</p>
      </div>

      <Card className="flex flex-col items-center gap-4 py-8 text-center sm:flex-row sm:text-right">
        <Avatar firstName={me.first_name} lastName={me.last_name} size={72} className="text-2xl" />
        <div className="flex flex-1 flex-col items-center gap-2 sm:items-start">
          <h2 className="text-lg font-bold text-text-primary">
            {me.first_name} {me.middle_name} {me.last_name}
          </h2>
          <p className="text-sm text-text-muted">@{me.username}</p>
          <div className="flex flex-wrap items-center justify-center gap-2 sm:justify-start">
            <RoleBadge role={me.role} label={ROLE_LABELS[me.role]} />
            <UserStatusBadge status={me.status} />
          </div>
        </div>
      </Card>

      <Card>
        <h3 className="mb-1 text-sm font-semibold text-text-primary">معلومات الحساب</h3>
        <div className="mt-2">
          <InfoRow icon={<Mail size={16} />} label="البريد الإلكتروني" value={me.email} />
          <InfoRow
            icon={<Building2 size={16} />}
            label="الإدارة"
            value={me.department ? me.department.name : 'بدون إدارة (سوبر أدمن)'}
          />
          <InfoRow icon={<ShieldCheck size={16} />} label="الدور" value={ROLE_LABELS[me.role]} />
          <InfoRow
            icon={<KeyRound size={16} />}
            label="آخر تسجيل دخول"
            value={formatDateTime(me.last_login_at)}
          />
          <InfoRow icon={<Calendar size={16} />} label="تاريخ إنشاء الحساب" value={formatDateTime(me.created_at)} />
          <InfoRow icon={<User size={16} />} label="معرّف المستخدم" value={<span className="font-mono text-xs">{me.user_id}</span>} />
        </div>
      </Card>
    </div>
  )
}
