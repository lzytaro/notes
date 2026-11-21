import { ArrowDownToLine, CheckCircle2, RefreshCw, ShieldCheck } from 'lucide-react'
import { inTauri } from './notifications'
import type { UpdateSnapshot } from './updateController'
import { updater } from './updater'

const timeLabel = (value: number) => new Date(value).toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })

export function UpdateSettings({ state }: { state: UpdateSnapshot }) {
  const { phase, release, progress } = state
  const busy = ['checking', 'downloading', 'installing'].includes(phase)
  const desktop = inTauri()
  const percent = progress.total ? Math.min(100, Math.floor(progress.downloaded / progress.total * 100)) : null
  const status = !desktop ? '请在桌面版检查更新' : phase === 'checking' ? '正在检查 GitHub 发布…'
    : phase === 'downloading' ? `正在下载${percent === null ? '…' : ` · ${percent}%`}`
      : phase === 'installing' ? '正在安装，即将重新打开纸笺…'
        : phase === 'ready' ? `v${release?.version} 已准备好`
          : phase === 'error' ? '更新未完成'
            : phase === 'available' ? `发现新版本 v${release?.version}`
              : phase === 'current' ? release ? '已是当前频道最新版本' : `暂无${state.includePrerelease ? '可用' : '正式'}发布`
                : '让纸笺保持更新'
  return <section className="update-settings" aria-labelledby="update-heading">
    <div className="update-section-title"><h3 id="update-heading">软件更新</h3><span>当前 v{state.currentVersion}</span></div>
    <div className="update-options">
      <div className="settings-row"><span className="settings-icon"><RefreshCw size={17} /></span><div><strong>自动检查并下载</strong><span>启动时及每 6 小时检查，安装前由你确认。</span></div><button className={`switch ${state.automatic ? 'on' : ''}`} role="switch" aria-label="自动检查并下载更新" aria-checked={state.automatic} disabled={!desktop || phase === 'installing'} onClick={() => updater.setAutomatic(!state.automatic)}><span /></button></div>
      <div className="settings-row update-preview-option"><div><strong>接收预览版本</strong><span>提前体验新功能，可能包含尚未完善的细节。</span></div><button className={`switch ${state.includePrerelease ? 'on' : ''}`} role="switch" aria-label="接收预览版本" aria-checked={state.includePrerelease} disabled={!desktop || busy} onClick={() => updater.setPreview(!state.includePrerelease)}><span /></button></div>
    </div>
    <div className={`update-status-card ${phase === 'error' ? 'has-error' : ''}`}>
      <div className="update-status-top"><span className={`update-status-icon ${busy ? 'is-working' : ''}`}>{busy ? <RefreshCw size={19} /> : phase === 'ready' || phase === 'current' ? <CheckCircle2 size={20} /> : <ArrowDownToLine size={20} />}</span><div role="status" aria-live="polite"><strong>{status}</strong><p>{phase === 'error' ? state.error : phase === 'ready' ? '签名校验通过，方便时再安装。' : phase === 'downloading' ? '可以关闭设置继续记录，下载会在后台完成。' : release?.unavailableReason || (state.lastChecked ? `上次检查：${timeLabel(state.lastChecked)}` : '更新与发布说明来自 lzytaro/notes。')}</p></div></div>
      {phase === 'downloading' && <div className="update-progress"><progress max={100} value={percent ?? undefined} aria-label="更新包下载进度" /><span>{(progress.downloaded / 1024 / 1024).toFixed(1)} MB{progress.total ? ` / ${(progress.total / 1024 / 1024).toFixed(1)} MB` : ''} · 下载后验证签名</span></div>}
      {state.retryAt > Date.now() && <p className="update-footnote">可重试时间：{timeLabel(state.retryAt)}</p>}
      <div className="update-actions">
        {phase === 'ready' ? <button className="primary-button" onClick={() => void updater.install()}>安装并重新启动</button>
          : phase === 'error' ? <button className="secondary-button" disabled={!desktop || state.retryAt > Date.now()} onClick={() => void updater.retry()}>{state.retryAction === 'install' ? '重试安装' : state.retryAction === 'download' ? '重新下载' : '重新检查'}</button>
            : phase === 'available' && release?.installable ? <button className="primary-button" onClick={() => void updater.download()}><ArrowDownToLine size={14} />下载更新</button>
              : <button className="secondary-button" disabled={!desktop || busy} onClick={() => void updater.check()}>{phase === 'checking' ? '正在检查…' : phase === 'downloading' ? '正在下载…' : phase === 'installing' ? '正在安装…' : '检查更新'}</button>}
        {!busy && phase !== 'ready' && (phase === 'error' || (phase === 'available' && release?.installable)) && <button className="update-text-button" onClick={() => void updater.check()}>重新检查版本</button>}
        <span className="update-channel">{state.includePrerelease ? '含预览版' : '正式版频道'}</span>
      </div>
      {phase === 'downloading' && !state.automatic && <p className="update-footnote">自动更新已关闭，本次已开始的下载会继续完成。</p>}
      {phase === 'ready' && <p className="update-footnote">安装会关闭并重新打开纸笺，请先结束正在编辑的内容。</p>}
    </div>
    {release && <details className="update-release-notes" key={release.version} open={release.available || undefined}>
      <summary>发布说明 <span>v{release.version}{release.prerelease ? ' · 预览版' : ''}</span></summary>
      {release.publishedAt && <div className="release-date">发布于 {new Date(release.publishedAt).toLocaleDateString('zh-CN')}</div>}
      <pre>{release.notes || '此版本未附带发布说明。'}</pre>
    </details>}
    <div className="update-security-note"><ShieldCheck size={13} /><span>下载后验证签名 · 不会自动重启</span></div>
  </section>
}
