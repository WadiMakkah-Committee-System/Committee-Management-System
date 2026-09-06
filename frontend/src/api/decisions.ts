import { apiClient } from '@/lib/apiClient'
import type {
  Decision,
  DecisionCreatePayload,
  DecisionUpdatePayload,
  DecisionVoteChoice,
} from '@/types'

/**
 * وحدة "إدارة القرارات" — تقابل app/api/v1/decisions.py بالباك-إند.
 * القرارات المستقلة فقط (بدون قرارات مستخرجة من اجتماع بالذكاء
 * الاصطناعي — تُبنى لاحقًا). التفويض هيكلي (دور اللجنة/النظام)، وليس
 * صلاحية عامة ثابتة — راجعي hooks/useDecisions.ts وDecisionsPage.tsx.
 */

export async function fetchDecisions(): Promise<Decision[]> {
  const { data } = await apiClient.get<Decision[]>('/decisions')
  return data
}

export async function fetchDecision(decisionId: string): Promise<Decision> {
  const { data } = await apiClient.get<Decision>(`/decisions/${decisionId}`)
  return data
}

export async function createDecision(payload: DecisionCreatePayload): Promise<Decision> {
  const { data } = await apiClient.post<Decision>('/decisions', payload)
  return data
}

export async function updateDecision(
  decisionId: string,
  payload: DecisionUpdatePayload,
): Promise<Decision> {
  const { data } = await apiClient.patch<Decision>(`/decisions/${decisionId}`, payload)
  return data
}

export async function deleteDecision(decisionId: string): Promise<void> {
  await apiClient.delete(`/decisions/${decisionId}`)
}

export async function openVoting(
  decisionId: string,
  votingDeadline?: string | null,
): Promise<Decision> {
  const { data } = await apiClient.post<Decision>(`/decisions/${decisionId}/open-voting`, {
    voting_deadline: votingDeadline ?? null,
  })
  return data
}

export async function castVote(
  decisionId: string,
  choice: DecisionVoteChoice,
): Promise<Decision> {
  const { data } = await apiClient.post<Decision>(`/decisions/${decisionId}/vote`, { choice })
  return data
}

export async function approveDecision(decisionId: string): Promise<Decision> {
  const { data } = await apiClient.post<Decision>(`/decisions/${decisionId}/approve`)
  return data
}
