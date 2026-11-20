import { inTauri } from './notifications'

export async function openDesktopWidget(kind: 'next' | 'today' | 'capture' = 'next') {
  if (!inTauri()) return false
  const { invoke } = await import('@tauri-apps/api/core')
  await invoke('open_widget', { kind })
  return true
}

export async function showMainWindow() {
  if (!inTauri()) return false
  const { invoke } = await import('@tauri-apps/api/core')
  await invoke('show_main_window')
  return true
}

export async function openQuickAddFromWidget() {
  if (!inTauri()) return false
  await showMainWindow()
  const { emit } = await import('@tauri-apps/api/event')
  await emit('open-quick-add')
  return true
}

export async function announceTasksChanged() {
  if (!inTauri()) return
  const { emit } = await import('@tauri-apps/api/event')
  await emit('tasks-changed')
}

export async function listenTasksChanged(callback: () => void) {
  if (!inTauri()) return () => {}
  const { listen } = await import('@tauri-apps/api/event')
  return listen('tasks-changed', callback)
}
