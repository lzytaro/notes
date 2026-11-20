import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { Bell, CalendarDays, Clock3, Plus, Sparkles, X } from 'lucide-react'
import type { Task } from './types'
import { loadTasks } from './storage'
import { listenTasksChanged, openQuickAddFromWidget, showMainWindow } from './desktop'
import { inTauri } from './notifications'
import './widget.css'

type WidgetKind = 'next' | 'today' | 'capture'

export default function WidgetApp({ kind }: { kind: WidgetKind }) {
  const [tasks, setTasks] = useState<Task[]>([])
  const material = (() => {
    try { return (JSON.parse(localStorage.getItem('notes-widget-settings-v1') || '{}') as { material?: 'glass' | 'solid' }).material || 'glass' } catch { return 'glass' }
  })()

  const refresh = () => { void loadTasks([]).then(setTasks) }
  useEffect(() => {
    refresh()
    let cleanup: (() => void) | undefined
    void listenTasksChanged(() => refresh()).then((unlisten) => { cleanup = unlisten })
    return () => cleanup?.()
  }, [])

  useEffect(() => {
    if (!inTauri()) return
    let active = true
    let cleanupMove: (() => void) | undefined
    let cleanupResize: (() => void) | undefined
    const settingsKey = `notes-widget-window:${kind}`
    const setupWindowState = async () => {
      const [{ getCurrentWindow }, { LogicalPosition, LogicalSize }] = await Promise.all([
        import('@tauri-apps/api/window'),
        import('@tauri-apps/api/dpi'),
      ])
      const window = getCurrentWindow()
      try {
        const saved = JSON.parse(localStorage.getItem(settingsKey) || '{}') as { x?: number; y?: number; width?: number; height?: number }
        const widgetSettings = JSON.parse(localStorage.getItem('notes-widget-settings-v1') || '{}') as { size?: 'small' | 'medium' }
        const width = saved.width || (widgetSettings.size === 'small' ? 300 : 340)
        const height = saved.height || (widgetSettings.size === 'small' ? 190 : 250)
        await window.setSize(new LogicalSize(width, height))
        if (typeof saved.x === 'number' && typeof saved.y === 'number') await window.setPosition(new LogicalPosition(saved.x, saved.y))
      } catch { /* use default window geometry */ }
      cleanupMove = await window.onMoved(({ payload }) => {
        const current = JSON.parse(localStorage.getItem(settingsKey) || '{}')
        localStorage.setItem(settingsKey, JSON.stringify({ ...current, x: payload.x, y: payload.y }))
      })
      cleanupResize = await window.onResized(({ payload }) => {
        const current = JSON.parse(localStorage.getItem(settingsKey) || '{}')
        localStorage.setItem(settingsKey, JSON.stringify({ ...current, width: payload.width, height: payload.height }))
      })
    }
    void setupWindowState().catch(() => {})
    return () => {
      if (active) {
        cleanupMove?.()
        cleanupResize?.()
      }
      active = false
    }
  }, [kind])

  const openTasks = tasks.filter((task) => task.status === 'open' && !task.deletedAt)
  const nextTask = useMemo(() => openTasks.filter((task) => task.dueAt).sort((a, b) => new Date(a.dueAt || 0).getTime() - new Date(b.dueAt || 0).getTime())[0] || openTasks[0], [openTasks])
  const todayTasks = openTasks.filter((task) => task.dueAt && new Date(task.dueAt).toDateString() === new Date().toDateString())
  const completedToday = tasks.filter((task) => task.status === 'completed' && !task.deletedAt).length

  const close = async () => {
    if (inTauri()) {
      const { getCurrentWindow } = await import('@tauri-apps/api/window')
      await getCurrentWindow().hide()
    } else {
      window.close()
    }
  }

  return <main className={`widget-window ${material === 'solid' ? 'widget-solid' : ''}`}>
    <div className="widget-window-topbar"><span className="widget-window-brand"><span className="widget-window-dot"><Sparkles size={11} /></span>纸笺</span><button className="widget-close" aria-label="关闭组件" onClick={() => void close()}><X size={14} /></button></div>
    {kind === 'next' && <section className="widget-window-content"><div className="widget-window-kicker"><span>下一件事</span><Clock3 size={14} /></div><h1>{nextTask?.title || '今天很清爽'}</h1>{nextTask ? <div className="widget-window-meta"><CalendarDays size={13} />{nextTask.dueAt ? new Date(nextTask.dueAt).toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '无日期'}{nextTask.reminder && <><span>·</span><Bell size={13} />{nextTask.reminder}</>}</div> : <p>把下一件事放进来。</p>}<button className="widget-window-action" onClick={() => void showMainWindow()}>打开任务</button></section>}
    {kind === 'today' && <section className="widget-window-content"><div className="widget-window-kicker"><span>今天</span><CalendarDays size={14} /></div><div className="widget-window-progress"><div className="widget-window-ring" style={{ '--progress': `${Math.min(100, Math.round((completedToday / Math.max(1, completedToday + todayTasks.length)) * 100))}%` } as CSSProperties}><span>{completedToday}/{completedToday + todayTasks.length}</span></div><div><h1>{todayTasks.length} 个待办</h1><p>保持轻松的节奏</p></div></div><button className="widget-window-action" onClick={() => void showMainWindow()}>查看今天</button></section>}
    {kind === 'capture' && <section className="widget-window-content capture-widget"><div className="widget-window-kicker"><span>快速记录</span><Sparkles size={14} /></div><button className="widget-capture-button" onClick={() => void openQuickAddFromWidget()}><Plus size={16} />记下此刻想到的事…</button><p>快捷键 ⌘ ⇧ 空格</p></section>}
  </main>
}
