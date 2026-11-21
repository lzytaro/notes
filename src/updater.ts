import { useEffect, useSyncExternalStore } from 'react'
import { Channel, invoke } from '@tauri-apps/api/core'
import { version } from '../package.json'
import { inTauri } from './notifications'
import { flushTaskWrites } from './storage'
import { UpdateController, type CheckResult, type Progress } from './updateController'

export const updater = new UpdateController({
  version, desktop: inTauri(), now: Date.now, online: () => navigator.onLine,
  read: () => localStorage.getItem('notes-updates-v1'),
  write: (value) => localStorage.setItem('notes-updates-v1', value),
  adapter: {
    check: (includePrerelease) => invoke<CheckResult>('check_for_updates', { includePrerelease }),
    download: (onProgress) => {
      const onProgressChannel = new Channel<Progress>()
      onProgressChannel.onmessage = onProgress
      return invoke<void>('download_update', { onProgress: onProgressChannel })
    },
    install: async () => { await flushTaskWrites(); await invoke<void>('install_update') },
  },
})

export function useUpdater() {
  const snapshot = useSyncExternalStore(updater.subscribe, updater.getSnapshot)
  useEffect(() => {
    updater.start()
    const timer = window.setInterval(updater.tick, 60_000)
    window.addEventListener('online', updater.tick)
    window.addEventListener('focus', updater.tick)
    document.addEventListener('visibilitychange', updater.tick)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener('online', updater.tick)
      window.removeEventListener('focus', updater.tick)
      document.removeEventListener('visibilitychange', updater.tick)
    }
  }, [])
  return snapshot
}
