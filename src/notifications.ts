export const inTauri = () => '__TAURI_INTERNALS__' in window

export async function sendReminderNotification(title: string, body: string) {
  if (inTauri()) {
    const notification = await import('@tauri-apps/plugin-notification')
    let permission = await notification.isPermissionGranted()
    if (!permission) permission = (await notification.requestPermission()) === 'granted'
    if (permission) notification.sendNotification({ title, body })
    return
  }

  if ('Notification' in window && Notification.permission === 'granted') {
    new Notification(title, { body })
  }
}

export function reminderOffsetMinutes(label?: string) {
  if (!label || label === '准时提醒') return 0
  if (label === '5 分钟前') return 5
  if (label === '15 分钟前') return 15
  if (label === '30 分钟前') return 30
  if (label === '1 小时前') return 60
  if (label === '1 天前') return 24 * 60
  return 0
}
