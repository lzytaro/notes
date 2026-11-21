import { beforeEach, expect, it, vi } from 'vitest'
import type { Task } from './types'

const { execute } = vi.hoisted(() => ({ execute: vi.fn() }))
vi.mock('./notifications', () => ({ inTauri: () => true }))
vi.mock('@tauri-apps/plugin-sql', () => ({ default: { load: async () => ({ execute }) } }))
const task: Task = { id: 'write-test', title: '保存后升级', notes: '', status: 'open', recurrence: 'none', tags: [], createdAt: '2026-11-21T00:00:00Z', updatedAt: '2026-11-21T00:00:00Z' }

beforeEach(() => { vi.resetModules(); execute.mockReset(); execute.mockResolvedValue(undefined) })

it('holds installation until the task transaction commits', async () => {
  let commit!: () => void
  let commitStarted!: () => void
  const started = new Promise<void>((resolve) => { commitStarted = resolve })
  execute.mockImplementation((query: string) => query === 'COMMIT' ? new Promise<void>((resolve) => { commit = resolve; commitStarted() }) : Promise.resolve())
  const { saveTaskChanges, flushTaskWrites } = await import('./storage')
  const write = saveTaskChanges([task])
  let flushed = false
  const flush = flushTaskWrites().then(() => { flushed = true })
  await started
  expect(commit).toBeDefined()
  expect(flushed).toBe(false)
  commit(); await write; await flush
  expect(flushed).toBe(true)
})

it('blocks installation if a task could not be saved', async () => {
  execute.mockImplementation((query: string) => query.startsWith('INSERT INTO tasks') ? Promise.reject(new Error('disk full')) : Promise.resolve())
  const { saveTaskChanges, flushTaskWrites } = await import('./storage')
  await saveTaskChanges([task])
  expect(execute).toHaveBeenCalledWith('ROLLBACK')
  await expect(flushTaskWrites()).rejects.toThrow('任务未能保存')
})
