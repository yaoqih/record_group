function formatDuration(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0))
  const hh = Math.floor(total / 3600)
  const mm = Math.floor((total % 3600) / 60)
  const ss = total % 60
  if (hh > 0) {
    return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}`
  }
  return `${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}`
}

function formatMilliseconds(ms) {
  return formatDuration(Number(ms || 0) / 1000)
}

function formatDateTime(value) {
  if (!value) return '未记录'
  const normalized = typeof value === 'string' && value.includes(' ') ? value.replace(' ', 'T') : value
  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) return String(value)
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hour = String(date.getHours()).padStart(2, '0')
  const minute = String(date.getMinutes()).padStart(2, '0')
  return `${year}-${month}-${day} ${hour}:${minute}`
}

function formatPoints(value) {
  return `${Math.max(0, Math.floor(Number(value) || 0))} 点`
}

function statusLabel(status) {
  const map = {
    uploaded: '待确认',
    starting: '启动中',
    queued: '排队中',
    transcribing: '转写中',
    completed: '已完成',
    confirmed: '已确认',
    failed: '失败',
    expired: '已过期'
  }
  return map[status] || status || '未知'
}

function statusTheme(status) {
  const map = {
    uploaded: 'warning',
    starting: 'primary',
    queued: 'primary',
    transcribing: 'primary',
    completed: 'success',
    confirmed: 'success',
    failed: 'danger',
    expired: 'default'
  }
  return map[status] || 'default'
}

function taskText(task) {
  if (!task) return ''
  if (task.status === 'failed') return task.error || '任务失败'
  return `${formatDuration(task.duration_seconds)} · ${formatPoints(task.points_cost)}`
}

function taskDisplayTitle(task) {
  if (!task) return '未命名任务'
  return task.source_name || task.title || task.id || '未命名任务'
}

function taskMeta(task) {
  if (!task) return []
  const items = []
  items.push({ label: '时长', value: formatDuration(task.duration_seconds) })
  items.push({ label: '费用', value: formatPoints(task.points_cost) })
  if (task.created_at) items.push({ label: '创建', value: formatDateTime(task.created_at) })
  return items
}

module.exports = {
  formatDateTime,
  formatDuration,
  formatMilliseconds,
  formatPoints,
  statusLabel,
  statusTheme,
  taskMeta,
  taskDisplayTitle,
  taskText
}
