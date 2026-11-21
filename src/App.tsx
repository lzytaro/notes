import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Archive,
  Bell,
  CalendarDays,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Circle,
  Clock3,
  Inbox,
  Keyboard,
  LayoutGrid,
  ListFilter,
  MoreHorizontal,
  Moon,
  Plus,
  Rocket,
  BellRing,
  Search,
  Settings,
  Sparkles,
  Sun,
  Tag,
  Trash2,
  Undo2,
  X,
} from 'lucide-react'
import type { Task, TaskDraft, ViewId } from './types'
import { inTauri, reminderOffsetMinutes, sendReminderNotification } from './notifications'
import { loadTasks, saveTaskChanges } from './storage'
import { getCurrentUser, onAuthChange, sendMagicLink, signInWithGoogle, signOutUser, supabaseConfigured } from './supabase'
import { syncTasks } from './sync'
import { nextOccurrence } from './recurrence'
import { announceTasksChanged, openDesktopWidget } from './desktop'
import { useUpdater } from './updater'
import { UpdateSettings } from './UpdateSettings'
import type { UpdateSnapshot } from './updateController'

const now = new Date()
const localISO = (date: Date) => {
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

const addHours = (hours: number) => {
  const date = new Date(now)
  date.setHours(date.getHours() + hours)
  return localISO(date)
}

const initialTasks: Task[] = [
  {
    id: 'task-1',
    title: '给客户发报价单',
    notes: '确认第二版价格和交付时间后发出。',
    status: 'open',
    dueAt: addHours(1),
    reminder: '15 分钟前',
    recurrence: 'none',
    tags: ['工作'],
    createdAt: new Date(now.getTime() - 1000 * 60 * 60 * 2).toISOString(),
    updatedAt: new Date(now.getTime() - 1000 * 60 * 50).toISOString(),
  },
  {
    id: 'task-2',
    title: '买咖啡豆',
    notes: '',
    status: 'open',
    dueAt: addHours(15),
    reminder: '准时提醒',
    recurrence: 'none',
    tags: ['生活'],
    createdAt: new Date(now.getTime() - 1000 * 60 * 60 * 6).toISOString(),
    updatedAt: new Date(now.getTime() - 1000 * 60 * 60 * 6).toISOString(),
  },
  {
    id: 'task-3',
    title: '整理项目周报',
    notes: '补上本周数据和下周风险。',
    status: 'open',
    dueAt: addHours(-3),
    reminder: '1 小时前',
    recurrence: 'none',
    tags: ['工作', '写作'],
    createdAt: new Date(now.getTime() - 1000 * 60 * 60 * 24).toISOString(),
    updatedAt: new Date(now.getTime() - 1000 * 60 * 30).toISOString(),
  },
  {
    id: 'task-4',
    title: '每周复盘本周目标',
    notes: '保留做得好的部分，写下一个下周重点。',
    status: 'open',
    dueAt: addHours(42),
    reminder: '30 分钟前',
    recurrence: 'weekly',
    tags: ['个人'],
    createdAt: new Date(now.getTime() - 1000 * 60 * 60 * 12).toISOString(),
    updatedAt: new Date(now.getTime() - 1000 * 60 * 60 * 12).toISOString(),
  },
  {
    id: 'task-5',
    title: '预约牙医',
    notes: '',
    status: 'completed',
    dueAt: addHours(-24),
    reminder: '准时提醒',
    recurrence: 'none',
    tags: ['生活'],
    createdAt: new Date(now.getTime() - 1000 * 60 * 60 * 48).toISOString(),
    updatedAt: new Date(now.getTime() - 1000 * 60 * 60 * 24).toISOString(),
  },
]

const navItems: { id: ViewId; label: string; icon: typeof Inbox }[] = [
  { id: 'inbox', label: '收件箱', icon: Inbox },
  { id: 'today', label: '今天', icon: CalendarDays },
  { id: 'upcoming', label: '即将到期', icon: Clock3 },
  { id: 'completed', label: '已完成', icon: CheckCircle2 },
]

const formatDue = (dueAt?: string) => {
  if (!dueAt) return '无日期'
  const date = new Date(dueAt)
  const sameDay = date.toDateString() === now.toDateString()
  if (sameDay) return `今天 ${date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`
  const tomorrow = new Date(now)
  tomorrow.setDate(now.getDate() + 1)
  if (date.toDateString() === tomorrow.toDateString()) return `明天 ${date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`
  return date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}

const isOverdue = (dueAt?: string, status?: Task['status']) => Boolean(dueAt && new Date(dueAt) < new Date() && status === 'open')

const startOfTomorrow = () => {
  const tomorrow = new Date(now)
  tomorrow.setDate(tomorrow.getDate() + 1)
  tomorrow.setHours(0, 0, 0, 0)
  return tomorrow
}

const viewTitle: Record<ViewId, string> = {
  inbox: '收件箱',
  today: '今天',
  upcoming: '即将到期',
  completed: '已完成',
}

function App() {
  const updateState = useUpdater()
  const [tasks, setTasks] = useState<Task[]>(() => {
    const saved = localStorage.getItem('notes-tasks-v1')
    return saved ? (JSON.parse(saved) as Task[]) : initialTasks
  })
  const [storageReady, setStorageReady] = useState(false)
  const [activeView, setActiveView] = useState<ViewId>('inbox')
  const [activeTag, setActiveTag] = useState<string | null>(null)
  const [filterMode, setFilterMode] = useState<'all' | 'reminder' | 'overdue'>('all')
  const [showFilterMenu, setShowFilterMenu] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [selectedId, setSelectedId] = useState('task-1')
  const [showQuickAdd, setShowQuickAdd] = useState(false)
  const [showDetails, setShowDetails] = useState(true)
  const [searchOpen, setSearchOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [themeMode, setThemeMode] = useState<'system' | 'light' | 'dark'>(() => (localStorage.getItem('notes-theme') as 'system' | 'light' | 'dark') || 'system')
  const [systemTheme, setSystemTheme] = useState<'light' | 'dark'>(() => window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
  const [toast, setToast] = useState<{ message: string; undo?: () => void } | null>(null)
  const [showAccount, setShowAccount] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const [showWidgets, setShowWidgets] = useState(false)
  const [accountEmail, setAccountEmail] = useState<string | null>(null)
  const [accountMessage, setAccountMessage] = useState('')
  const [accountBusy, setAccountBusy] = useState(false)
  const quickInputRef = useRef<HTMLInputElement>(null)
  const lastPersistedTasks = useRef<Task[] | null>(null)

  useEffect(() => {
    let mounted = true
    void loadTasks(initialTasks).then((loaded) => {
      if (!mounted) return
      setTasks(loaded)
      lastPersistedTasks.current = loaded
      setStorageReady(true)
    })
    return () => { mounted = false }
  }, [])

  useEffect(() => {
    if (storageReady) {
      const previous = lastPersistedTasks.current || []
      const previousById = new Map(previous.map((task) => [task.id, JSON.stringify(task)]))
      const changed = tasks.filter((task) => previousById.get(task.id) !== JSON.stringify(task))
      if (changed.length > 0) void saveTaskChanges(changed, tasks)
      lastPersistedTasks.current = tasks
      void announceTasksChanged()
    }
  }, [storageReady, tasks])

  const theme = themeMode === 'system' ? systemTheme : themeMode

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('notes-theme', themeMode)
  }, [theme, themeMode])

  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const update = (event: MediaQueryListEvent) => setSystemTheme(event.matches ? 'dark' : 'light')
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])

  useEffect(() => {
    let mounted = true
    void getCurrentUser().then((user) => {
      if (mounted) setAccountEmail(user?.email || null)
    })
    const unsubscribe = onAuthChange((_event, session) => {
      setAccountEmail(session?.user.email || null)
    })
    return () => {
      mounted = false
      unsubscribe()
    }
  }, [])

  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      const modifier = event.metaKey || event.ctrlKey
      if (modifier && event.shiftKey && event.code === 'Space') {
        event.preventDefault()
        setShowQuickAdd(true)
      }
      if (modifier && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setSearchOpen((value) => !value)
      }
      if (event.key === 'Escape') {
        setShowSettings(false)
        setShowQuickAdd(false)
        setSearchOpen(false)
      }
    }
    window.addEventListener('keydown', listener)
    return () => window.removeEventListener('keydown', listener)
  }, [])

  useEffect(() => {
    if (!inTauri()) return
    let unlisten: (() => void) | undefined
    let registered = false
    const setup = async () => {
      const [{ listen }, { register, unregister }] = await Promise.all([
        import('@tauri-apps/api/event'),
        import('@tauri-apps/plugin-global-shortcut'),
      ])
      unlisten = await listen('open-quick-add', () => setShowQuickAdd(true))
      const shortcut = 'CommandOrControl+Shift+Space'
      await register(shortcut, (event) => {
        if (event.state === 'Pressed') setShowQuickAdd(true)
      })
      registered = true
      return () => unregister(shortcut)
    }
    let unregisterShortcut: (() => Promise<void>) | undefined
    void setup().then((unregister) => { unregisterShortcut = unregister }).catch(() => {})
    return () => {
      unlisten?.()
      if (registered) void unregisterShortcut?.()
    }
  }, [])

  useEffect(() => {
    const checkReminders = () => {
      const current = Date.now()
      tasks.forEach((task) => {
        if (localStorage.getItem('notes-notifications-enabled') === 'false' || task.status !== 'open' || !task.dueAt || !task.reminder) return
        const dueTime = new Date(task.dueAt).getTime()
        const fireAt = dueTime - reminderOffsetMinutes(task.reminder) * 60 * 1000
        const reminderKey = `notes-reminder:${task.id}:${task.dueAt}:${task.reminder}`
        const catchUpWindow = 24 * 60 * 60 * 1000
        if (current >= fireAt && current < fireAt + catchUpWindow && !localStorage.getItem(reminderKey)) {
          localStorage.setItem(reminderKey, 'sent')
          const overdue = current > dueTime
          const label = overdue ? '错过提醒，回来看看' : task.reminder === '准时提醒' ? '现在' : task.reminder
          void sendReminderNotification('纸笺提醒', `${task.title} · ${label}`)
          setToast({ message: overdue ? `补发提醒：${task.title}` : `提醒：${task.title}` })
        }
      })
    }
    const timer = window.setInterval(checkReminders, 15_000)
    const onWake = () => checkReminders()
    window.addEventListener('focus', onWake)
    document.addEventListener('visibilitychange', onWake)
    checkReminders()
    return () => {
      window.clearInterval(timer)
      window.removeEventListener('focus', onWake)
      document.removeEventListener('visibilitychange', onWake)
    }
  }, [tasks])

  useEffect(() => {
    if (showQuickAdd) window.setTimeout(() => quickInputRef.current?.focus(), 20)
  }, [showQuickAdd])

  const selectedTask = tasks.find((task) => task.id === selectedId)
  const filteredTasks = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase()
    return tasks
      .filter((task) => {
        if (task.deletedAt) return false
        if (activeView === 'completed') return task.status === 'completed'
        if (task.status === 'completed') return false
        if (activeView === 'today') return Boolean(task.dueAt && new Date(task.dueAt) < startOfTomorrow())
        if (activeView === 'upcoming') return Boolean(task.dueAt && new Date(task.dueAt) >= startOfTomorrow())
        return true
      })
      .filter((task) => !activeTag || task.tags.includes(activeTag))
      .filter((task) => filterMode === 'all' ? true : filterMode === 'reminder' ? Boolean(task.reminder) : isOverdue(task.dueAt, task.status))
      .filter((task) => !normalizedQuery || `${task.title} ${task.notes} ${task.tags.join(' ')}`.toLowerCase().includes(normalizedQuery))
      .sort((a, b) => {
        if (!a.dueAt) return 1
        if (!b.dueAt) return -1
        return new Date(a.dueAt).getTime() - new Date(b.dueAt).getTime()
      })
  }, [activeTag, activeView, filterMode, query, tasks])

  const counts = useMemo(() => ({
    inbox: tasks.filter((task) => !task.deletedAt && task.status === 'open').length,
    today: tasks.filter((task) => !task.deletedAt && task.status === 'open' && task.dueAt && new Date(task.dueAt) < startOfTomorrow()).length,
    upcoming: tasks.filter((task) => !task.deletedAt && task.status === 'open' && task.dueAt && new Date(task.dueAt) >= startOfTomorrow()).length,
    completed: tasks.filter((task) => !task.deletedAt && task.status === 'completed').length,
  }), [tasks])

  const createTask = (draft: TaskDraft) => {
    const task: Task = {
      id: `task-${Date.now()}`,
      title: draft.title.trim(),
      notes: draft.notes,
      status: 'open',
      dueAt: draft.dueAt,
      reminder: draft.reminder,
      recurrence: draft.recurrence,
      tags: draft.tags,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    }
    setTasks((current) => [task, ...current])
    setSelectedId(task.id)
    setShowDetails(true)
    setShowQuickAdd(false)
    setToast({ message: '任务已添加' })
  }

  const updateTask = (id: string, patch: Partial<Task>) => {
    setTasks((current) => current.map((task) => (task.id === id ? { ...task, ...patch, updatedAt: new Date().toISOString() } : task)))
  }

  const toggleTask = (task: Task) => {
    const completing = task.status === 'open'
    const nextDueAt = completing && task.recurrence !== 'none' && task.dueAt ? nextOccurrence(task.dueAt, task.recurrence) : task.dueAt
    const nextStatus = completing && nextDueAt !== task.dueAt ? 'open' : completing ? 'completed' : 'open'
    updateTask(task.id, { status: nextStatus, dueAt: nextDueAt })
    const original = { status: task.status, dueAt: task.dueAt }
    setToast({
      message: nextDueAt !== task.dueAt ? '已完成，下一次已安排' : nextStatus === 'completed' ? '已完成' : '已恢复',
      undo: () => updateTask(task.id, original),
    })
  }

  const deleteTask = (id: string) => {
    const deleted = tasks.find((task) => task.id === id)
    const deletedAt = new Date().toISOString()
    setTasks((current) => current.map((task) => task.id === id ? { ...task, deletedAt, updatedAt: deletedAt } : task))
    if (selectedId === id) setSelectedId('')
    setToast({ message: '任务已删除', undo: deleted ? () => setTasks((current) => current.map((task) => task.id === id ? { ...deleted, updatedAt: new Date().toISOString() } : task)) : undefined })
  }

  const syncNow = async () => {
    setAccountBusy(true)
    const result = await syncTasks(tasks)
    setTasks(result.tasks)
    setAccountMessage(result.message)
    setAccountBusy(false)
  }

  return (
    <div className={`app-shell ${sidebarCollapsed ? 'is-sidebar-collapsed' : ''}`}>
      <aside className="sidebar">
        <div className="brand-row">
          <div className="brand-mark"><Sparkles size={15} strokeWidth={2.3} /></div>
          <span className="brand-name">纸笺</span>
          <button className="icon-button ghost sidebar-collapse" aria-label={sidebarCollapsed ? '展开侧栏' : '收起侧栏'} onClick={() => setSidebarCollapsed((value) => !value)}>{sidebarCollapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}</button>
        </div>

        <button className="quick-entry-button" onClick={() => setShowQuickAdd(true)}>
          <span className="quick-entry-icon"><Plus size={16} /></span>
          <span className="quick-entry-label">快速记录</span>
          <kbd>⌘ ⇧ 空格</kbd>
        </button>

        <div className="nav-group">
          <div className="nav-caption">任务</div>
          {navItems.map(({ id, label, icon: Icon }) => (
            <button key={id} className={`nav-item ${activeView === id ? 'active' : ''}`} onClick={() => setActiveView(id)}>
              <Icon size={17} strokeWidth={activeView === id ? 2.2 : 1.8} />
              <span className="nav-label">{label}</span>
              <span className="nav-count">{counts[id]}</span>
            </button>
          ))}
        </div>

        <div className="nav-group tags-group">
          <div className="nav-caption row-caption"><span>标签</span><button className="mini-button" aria-label="添加标签"><Plus size={14} /></button></div>
          <button className={`tag-nav-item ${activeTag === '工作' ? 'active' : ''}`} onClick={() => { setActiveTag('工作'); setActiveView('inbox') }}><span className="tag-dot work" /><span className="nav-label">工作</span><span className="nav-count">{tasks.filter((task) => task.tags.includes('工作')).length}</span></button>
          <button className={`tag-nav-item ${activeTag === '生活' ? 'active' : ''}`} onClick={() => { setActiveTag('生活'); setActiveView('inbox') }}><span className="tag-dot life" /><span className="nav-label">生活</span><span className="nav-count">{tasks.filter((task) => task.tags.includes('生活')).length}</span></button>
          <button className={`tag-nav-item ${activeTag === '个人' ? 'active' : ''}`} onClick={() => { setActiveTag('个人'); setActiveView('inbox') }}><span className="tag-dot personal" /><span className="nav-label">个人</span><span className="nav-count">{tasks.filter((task) => task.tags.includes('个人')).length}</span></button>
        </div>

        <button className="nav-item widget-nav" onClick={() => setShowWidgets(true)}><LayoutGrid size={17} /><span className="nav-label">桌面组件</span><span className="nav-badge">NEW</span></button>

        <div className="sidebar-bottom">
          <button className="nav-item muted-action" onClick={() => setShowSettings(true)}><Settings size={17} /><span className="nav-label">设置</span></button>
          <button className="profile-card" onClick={() => { setAccountMessage(''); setShowAccount(true) }}>
            <div className="avatar">L</div>
            <div className="profile-copy"><strong>{accountEmail || '本地访客'}</strong><span>{accountEmail ? '已连接云同步' : '数据仅保存在本机'}</span></div>
            <MoreHorizontal size={17} className="profile-more" />
          </button>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div className="breadcrumb"><span>任务</span><ChevronRight size={14} /><strong>{viewTitle[activeView]}</strong></div>
          <div className="topbar-actions">
            <button className="sync-status"><span className="online-dot" />已保存到本地</button>
            <button className="icon-button" aria-label="搜索" onClick={() => setSearchOpen((value) => !value)}><Search size={18} /></button>
            <button className="icon-button" aria-label="切换主题" onClick={() => setThemeMode((value) => value === 'system' ? 'dark' : value === 'dark' ? 'light' : 'system')} title={`主题：${themeMode === 'system' ? '跟随系统' : themeMode === 'dark' ? '深色' : '浅色'}`}>{theme === 'light' ? <Moon size={18} /> : <Sun size={18} />}</button>
            <div className="top-avatar">L</div>
          </div>
        </header>

        {searchOpen && (
          <div className="search-bar-wrap"><Search size={16} /><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索任务、备注或标签" /><kbd>⌘ K</kbd><button className="icon-button ghost" aria-label="清除搜索" onClick={() => { setQuery(''); setSearchOpen(false) }}><X size={16} /></button></div>
        )}

        <div className="content-scroll">
          <section className="content-header">
            <div>
              <div className="eyebrow">{activeView === 'today' ? '2026年11月20日 · 星期五' : activeView === 'inbox' ? '把脑中的事先放下来' : '保持节奏，轻松推进'}</div>
              <h1>{viewTitle[activeView]}</h1>
            </div>
            <div className="header-actions"><div className="filter-wrap"><button className={`filter-button ${filterMode !== 'all' ? 'active' : ''}`} onClick={() => setShowFilterMenu((value) => !value)}><ListFilter size={15} />筛选<ChevronDown size={14} /></button>{showFilterMenu && <div className="filter-menu"><button className={filterMode === 'all' ? 'selected' : ''} onClick={() => { setFilterMode('all'); setShowFilterMenu(false) }}>全部任务</button><button className={filterMode === 'reminder' ? 'selected' : ''} onClick={() => { setFilterMode('reminder'); setShowFilterMenu(false) }}>有提醒</button><button className={filterMode === 'overdue' ? 'selected' : ''} onClick={() => { setFilterMode('overdue'); setShowFilterMenu(false) }}>已逾期</button></div>}</div><button className="icon-button" aria-label="更多视图操作" onClick={() => setShowFilterMenu((value) => !value)}><MoreHorizontal size={18} /></button></div>
          </section>

          <button className="inline-add" onClick={() => setShowQuickAdd(true)}><Plus size={17} /><span>记下此刻想到的事…</span><kbd>⌘ ⇧ 空格</kbd></button>

          <div className="list-meta"><span>{filteredTasks.length} 个任务</span><span className="list-meta-divider" /><span>按日期排序</span></div>
          <section className="task-list" aria-label={`${viewTitle[activeView]}任务列表`}>
            {filteredTasks.length === 0 ? <EmptyState view={activeView} onAdd={() => setShowQuickAdd(true)} /> : filteredTasks.map((task) => (
              <TaskRow key={task.id} task={task} selected={task.id === selectedId} onSelect={() => { setSelectedId(task.id); setShowDetails(true) }} onToggle={() => toggleTask(task)} />
            ))}
          </section>

          <div className="list-footer"><Keyboard size={14} /><span>按 <kbd>⌘ K</kbd> 搜索任务，按 <kbd>Enter</kbd> 打开详情</span></div>
        </div>
      </main>

      {showDetails && selectedTask && <TaskDetails task={selectedTask} onClose={() => setShowDetails(false)} onUpdate={(patch) => updateTask(selectedTask.id, patch)} onDelete={() => deleteTask(selectedTask.id)} onToggle={() => toggleTask(selectedTask)} />}
      {showQuickAdd && <QuickAddModal inputRef={quickInputRef} onClose={() => setShowQuickAdd(false)} onCreate={createTask} />}
      {showAccount && <AccountModal email={accountEmail} configured={supabaseConfigured} message={accountMessage} busy={accountBusy} onClose={() => setShowAccount(false)} onMessage={setAccountMessage} onEmail={setAccountEmail} onSync={syncNow} />}
      {updateState.phase === 'ready' && !showSettings && <button className="update-ready-banner" onClick={() => setShowSettings(true)}><span className="update-ready-dot" />新版本已准备好<span>查看更新</span></button>}
      {showSettings && <SettingsModal updateState={updateState} onClose={() => setShowSettings(false)} />}
      {showWidgets && <WidgetStudio onClose={() => setShowWidgets(false)} onQuickAdd={() => { setShowWidgets(false); setShowQuickAdd(true) }} onOpenDesktop={(kind) => void openDesktopWidget(kind)} />}
      {toast && <Toast toast={toast} onClose={() => setToast(null)} />}
    </div>
  )
}

