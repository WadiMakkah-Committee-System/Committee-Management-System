import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'
import { applyOptimistic, patchEverywhere, removeFromLists, rollbackOptimistic } from './optimistic'

type Item = { id: string; status: string }

function client() {
  const qc = new QueryClient()
  qc.setQueryData(['tasks'], [
    { id: 'a', status: 'todo' },
    { id: 'b', status: 'todo' },
  ])
  qc.setQueryData(['tasks', 'a'], { id: 'a', status: 'todo' })
  qc.setQueryData(['tasks', 'a', 'activity'], [{ label: 'x' }])
  return qc
}

describe('optimistic helpers', () => {
  it('removes an item from every list but leaves detail objects alone', async () => {
    const qc = client()
    await applyOptimistic(qc, [{ queryKey: ['tasks'], update: removeFromLists<Item>((t) => t.id === 'a') }])
    expect(qc.getQueryData<Item[]>(['tasks'])?.map((t) => t.id)).toEqual(['b'])
    expect(qc.getQueryData(['tasks', 'a'])).toEqual({ id: 'a', status: 'todo' })
    expect(qc.getQueryData(['tasks', 'a', 'activity'])).toEqual([{ label: 'x' }])
  })

  it('patches the item in lists and in its detail object', async () => {
    const qc = client()
    await applyOptimistic(qc, [
      {
        queryKey: ['tasks'],
        update: patchEverywhere<Item>((t) => t.id === 'a', (t) => ({ ...t, status: 'done' })),
      },
    ])
    expect(qc.getQueryData<Item[]>(['tasks'])?.[0].status).toBe('done')
    expect(qc.getQueryData<Item[]>(['tasks'])?.[1].status).toBe('todo')
    expect(qc.getQueryData<Item>(['tasks', 'a'])?.status).toBe('done')
  })

  it('rolls everything back exactly', async () => {
    const qc = client()
    const before = qc.getQueryData(['tasks'])
    const snapshot = await applyOptimistic(qc, [
      { queryKey: ['tasks'], update: removeFromLists<Item>((t) => t.id === 'a') },
    ])
    rollbackOptimistic(qc, snapshot)
    expect(qc.getQueryData(['tasks'])).toEqual(before)
  })

  it('exact targets only touch that key', async () => {
    const qc = client()
    await applyOptimistic(qc, [
      { queryKey: ['tasks'], exact: true, update: patchEverywhere<Item>((t) => t.id === 'a', (t) => ({ ...t, status: 'done' })) },
    ])
    expect(qc.getQueryData<Item>(['tasks', 'a'])?.status).toBe('todo')
  })
})
