export type TaskStatus = 'open' | 'completed'
export type ViewId = 'inbox' | 'today' | 'upcoming' | 'completed'
export type Recurrence = 'none' | 'daily' | 'weekly'

export type Task = {
  id: string
  title: string
  notes: string
  status: TaskStatus
  dueAt?: string
  reminder?: string
  recurrence: Recurrence
  tags: string[]
  createdAt: string
  updatedAt: string
  deletedAt?: string
}

export type TaskDraft = Pick<Task, 'title' | 'notes' | 'dueAt' | 'reminder' | 'recurrence' | 'tags'>
