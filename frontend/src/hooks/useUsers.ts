import { useEffect } from 'react'
import { useMutation, useQuery, useQueryClient, type Query } from '@tanstack/react-query'
import * as usersApi from '@/api/users'
import { notify } from '@/components/ui/Toast'
import { departmentsKeys } from '@/hooks/useDepartments'
import { rolesKeys } from '@/hooks/useRoles'
import { ACTIVE_ROLE_CHANGED_EVENT } from '@/lib/activeRole'
import { roleLabel } from '@/lib/utils'
import { useAuthStore } from '@/store/authStore'
import type { UserCreatePayload, UserDetail, UserUpdatePayload } from '@/types'

export const usersKeys = {
  all: ['users'] as const,
  me: ['users', 'me'] as const,
  detail: (userId: string) => ['users', userId] as const,
}

/**
 * أي عملية تُغيّر مستخدمًا (إنشاء/تعديل/حذف/إيقاف/تفعيل) قد تُغيّر أيضًا
 * قائمة أعضاء إدارته (صفحة تفاصيل الإدارة) وعدد المستخدمين المرتبطين
 * بدوره (تبويب الأدوار والصلاحيات) — لذلك تُبطَل الثلاثة معًا دائمًا بدل
 * تكرار هذا المنطق في كل mutation على حدة.
 */
function invalidateUserRelatedQueries(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: usersKeys.all })
  queryClient.invalidateQueries({ queryKey: departmentsKeys.all })
  queryClient.invalidateQueries({ queryKey: rolesKeys.all })
}

export function useMe() {
  return useQuery({ queryKey: usersKeys.me, queryFn: usersApi.fetchMe })
}

/** options.enabled: لقوائم الاختيار داخل نماذج مغلقة افتراضيًا — لا تُجلب قائمة
 * كل المستخدمين إلا عند فتح النموذج فعليًا (نفس نمط useRoles/useJobTitles). */
export function useUsers(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: usersKeys.all,
    queryFn: () => usersApi.fetchUsers(),
    enabled: options?.enabled ?? true,
  })
}

export function useUserDetail(userId: string | undefined) {
  return useQuery({
    queryKey: usersKeys.detail(userId ?? ''),
    queryFn: () => usersApi.fetchUser(userId as string),
    enabled: !!userId,
  })
}

export function useCreateUser() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: UserCreatePayload) => usersApi.createUser(payload),
    onSuccess: () => invalidateUserRelatedQueries(queryClient),
  })
}

export function useUpdateUser() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ userId, payload }: { userId: string; payload: UserUpdatePayload }) =>
      usersApi.updateUser(userId, payload),
    onSuccess: (_data, variables) => {
      invalidateUserRelatedQueries(queryClient)
      queryClient.invalidateQueries({ queryKey: usersKeys.detail(variables.userId) })
    },
  })
}

export function useDeleteUser() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (userId: string) => usersApi.deleteUser(userId),
    onSuccess: () => invalidateUserRelatedQueries(queryClient),
  })
}

export function useSuspendUser() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (userId: string) => usersApi.suspendUser(userId),
    onSuccess: (_data, userId) => {
      invalidateUserRelatedQueries(queryClient)
      queryClient.invalidateQueries({ queryKey: usersKeys.detail(userId) })
    },
  })
}

export function useReactivateUser() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (userId: string) => usersApi.reactivateUser(userId),
    onSuccess: (_data, userId) => {
      invalidateUserRelatedQueries(queryClient)
      queryClient.invalidateQueries({ queryKey: usersKeys.detail(userId) })
    },
  })
}

/**
 * رفع ملف المستخدمين (users.import): ينشئ المستخدمين ثم يحدّث قوائم
 * المستخدمين والإدارات (قد تُنشأ إدارات جديدة) والأدوار.
 */
export function useImportUsers() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => usersApi.importUsers(file),
    onSuccess: () => invalidateUserRelatedQueries(queryClient),
  })
}

/** تحميل نموذج رفع المستخدمين كملف .xlsx (يمر عبر axios لأن التحميل يحتاج التوكن). */
export function useDownloadImportTemplate() {
  return useMutation({
    mutationFn: async () => {
      const blob = await usersApi.fetchImportTemplate()
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = 'نموذج_بيانات_المستخدمين.xlsx'
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    },
  })
}

/** كل الاستعلامات المخزّنة ما عدا /users/me نفسه (يُضبط يدويًا من الرد). */
const isNotMeQuery = (query: Query) => !(query.queryKey[0] === 'users' && query.queryKey[1] === 'me')

/**
 * الهدف: تطبيق بيانات مستخدم بدور حالي جديد على الواجهة كاملة.
 *
 * التأثيرات الجانبية: يحدّث authStore (القائمة الجانبية/الصلاحيات تتبعه
 * فورًا)، ويضبط /users/me بالكاش، ويعيد ضبط كل البيانات المخزّنة الأخرى —
 * ما يظهر لكل دور يختلف (طلبات، مستخدمون، وثائق...)، فالاستعلامات المعروضة
 * حاليًا تُجلب من جديد بالدور الجديد.
 */
async function applyActiveRoleUser(
  queryClient: ReturnType<typeof useQueryClient>,
  setUser: (user: UserDetail) => void,
  me: UserDetail,
): Promise<void> {
  setUser(me)
  queryClient.setQueryData(usersKeys.me, me)
  await queryClient.resetQueries({ predicate: isNotMeQuery })
}

/**
 * تبديل الدور الحالي (مبدّل الأدوار بالشريط العلوي، ورسالة "هذه الصفحة
 * تتبع دورًا آخر") — تعدد الأدوار، migration 0046. الصلاحيات كلها تُفحص
 * بالباك-إند؛ الواجهة فقط تعرض ما يرجّعه بعد التبديل.
 */
export function useSwitchActiveRole() {
  const queryClient = useQueryClient()
  const setUser = useAuthStore((s) => s.setUser)
  return useMutation({
    mutationFn: (roleId: string) => usersApi.switchActiveRole(roleId),
    onSuccess: async (me) => {
      await applyActiveRoleUser(queryClient, setUser, me)
      notify(`تم التبديل إلى دور «${roleLabel(me.role)}»`, 'success')
    },
  })
}

/**
 * الهدف:
 * مزامنة النافذة الحالية لو تغيّر الدور الحالي من نافذة/تبويب آخر — يستقبل
 * حدث ACTIVE_ROLE_CHANGED_EVENT (يطلقه apiClient عند رد 409
 * active_role_changed) فيعيد جلب /users/me ويطبّقه.
 *
 * يُستدعى مرة واحدة بـAppShell. طلبات متزامنة كثيرة قد ترجع 409 معًا — علم
 * syncing يمنع تكرار الجلب.
 */
export function useActiveRoleSync() {
  const queryClient = useQueryClient()
  const setUser = useAuthStore((s) => s.setUser)

  useEffect(() => {
    let syncing = false
    const handler = async () => {
      if (syncing) return
      syncing = true
      try {
        const me = await usersApi.fetchMe()
        await applyActiveRoleUser(queryClient, setUser, me)
        notify(`تغيّر دورك الحالي من نافذة أخرى — تعرض الآن صلاحيات «${roleLabel(me.role)}»`, 'info')
      } catch {
        // فشل الجلب نفسه (جلسة منتهية...) يعالجه apiClient (تسجيل خروج + رسالة).
      } finally {
        syncing = false
      }
    }
    window.addEventListener(ACTIVE_ROLE_CHANGED_EVENT, handler)
    return () => window.removeEventListener(ACTIVE_ROLE_CHANGED_EVENT, handler)
  }, [queryClient, setUser])
}
