import type { Task } from './types'
import { supabase } from './supabase'
import { clearPendingChanges } from './storage'

export type RemoteTask = {
  id: string
  user_id: string
  title: string
  notes: string
  status: Task['status']
  due_at: string | null
  reminder: string | null
  recurrence: Task['recurrence']
  tags: string[]
  created_at: string
  updated_at: string
  deleted_at: string | null
}

const toRemote = (task: Task, userId: string): RemoteTask => ({
  id: task.id,
  user_id: userId,
  title: task.title,
  notes: task.notes,
  status: task.status,
  due_at: task.dueAt || null,
  reminder: task.reminder || null,
  recurrence: task.recurrence,
  tags: task.tags,
  created_at: task.createdAt,
  updated_at: task.updatedAt,
  deleted_at: task.deletedAt || null,
})

const fromRemote = (task: RemoteTask): Task => ({
  id: task.id,
  title: task.title,
  notes: task.notes || '',
  status: task.status,
  dueAt: task.due_at || undefined,
  reminder: task.reminder || undefined,
  recurrence: task.recurrence,
  tags: task.tags || [],
  createdAt: task.created_at,
  updatedAt: task.updated_at,
  deletedAt: task.deleted_at || undefined,
})

export function mergeTasks(localTasks: Task[], remote: RemoteTask[]) {
  const localById = new Map(localTasks.map((task) => [task.id, task]))
  const remoteById = new Map(remote.map((task) => [task.id, task]))
  const merged: Task[] = []

  for (const task of localTasks) {
    const cloud = remoteById.get(task.id)
    if (!cloud || new Date(task.updatedAt).getTime() >= new Date(cloud.updated_at).getTime()) {
      merged.push(task)
    } else {
      merged.push(fromRemote(cloud))
    }
  }

  for (const cloud of remote) {
    if (!localById.has(cloud.id)) merged.push(fromRemote(cloud))
  }

  return merged
}

export async function syncTasks(localTasks: Task[]) {
  if (!supabase) return { tasks: localTasks, connected: false, message: '尚未配置云同步' }

  const { data: auth } = await supabase.auth.getUser()
  if (!auth.user) return { tasks: localTasks, connected: false, message: '请先登录' }

  const cursorKey = `notes-last-sync:${auth.user.id}`
  const cursor = localStorage.getItem(cursorKey)
  let query = supabase.from('tasks').select('*').eq('user_id', auth.user.id)
  if (cursor) query = query.gt('updated_at', cursor)
  const { data: remoteRows, error: fetchError } = await query

  if (fetchError) return { tasks: localTasks, connected: true, message: fetchError.message }

  const remote = (remoteRows || []) as RemoteTask[]
  const merged = mergeTasks(localTasks, remote)

  const payload = merged.map((task) => toRemote(task, auth.user.id))
  const { error: pushError } = await supabase.from('tasks').upsert(payload, { onConflict: 'user_id,id' })
  if (pushError) return { tasks: merged, connected: true, message: pushError.message }

  await clearPendingChanges()
  const latestRemote = remote.reduce((latest, task) => task.updated_at > latest ? task.updated_at : latest, cursor || '')
  localStorage.setItem(cursorKey, latestRemote || new Date().toISOString())

  return { tasks: merged, connected: true, message: `已同步 ${merged.length} 个任务` }
}
