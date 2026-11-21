import { describe, expect, it, vi } from 'vitest'
import { CHECK_INTERVAL, RETRY_INTERVAL, UpdateController, type CheckResult, type ReleaseInfo } from './updateController'

const release: ReleaseInfo = {
  version: '0.3.0', name: '纸笺 0.3.0', notes: '# 更新\n- 更流畅', publishedAt: null,
  prerelease: false, available: true, installable: true, unavailableReason: null,
}
function fixture(stored = '{}') {
  let now = 1_800_000_000_000
  let online = true
  const adapter = {
    check: vi.fn<() => Promise<CheckResult>>().mockResolvedValue({ currentVersion: '0.2.0', release }),
    download: vi.fn().mockResolvedValue(undefined), install: vi.fn().mockResolvedValue(undefined),
  }
  const write = vi.fn()
  const controller = new UpdateController({ adapter, version: '0.2.0', desktop: true,
    now: () => now, online: () => online, read: () => stored, write })
  return { controller, adapter, write, advance: (ms: number) => { now += ms }, offline: () => { online = false } }
}
const settle = async () => { for (let i = 0; i < 8; i++) await Promise.resolve() }

describe('application updates', () => {
  it('defaults to opt-in and manual check works with automatic updates off', async () => {
    const { controller, adapter } = fixture()
    controller.start(); controller.tick()
    expect(adapter.check).not.toHaveBeenCalled()
    await controller.check()
    expect(adapter.check).toHaveBeenCalledWith(false)
    expect(adapter.download).not.toHaveBeenCalled()
    expect(controller.getSnapshot().phase).toBe('available')
  })
  it('checks once at startup, downloads automatically and never installs automatically', async () => {
    const { controller, adapter } = fixture('{"automatic":true}')
    controller.start(); controller.start(); controller.tick()
    await settle()
    expect(adapter.check).toHaveBeenCalledTimes(1)
    expect(adapter.download).toHaveBeenCalledTimes(1)
    expect(controller.getSnapshot().phase).toBe('ready')
    expect(adapter.install).not.toHaveBeenCalled()
  })
  it('checks every six hours and catches up after sleep', async () => {
    const { controller, adapter, advance } = fixture('{"automatic":true}')
    adapter.check.mockResolvedValue({ currentVersion: '0.2.0', release: null })
    controller.start(); await settle()
    advance(CHECK_INTERVAL - 1); controller.tick(); await settle()
    expect(adapter.check).toHaveBeenCalledTimes(1)
    advance(10_000); controller.tick(); await settle()
    expect(adapter.check).toHaveBeenCalledTimes(2)
    controller.setAutomatic(false); advance(CHECK_INTERVAL); controller.tick(); await settle()
    expect(adapter.check).toHaveBeenCalledTimes(2)
  })
  it('turning off while checking prevents the pending automatic download', async () => {
    const { controller, adapter } = fixture()
    let finish!: (value: CheckResult) => void
    adapter.check.mockImplementation(() => new Promise((resolve) => { finish = resolve }))
    controller.setAutomatic(true)
    controller.setAutomatic(false)
    finish({ currentVersion: '0.2.0', release }); await settle()
    expect(adapter.download).not.toHaveBeenCalled()
  })
  it('deduplicates manual requests and retains a downloaded package until installation', async () => {
    const { controller, adapter, advance } = fixture('{"automatic":true}')
    await Promise.all([controller.check(), controller.check()])
    expect(adapter.check).toHaveBeenCalledTimes(1)
    advance(CHECK_INTERVAL); controller.tick(); await controller.check()
    expect(adapter.check).toHaveBeenCalledTimes(1)
    await controller.install()
    expect(adapter.install).toHaveBeenCalledTimes(1)
  })
  it('backs off on network failures but allows a manual retry', async () => {
    const { controller, adapter, advance } = fixture('{"automatic":true}')
    adapter.check.mockRejectedValueOnce({ message: '无法连接 GitHub' })
    await controller.check()
    controller.tick(); advance(RETRY_INTERVAL - 1); controller.tick()
    expect(adapter.check).toHaveBeenCalledTimes(1)
    await controller.check()
    expect(adapter.check).toHaveBeenCalledTimes(2)
  })
  it('honors GitHub rate limiting for manual and scheduled requests', async () => {
    const { controller, adapter, advance } = fixture('{"automatic":true}')
    adapter.check.mockRejectedValueOnce({ message: '请求过多', retryAt: 1_800_000_600_000 })
    await controller.check(); await controller.check(); controller.tick()
    expect(adapter.check).toHaveBeenCalledTimes(1)
    advance(600_001); await controller.check()
    expect(adapter.check).toHaveBeenCalledTimes(2)
  })
  it('keeps last successful check time when offline', async () => {
    const { controller, adapter, offline } = fixture()
    await controller.check()
    const checked = controller.getSnapshot().lastChecked
    offline(); await controller.check()
    expect(controller.getSnapshot().lastChecked).toBe(checked)
    expect(controller.getSnapshot().error).toContain('离线')
    expect(adapter.check).toHaveBeenCalledTimes(1)
  })
  it('invalidates the selected preview when changing channels', async () => {
    const { controller, adapter } = fixture()
    controller.setPreview(true); await controller.check()
    expect(adapter.check).toHaveBeenCalledWith(true)
    controller.setPreview(false)
    expect(controller.getSnapshot().release).toBeNull()
    await controller.download()
    expect(adapter.download).not.toHaveBeenCalled()
  })
  it('never downloads a release without a signed updater package', async () => {
    const { controller, adapter } = fixture('{"automatic":true}')
    adapter.check.mockResolvedValue({ currentVersion: '0.2.0', release: { ...release, installable: false } })
    await controller.check(); await controller.download()
    expect(adapter.download).not.toHaveBeenCalled()
  })
  it('offers download and install retries without losing the selected release', async () => {
    const { controller, adapter } = fixture()
    await controller.check()
    adapter.download.mockRejectedValueOnce({ message: '签名错误' })
    await controller.download()
    expect(controller.getSnapshot().retryAction).toBe('download')
    expect(adapter.install).not.toHaveBeenCalled()
    await controller.retry()
    expect(controller.getSnapshot().phase).toBe('ready')
    adapter.install.mockRejectedValueOnce({ message: '目录不可写' })
    await controller.install(); await controller.retry()
    expect(adapter.install).toHaveBeenCalledTimes(2)
  })
  it('recovers corrupt preferences and persists only settings, never packages or release HTML', async () => {
    const { controller, write } = fixture('{broken')
    await controller.check()
    expect(JSON.parse(write.mock.calls.at(-1)![0])).toEqual(expect.objectContaining({ automatic: false, includePrerelease: false }))
    expect(write.mock.calls.at(-1)![0]).not.toContain('notes')
  })
})
