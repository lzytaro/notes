import type { Recurrence } from './types'

const toLocalInput = (date: Date) => {
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export function nextOccurrence(dueAt: string, recurrence: Recurrence, now = new Date()) {
  if (recurrence === 'none') return dueAt
  const next = new Date(dueAt)
  const days = recurrence === 'daily' ? 1 : 7
  do {
    next.setDate(next.getDate() + days)
  } while (next <= now)
  return toLocalInput(next)
}