function TaskRow({ task, selected, onSelect, onToggle }: { task: Task; selected: boolean; onSelect: () => void; onToggle: () => void }) {
  return <article className={`task-row ${selected ? 'selected' : ''}`} onClick={onSelect}>
    <button className={`task-check ${task.status === 'completed' ? 'checked' : ''}`} aria-label={task.status === 'completed' ? '恢复任务' : '完成任务'} onClick={(event) => { event.stopPropagation(); onToggle() }}>{task.status === 'completed' ? <Check size={14} /> : <Circle size={17} />}</button>
    <div className="task-main"><div className={`task-title ${task.status === 'completed' ? 'done' : ''}`}>{task.title}</div><div className="task-subline">{task.dueAt && <span className={`due-chip ${isOverdue(task.dueAt, task.status) ? 'overdue' : ''}`}><CalendarDays size={13} />{formatDue(task.dueAt)}</span>}{task.reminder && <span className="subline-item"><Bell size={13} />{task.reminder}</span>}{task.recurrence !== 'none' && <span className="subline-item">↻ {task.recurrence === 'weekly' ? '每周' : '每天'}</span>}{task.tags.map((tag) => <span key={tag} className="task-tag">{tag}</span>)}</div></div>
    <button className="row-more icon-button ghost" aria-label="打开任务详情" onClick={(event) => { event.stopPropagation(); onSelect() }}><MoreHorizontal size={17} /></button>
  </article>
}

