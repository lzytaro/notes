import type { Task } from './types'
import { inTauri } from './notifications'

type StoredTask = {
  id: string
  title: string
  notes: string
  status: Task['status']
  due_at: string | null
  reminder: string | null
  recurrence: Task['recurrence']
  tags: string
  created_at: string
  updated_at: string
  deleted_at: string | null
}

type SyncOutboxRow = {
  task_id: string
  operation: 'upsert' | 'delete'
  payload: string
  changed_at: string
}

const DB_PATH = 'sqlite:notes.db'
let databasePromise: Promise<import('@tauri-apps/plugin-sql').default> | null = null

async function getDatabase() {
  if (!inTauri()) return null
  if (!databasePromise) {
    databasePromise = import('@tauri-apps/plugin-sql').then(async ({ default: Database }) => {
      const database = await Database.load(DB_PATH)
      await database.execute(`
        CREATE TABLE IF NOT EXISTS tasks (
          id TEXT PRIMARY KEY NOT NULL,
          title TEXT NOT NULL,
          notes TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL,
          due_at TEXT,
          reminder TEXT,
          recurrence TEXT NOT NULL DEFAULT 'none',
          tags TEXT NOT NULL DEFAULT '[]',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          deleted_at TEXT
        )
      `)
      await database.execute('ALTER TABLE tasks ADD COLUMN deleted_at TEXT').catch(() => {})
      await database.execute(`
        CREATE TABLE IF NOT EXISTS sync_outbox (
          task_id TEXT PRIMARY KEY NOT NULL,
          operation TEXT NOT NULL,
          payload TEXT NOT NULL,
          changed_at TEXT NOT NULL
        )
      `)
      return database
    })
  }
  return databasePromise
}

export async function loadTasks(fallback: Task[]) {
  const database = await getDatabase()
  if (!database) {
    const saved = localStorage.getItem('notes-tasks-v1')
    return saved ? (JSON.parse(saved) as Task[]) : fallback
  }

  try {
    const rows = await database.select<StoredTask[]>(
      'SELECT id, title, notes, status, due_at, reminder, recurrence, tags, created_at, updated_at, deleted_at FROM tasks ORDER BY updated_at DESC',
    )
    if (rows.length === 0) {
      await saveTasks(fallback)
      return fallback
    }
    return rows.map((row) => ({
      id: row.id,
      title: row.title,
      notes: row.notes,
      status: row.status,
      dueAt: row.due_at || undefined,
      reminder: row.reminder || undefined,
      recurrence: row.recurrence,
      tags: JSON.parse(row.tags || '[]') as string[],
      createdAt: row.created_at,
      updatedAt: row.updated_at,
      deletedAt: row.deleted_at || undefined,
    }))
  } catch {
    return fallback
  }
}

const pendingWrites = new Set<Promise<void>>()
let writeFailed = false

// Installation can terminate the process (especially on Windows). Wait for
// task writes already accepted by this window before handing off to the installer.
export async function flushTaskWrites() {
  while (pendingWrites.size) await Promise.all([...pendingWrites])
  if (writeFailed) throw new Error('本次会话有任务未能保存，请先确认任务数据，再安装更新。')
}

export function saveTaskChanges(changedTasks: Task[], allTasks = changedTasks) {
  const write = persistTaskChanges(changedTasks, allTasks).catch(() => { writeFailed = true })
  pendingWrites.add(write)
  void write.finally(() => pendingWrites.delete(write))
  return write
}

async function persistTaskChanges(changedTasks: Task[], allTasks: Task[]) {
  if (!inTauri()) {
    localStorage.setItem('notes-tasks-v1', JSON.stringify(allTasks))
    return
  }

  const database = await getDatabase()
  if (!database) return

  try {
    await database.execute('BEGIN')
    for (const task of changedTasks) {
      await database.execute(
        `INSERT INTO tasks (id, title, notes, status, due_at, reminder, recurrence, tags, created_at, updated_at, deleted_at)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
         ON CONFLICT(id) DO UPDATE SET
           title = excluded.title,
           notes = excluded.notes,
           status = excluded.status,
           due_at = excluded.due_at,
           reminder = excluded.reminder,
           recurrence = excluded.recurrence,
           tags = excluded.tags,
           created_at = excluded.created_at,
           updated_at = excluded.updated_at,
           deleted_at = excluded.deleted_at`,
        [
          task.id,
          task.title,
          task.notes,
          task.status,
          task.dueAt || null,
          task.reminder || null,
          task.recurrence,
          JSON.stringify(task.tags),
          task.createdAt,
          task.updatedAt,
          task.deletedAt || null,
        ],
      )
      await database.execute(
        `INSERT INTO sync_outbox (task_id, operation, payload, changed_at)
         VALUES ($1, $2, $3, $4)
         ON CONFLICT(task_id) DO UPDATE SET
           operation = excluded.operation,
           payload = excluded.payload,
           changed_at = excluded.changed_at`,
        [task.id, task.deletedAt ? 'delete' : 'upsert', JSON.stringify(task), task.updatedAt],
      )
    }
    await database.execute('COMMIT')
  } catch (error) {
    await database.execute('ROLLBACK').catch(() => {})
    throw error
  }
}

export async function saveTasks(tasks: Task[]) {
  return saveTaskChanges(tasks, tasks)
}

export async function clearPendingChanges() {
  const database = await getDatabase()
  if (database) await database.execute('DELETE FROM sync_outbox')
}

export async function pendingChanges() {
  const database = await getDatabase()
  if (!database) return [] as SyncOutboxRow[]
  return database.select<SyncOutboxRow[]>('SELECT task_id, operation, payload, changed_at FROM sync_outbox ORDER BY changed_at ASC')
}
