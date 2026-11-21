export const CHECK_INTERVAL = 6 * 60 * 60 * 1000
export const RETRY_INTERVAL = 15 * 60 * 1000

export type ReleaseInfo = {
  version: string
  name: string
  notes: string
  publishedAt: string | null
  prerelease: boolean
  available: boolean
  installable: boolean
  unavailableReason: string | null
}
export type CheckResult = { currentVersion: string; release: ReleaseInfo | null }
export type Progress = { downloaded: number; total: number | null }
type Phase = 'idle' | 'checking' | 'current' | 'available' | 'downloading' | 'ready' | 'installing' | 'error'
type Action = 'check' | 'download' | 'install'
export type UpdateSnapshot = {
  automatic: boolean
  includePrerelease: boolean
  lastChecked: number | null
  nextCheck: number
  retryAt: number
  currentVersion: string
  phase: Phase
  release: ReleaseInfo | null
  progress: Progress
  error: string | null
  retryAction: Action
}
export interface UpdateAdapter {
  check: (preview: boolean) => Promise<CheckResult>
  download: (progress: (value: Progress) => void) => Promise<void>
  install: () => Promise<void>
}
type Options = {
  adapter: UpdateAdapter
  version: string
  desktop: boolean
  now: () => number
  online: () => boolean
  read: () => string | null
  write: (value: string) => void
}

export class UpdateController {
  private state: UpdateSnapshot
  private listeners = new Set<() => void>()
  private busy = false
  private started = false
  private failures = 0
  constructor(private options: Options) {
    let stored: Partial<UpdateSnapshot> = {}
    try { stored = JSON.parse(options.read() || '{}') || {} } catch { /* recover corrupt preferences */ }
    const timestamp = (v: unknown) => typeof v === 'number' && Number.isFinite(v) && v > 0 ? v : 0
    this.state = {
      automatic: stored.automatic === true, includePrerelease: stored.includePrerelease === true,
      lastChecked: timestamp(stored.lastChecked) || null,
      nextCheck: Math.min(timestamp(stored.nextCheck), options.now() + CHECK_INTERVAL),
      retryAt: Math.min(timestamp(stored.retryAt), options.now() + CHECK_INTERVAL),
      currentVersion: options.version, phase: 'idle', release: null,
      progress: { downloaded: 0, total: null }, error: null, retryAction: 'check',
    }
  }
  getSnapshot = () => this.state
  subscribe = (listener: () => void) => {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }
  private patch(value: Partial<UpdateSnapshot>) {
    this.state = { ...this.state, ...value }
    const { automatic, includePrerelease, lastChecked, nextCheck, retryAt } = this.state
    if (['automatic', 'includePrerelease', 'lastChecked', 'nextCheck', 'retryAt'].some((key) => key in value)) {
      try { this.options.write(JSON.stringify({ automatic, includePrerelease, lastChecked, nextCheck, retryAt })) } catch { /* session still works */ }
    }
    this.listeners.forEach((listener) => listener())
  }
  start = () => {
    if (this.started) return
    this.started = true
    // One startup check, also when the main window stays hidden in the tray.
    if (this.state.automatic && this.options.now() >= this.state.retryAt) void this.check(false)
  }
  tick = () => {
    if (this.state.automatic && this.options.now() >= this.state.nextCheck
      && !(this.state.phase === 'error' && this.state.retryAction === 'install')
      && !['ready', 'installing'].includes(this.state.phase)) void this.check(false)
  }
  setAutomatic = (automatic: boolean) => {
    this.patch({ automatic })
    if (automatic && this.state.phase !== 'ready') void this.check(false)
  }
  setPreview = (includePrerelease: boolean) => {
    if (this.busy || this.state.includePrerelease === includePrerelease) return
    this.patch({ includePrerelease, phase: 'idle', release: null, error: null, nextCheck: 0 })
    if (this.state.automatic) void this.check(false)
  }
  private fail(error: unknown, action: Action) {
    const detail = typeof error === 'object' && error !== null ? error as { message?: unknown; retryAt?: unknown } : {}
    const message = typeof detail.message === 'string' ? detail.message : '操作未完成，请稍后重试。'
    const backoff = Math.min(RETRY_INTERVAL * 2 ** this.failures++, CHECK_INTERVAL)
    const retryAt = typeof detail.retryAt === 'number' && Number.isFinite(detail.retryAt)
      ? Math.min(Math.max(detail.retryAt, this.options.now() + 60_000), this.options.now() + CHECK_INTERVAL) : 0
    this.patch({ phase: 'error', error: message, retryAction: action, retryAt,
      nextCheck: Math.max(this.options.now() + backoff, retryAt) })
  }
  check = async (manual = true) => {
    if (!this.options.desktop || this.busy || this.state.phase === 'ready') return
    if (this.options.now() < this.state.retryAt) {
      if (manual) this.patch({ error: 'GitHub 请求频率受限，请在提示的时间后重试。', phase: 'error', retryAction: 'check' })
      return
    }
    if (!this.options.online()) {
      if (manual) this.patch({ phase: 'error', error: '当前处于离线状态，请联网后重试。', retryAction: 'check' })
      return
    }
    this.busy = true
    this.patch({ phase: 'checking', error: null, progress: { downloaded: 0, total: null } })
    let shouldDownload = false
    try {
      const result = await this.options.adapter.check(this.state.includePrerelease)
      this.failures = 0
      this.patch({ ...result, phase: result.release?.available ? 'available' : 'current',
        lastChecked: this.options.now(), nextCheck: this.options.now() + CHECK_INTERVAL, retryAt: 0 })
      shouldDownload = this.state.automatic && !!result.release?.installable
    } catch (error) {
      this.patch({ release: null })
      this.fail(error, 'check')
    } finally { this.busy = false }
    // Read the current preference after the request: switching off during a
    // check must not start a background download when that request resolves.
    if (shouldDownload && this.state.automatic) await this.download()
  }
  download = async () => {
    if (!this.options.desktop || this.busy || !this.state.release?.installable || this.state.phase === 'ready') return
    this.busy = true
    this.patch({ phase: 'downloading', error: null, progress: { downloaded: 0, total: null } })
    try {
      await this.options.adapter.download((progress) => this.patch({ progress }))
      this.patch({ phase: 'ready', error: null })
    } catch (error) { this.fail(error, 'download') }
    finally { this.busy = false }
  }
  install = async () => {
    if (!this.options.desktop || this.busy || !(this.state.phase === 'ready'
      || (this.state.phase === 'error' && this.state.retryAction === 'install'))) return
    this.busy = true
    this.patch({ phase: 'installing', error: null })
    try { await this.options.adapter.install() }
    catch (error) { this.fail(error, 'install') }
    finally { this.busy = false }
  }
  retry = () => this.state.retryAction === 'install' ? this.install()
    : this.state.retryAction === 'download' ? this.download() : this.check()
}
