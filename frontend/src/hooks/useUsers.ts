import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as usersApi from '@/api/users'
import { departmentsKeys } from '@/hooks/useDepartments'
import { rolesKeys } from '@/hooks/useRoles'
import type { UserCreatePayload, UserUpdatePayload } from '@/types'

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

export function useUsers() {
  return useQuery({ queryKey: usersKeys.all, queryFn: () => usersApi.fetchUsers() })
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
