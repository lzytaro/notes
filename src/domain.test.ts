import { describe, expect, it } from 'vitest'
import { nextOccurrence } from './recurrence'
import { mergeTasks, type RemoteTask } from './sync'
import type { Task } from './types'

const task = (overrides: Partial<Task> = {}): Task => ({
  id: 'task-1',
  title: '本地标题',
  notes: '',
  status: 'open',
  dueAt: '2026-11-20T09:00',
  recurrence: 'none',
  tags: [],
  createdAt: '2026-11-20T08:00:00.000Z',
  updatedAt: '2026-11-20T09:00:00.000Z',
  ...overrides,
})

const remote = (overrides: Partial<RemoteTask> = {}): RemoteTask => ({
  id: 'task-1',
  user_id: 'user-1',
  title: '云端标题',
  notes: '',
  status: 'open',
  due_at: '2026-11-20T09:00',
  reminder: null,
  recurrence: 'none',
  tags: [],
  created_at: '2026-11-20T08:00:00.000Z',
  updated_at: '2026-11-20T08:30:00.000Z',
  deleted_at: null,
  ...overrides,
})

describe('recurrence', () => {
  it('moves daily tasks to the next future occurrence', () => {
    expect(nextOccurrence('2026-11-20T09:00', 'daily', new Date('2026-11-20T12:00'))).toBe('2026-11-21T09:00')
  })

  it('moves weekly tasks by seven days', () => {
    expect(nextOccurrence('2026-11-20T09:00', 'weekly', new Date('2026-11-20T12:00'))).toBe('2026-11-27T09:00')
  })
})

describe('sync merge', () => {
  it('keeps the newer local task', () => {
    expect(mergeTasks([task({ title: '本地更新', updatedAt: '2026-11-20T10:00:00.000Z' })], [remote()])[0].title).toBe('本地更新')
  })

  it('keeps the newer cloud task', () => {
    expect(mergeTasks([task()], [remote({ title: '云端更新', updated_at: '2026-11-20T10:00:00.000Z' })])[0].title).toBe('云端更新')
  })

  it('preserves cloud tombstones during merge', () => {
    const merged = mergeTasks([task()], [remote({ deleted_at: '2026-11-20T10:00:00.000Z', updated_at: '2026-11-20T11:00:00.000Z' })])
    expect(merged[0].deletedAt).toBe('2026-11-20T10:00:00.000Z')
  })
})
