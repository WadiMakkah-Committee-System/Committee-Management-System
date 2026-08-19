import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as usersApi from '@/api/users'
import type { UserCreatePayload, UserUpdatePayload } from '@/types'

export const usersKeys = {
  all: ['users'] as const,
  me: ['users', 'me'] as const,
}

export function useMe() {
  return useQuery({ queryKey: usersKeys.me, queryFn: usersApi.fetchMe })
}

export function useUsers() {
  return useQuery({ queryKey: usersKeys.all, queryFn: usersApi.fetchUsers })
}

export function useCreateUser() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: UserCreatePayload) => usersApi.createUser(payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: usersKeys.all }),
  })
}

export function useUpdateUser() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ userId, payload }: { userId: string; payload: UserUpdatePayload }) =>
      usersApi.updateUser(userId, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: usersKeys.all }),
  })
}

export function useDeleteUser() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (userId: string) => usersApi.deleteUser(userId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: usersKeys.all }),
  })
}

export function useSuspendUser() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (userId: string) => usersApi.suspendUser(userId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: usersKeys.all }),
  })
}

export function useReactivateUser() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (userId: string) => usersApi.reactivateUser(userId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: usersKeys.all }),
  })
}