function TaskDetails({ task, onClose, onUpdate, onDelete, onToggle }: { task: Task; onClose: () => void; onUpdate: (patch: Partial<Task>) => void; onDelete: () => void; onToggle: () => void }) {
  const [addingTag, setAddingTag] = useState(false)
  const [newTag, setNewTag] = useState('')
  const addTag = () => {
    const tag = newTag.trim()
    if (!tag || task.tags.includes(tag)) return
    onUpdate({ tags: [...task.tags, tag] })
    setNewTag('')
    setAddingTag(false)
  }

  return <aside className="details-panel">
    <div className="details-header"><span className="details-label">任务详情</span><div className="details-actions"><button className="icon-button ghost" aria-label="完成任务" onClick={onToggle}>{task.status === 'completed' ? <Undo2 size={17} /> : <Check size={17} />}</button><button className="icon-button ghost" aria-label="关闭详情" onClick={onClose}><X size={17} /></button></div></div>
    <div className="details-content">
      <div className="detail-status"><span className={`status-dot ${task.status === 'completed' ? 'completed' : ''}`} />{task.status === 'completed' ? '已完成' : '进行中'}</div>
      <textarea className={`detail-title-input ${task.status === 'completed' ? 'done' : ''}`} value={task.title} onChange={(event) => onUpdate({ title: event.target.value })} rows={2} />
      <label className="field-label">备注<textarea className="notes-input" value={task.notes} onChange={(event) => onUpdate({ notes: event.target.value })} placeholder="补充一些上下文…" rows={4} /></label>
      <div className="detail-fields">
        <div className="detail-field"><span className="field-icon"><CalendarDays size={16} /></span><div><span className="field-label">日期</span><input type="datetime-local" value={task.dueAt || ''} onChange={(event) => onUpdate({ dueAt: event.target.value || undefined })} /></div></div>
        <div className="detail-field"><span className="field-icon"><Bell size={16} /></span><div><span className="field-label">提醒</span><select value={task.reminder || ''} onChange={(event) => onUpdate({ reminder: event.target.value || undefined })}><option value="">不提醒</option><option>准时提醒</option><option>5 分钟前</option><option>15 分钟前</option><option>30 分钟前</option><option>1 小时前</option><option>1 天前</option></select></div></div>
        <div className="detail-field"><span className="field-icon">↻</span><div><span className="field-label">重复</span><select value={task.recurrence} onChange={(event) => onUpdate({ recurrence: event.target.value as Task['recurrence'] })}><option value="none">不重复</option><option value="daily">每天</option><option value="weekly">每周</option></select></div></div>
        <div className="detail-field"><span className="field-icon"><Tag size={16} /></span><div><span className="field-label">标签</span><div className="detail-tags">{task.tags.map((tag) => <span className="task-tag" key={tag}>{tag}<button aria-label={`移除标签 ${tag}`} onClick={() => onUpdate({ tags: task.tags.filter((item) => item !== tag) })}>×</button></span>)}{addingTag ? <input className="tag-input" autoFocus value={newTag} onChange={(event) => setNewTag(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') addTag(); if (event.key === 'Escape') setAddingTag(false) }} placeholder="新标签" /> : <button className="add-tag-button" onClick={() => setAddingTag(true)}>添加标签</button>}</div></div></div>
      </div>
    </div>
    <div className="details-footer"><button className="danger-button" onClick={onDelete}><Trash2 size={15} />删除任务</button><span>最后编辑于刚刚</span></div>
  </aside>
}

function QuickAddModal({ onClose, onCreate, inputRef }: { onClose: () => void; onCreate: (draft: TaskDraft) => void; inputRef: React.RefObject<HTMLInputElement | null> }) {
  const [title, setTitle] = useState('')
  const [expanded, setExpanded] = useState(false)
  const [dueAt, setDueAt] = useState('')
  const [reminder, setReminder] = useState('')
  const [tag, setTag] = useState('')

  const submit = () => {
    if (!title.trim()) return
    onCreate({ title, notes: '', dueAt: dueAt || undefined, reminder: reminder || undefined, recurrence: 'none', tags: tag ? [tag] : [] })
  }

  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
    <div className="quick-modal" role="dialog" aria-modal="true" aria-label="快速记录">
      <div className="quick-modal-top"><div className="modal-spark"><Sparkles size={15} /></div><input ref={inputRef} value={title} onChange={(event) => setTitle(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') submit() }} placeholder="接下来要做什么？" /><button className="icon-button ghost" aria-label="关闭快速记录" onClick={onClose}><X size={17} /></button></div>
      {expanded && <div className="quick-extra"><label><CalendarDays size={15} /><input type="datetime-local" value={dueAt} onChange={(event) => setDueAt(event.target.value)} /></label><label><Bell size={15} /><select value={reminder} onChange={(event) => setReminder(event.target.value)}><option value="">添加提醒</option><option>准时提醒</option><option>15 分钟前</option><option>30 分钟前</option><option>1 小时前</option><option>1 天前</option></select></label><label><Tag size={15} /><input value={tag} onChange={(event) => setTag(event.target.value)} placeholder="添加标签" /></label></div>}
      <div className="quick-modal-footer"><button className="expand-button" onClick={() => setExpanded((value) => !value)}>{expanded ? '收起选项' : '添加日期、提醒或标签'}<ChevronDown size={15} className={expanded ? 'rotate' : ''} /></button><div className="quick-hint"><kbd>Enter</kbd> 创建 <kbd>Esc</kbd> 关闭</div></div>
    </div>
  </div>
}

function AccountModal({ email, configured, message, busy, onClose, onMessage, onEmail, onSync }: { email: string | null; configured: boolean; message: string; busy: boolean; onClose: () => void; onMessage: (message: string) => void; onEmail: (email: string | null) => void; onSync: () => Promise<void> }) {
  const [inputEmail, setInputEmail] = useState('')
  const [authBusy, setAuthBusy] = useState(false)

  const submitEmail = async () => {
    if (!inputEmail.trim()) return
    setAuthBusy(true)
    const error = await sendMagicLink(inputEmail.trim())
    onMessage(error ? error.message : '登录链接已发送，请检查邮箱。')
    setAuthBusy(false)
  }

  const submitGoogle = async () => {
    setAuthBusy(true)
    const error = await signInWithGoogle()
    onMessage(error ? error.message : '正在打开 Google 登录…')
    setAuthBusy(false)
  }

  const logout = async () => {
    setAuthBusy(true)
    const error = await signOutUser()
    if (error) onMessage(error.message)
    else onEmail(null)
    setAuthBusy(false)
  }

  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
    <div className="account-modal" role="dialog" aria-modal="true" aria-label="账号与同步">
      <div className="account-modal-header"><div><div className="eyebrow">纸笺账户</div><h2>{email ? '已连接云同步' : '让任务跟着你走'}</h2></div><button className="icon-button ghost" aria-label="关闭账号面板" onClick={onClose}><X size={17} /></button></div>
      {!configured && <div className="account-notice"><CloudOffIcon /><div><strong>云同步尚未配置</strong><span>添加 VITE_SUPABASE_URL 和 VITE_SUPABASE_ANON_KEY 后启用登录与同步。</span></div></div>}
      {email ? <div className="account-signed-in"><div className="signed-avatar">{email.slice(0, 1).toUpperCase()}</div><div><strong>{email}</strong><span>本地任务会在手动同步时合并到云端。</span></div><button className="secondary-button" disabled={busy} onClick={() => void onSync()}>{busy ? '同步中…' : '立即同步'}</button><button className="text-button" disabled={authBusy} onClick={() => void logout()}>退出登录</button></div> : <div className="account-form"><label className="field-label">邮箱地址<input className="account-input" type="email" value={inputEmail} onChange={(event) => setInputEmail(event.target.value)} placeholder="you@example.com" onKeyDown={(event) => { if (event.key === 'Enter') void submitEmail() }} /></label><button className="primary-button account-submit" disabled={authBusy || !configured} onClick={() => void submitEmail()}>{authBusy ? '处理中…' : '发送登录链接'}</button><div className="auth-divider"><span>或者</span></div><button className="google-button" disabled={authBusy || !configured} onClick={() => void submitGoogle()}><span>G</span>使用 Google 登录</button></div>}
      {message && <div className="account-message">{message}</div>}
      <div className="account-modal-footer"><span>访客模式下，任务仍保存在本机。</span><button className="icon-button ghost" aria-label="关闭账号面板" onClick={onClose}><Check size={16} /></button></div>
    </div>
  </div>
}

function WidgetStudio({ onClose, onQuickAdd, onOpenDesktop }: { onClose: () => void; onQuickAdd: () => void; onOpenDesktop: (kind: 'next' | 'today' | 'capture') => void }) {
  const saved = (() => {
    try { return JSON.parse(localStorage.getItem('notes-widget-settings-v1') || '{}') as Partial<{ widget: 'next' | 'today' | 'capture'; size: 'small' | 'medium'; material: 'glass' | 'solid' }> } catch { return {} }
  })()
  const [widget, setWidget] = useState<'next' | 'today' | 'capture'>(saved.widget || 'next')
  const [size, setSize] = useState<'small' | 'medium'>(saved.size || 'medium')
  const [material, setMaterial] = useState<'glass' | 'solid'>(saved.material || 'glass')

  useEffect(() => {
    localStorage.setItem('notes-widget-settings-v1', JSON.stringify({ widget, size, material }))
  }, [material, size, widget])

  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
    <div className="widget-studio" role="dialog" aria-modal="true" aria-label="桌面组件">
      <div className="widget-studio-header"><div><div className="eyebrow">桌面组件</div><h2>把重要的事放在桌面上</h2><p>轻量、安静、随时可用。组件会保持和任务列表同步。</p></div><button className="icon-button ghost" aria-label="关闭桌面组件" onClick={onClose}><X size={17} /></button></div>
      <div className="widget-studio-body">
        <div className="widget-preview">
          {widget === 'next' && <div className={`widget-card-preview ${size === 'small' ? 'small' : ''}`} style={material === 'solid' ? { background: 'var(--surface-strong)' } : undefined}><div className="widget-topline"><strong>下一件事</strong><Clock3 size={15} /></div><div className="widget-task-title">给客户发报价单</div><div className="widget-task-meta"><CalendarDays size={13} />今天 23:45 <span>·</span><Bell size={13} />15 分钟前</div><button className="secondary-button" style={{ marginTop: 28 }} onClick={onQuickAdd}>快速记录</button></div>}
          {widget === 'today' && <div className={`widget-card-preview ${size === 'small' ? 'small' : ''}`} style={material === 'solid' ? { background: 'var(--surface-strong)' } : undefined}><div className="widget-topline"><strong>今天</strong><CalendarDays size={15} /></div><div className="widget-progress"><div className="progress-ring" /><span>还有 2 个任务<br /><small>保持轻松的节奏</small></span></div><div className="widget-task-meta"><CheckCircle2 size={13} />完成任务后自动更新</div></div>}
          {widget === 'capture' && <div className={`widget-card-preview ${size === 'small' ? 'small' : ''}`} style={material === 'solid' ? { background: 'var(--surface-strong)' } : undefined}><div className="widget-topline"><strong>快速记录</strong><Sparkles size={15} /></div><div className="widget-capture-input" onClick={onQuickAdd}><Plus size={15} />记下此刻想到的事…</div><div className="widget-task-meta"><Keyboard size={13} />⌘ ⇧ 空格随时呼出</div></div>}
        </div>
        <div className="widget-controls">
          <div><div className="widget-control-label">组件</div><div className="widget-choice-row"><button className={`widget-choice ${widget === 'next' ? 'active' : ''}`} onClick={() => setWidget('next')}>下一件事</button><button className={`widget-choice ${widget === 'today' ? 'active' : ''}`} onClick={() => setWidget('today')}>今天</button><button className={`widget-choice ${widget === 'capture' ? 'active' : ''}`} onClick={() => setWidget('capture')}>快速记录</button></div></div>
          <div><div className="widget-control-label">尺寸</div><div className="widget-choice-row"><button className={`widget-choice ${size === 'small' ? 'active' : ''}`} onClick={() => setSize('small')}>小</button><button className={`widget-choice ${size === 'medium' ? 'active' : ''}`} onClick={() => setSize('medium')}>中</button></div></div>
          <div><div className="widget-control-label">材质</div><div className="widget-choice-row"><button className={`widget-choice ${material === 'glass' ? 'active' : ''}`} onClick={() => setMaterial('glass')}>磨砂</button><button className={`widget-choice ${material === 'solid' ? 'active' : ''}`} onClick={() => setMaterial('solid')}>实色</button></div></div>
        </div>
      </div>
      <div className="widget-studio-footer"><span>桌面版支持拖动、调整尺寸和置顶显示。</span><div className="widget-studio-footer-actions"><button className="secondary-button" onClick={() => onOpenDesktop(widget)}>打开桌面组件</button><button className="primary-button" onClick={onClose}>完成</button></div></div>
    </div>
  </div>
}

function SettingsModal({ onClose, updateState }: { onClose: () => void; updateState: UpdateSnapshot }) {
  const [autostart, setAutostart] = useState(false)
  const [notifications, setNotifications] = useState(() => localStorage.getItem('notes-notifications-enabled') !== 'false')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!inTauri()) return
    void import('@tauri-apps/plugin-autostart').then(({ isEnabled }) => isEnabled().then(setAutostart).catch(() => {})).catch(() => {})
  }, [])

  const toggleAutostart = async () => {
    if (!inTauri()) return
    setBusy(true)
    try {
      const api = await import('@tauri-apps/plugin-autostart')
      if (autostart) await api.disable()
      else await api.enable()
      setAutostart(!autostart)
    } finally {
      setBusy(false)
    }
  }

  const toggleNotifications = () => {
    const value = !notifications
    setNotifications(value)
    localStorage.setItem('notes-notifications-enabled', String(value))
  }

  return <div className="modal-backdrop settings-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
    <div className="settings-modal" role="dialog" aria-modal="true" aria-label="设置">
      <div className="account-modal-header"><div><div className="eyebrow">纸笺偏好</div><h2>设置</h2></div><button className="icon-button ghost" aria-label="关闭设置" onClick={onClose}><X size={17} /></button></div>
      <div className="settings-scroll"><div className="settings-list">
        <div className="settings-row"><span className="settings-icon"><Rocket size={17} /></span><div><strong>开机启动</strong><span>登录系统后自动在托盘运行，确保提醒不中断。</span></div><button className={`switch ${autostart ? 'on' : ''}`} aria-pressed={autostart} disabled={!inTauri() || busy} onClick={() => void toggleAutostart}><span /></button></div>
        <div className="settings-row"><span className="settings-icon"><BellRing size={17} /></span><div><strong>桌面提醒</strong><span>在任务到期或提前时间显示系统通知。</span></div><button className={`switch ${notifications ? 'on' : ''}`} aria-pressed={notifications} onClick={toggleNotifications}><span /></button></div>
        <div className="settings-row"><span className="settings-icon"><Keyboard size={17} /></span><div><strong>快速记录快捷键</strong><span>任何应用中按下即可呼出快速录入。</span></div><kbd>⌘ ⇧ 空格</kbd></div>
        <div className="settings-row"><span className="settings-icon"><Moon size={17} /></span><div><strong>主题</strong><span>当前主题跟随系统，可使用顶栏按钮切换。</span></div><span className="settings-value">跟随系统</span></div>
      </div>
      <UpdateSettings state={updateState} /></div>
      <div className="account-modal-footer"><span>{inTauri() ? '桌面设置会保存在本机。' : '浏览器预览不会修改系统启动项。'}</span><button className="icon-button ghost" aria-label="关闭设置" onClick={onClose}><Check size={16} /></button></div>
    </div>
  </div>
}

function CloudOffIcon() {
  return <span className="cloud-off-icon" aria-hidden="true">⌁</span>
}

function EmptyState({ view, onAdd }: { view: ViewId; onAdd: () => void }) {
  return <div className="empty-state"><div className="empty-icon"><Archive size={20} /></div><h3>{view === 'completed' ? '还没有完成的任务' : '这里还很清爽'}</h3><p>{view === 'completed' ? '完成的任务会出现在这里。' : '把脑中的下一件事记下来，给自己一个轻松的开始。'}</p>{view !== 'completed' && <button className="primary-button" onClick={onAdd}><Plus size={16} />添加任务</button>}</div>
}

function Toast({ toast, onClose }: { toast: { message: string; undo?: () => void }; onClose: () => void }) {
  useEffect(() => {
    const timeout = window.setTimeout(onClose, 4000)
    return () => window.clearTimeout(timeout)
  }, [onClose])
  return <div className="toast"><span className="toast-check"><Check size={13} /></span><span>{toast.message}</span>{toast.undo && <button onClick={() => { toast.undo?.(); onClose() }}><Undo2 size={14} />撤销</button>}</div>
}

export default App
