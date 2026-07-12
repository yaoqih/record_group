const api = require('../../utils/api')
const {
  formatDateTime,
  formatDuration,
  formatPoints,
  statusLabel,
  statusTheme,
  taskDisplayTitle,
  taskText
} = require('../../utils/format')

const REQUEST_TIMEOUT_MS = 10000
const PAGE_CACHE_MS = 2000
const POLL_DELAYS_MS = [5000, 10000, 20000, 30000]

Page({
  data: {
    loading: false,
    hasLoaded: false,
    tasks: [],
    filteredTasks: [],
    filters: [],
    activeFilter: 'all',
    taskCount: 0,
    processingCount: 0,
    completedCount: 0,
    headerSubtitle: '登录后查看上传和转写状态',
    isEmpty: true,
    hasSession: false,
    error: ''
  },

  onShow() {
    this.pageVisible = true
    this.loadTasks({ silent: this.data.hasLoaded, cacheMs: PAGE_CACHE_MS })
  },

  onHide() {
    this.pageVisible = false
    this.stopPolling()
  },

  onUnload() {
    this.pageVisible = false
    this.stopPolling()
  },

  async onPullDownRefresh() {
    await this.loadTasks({ silent: true, forceRefresh: true })
    wx.stopPullDownRefresh()
  },

  async loadTasks(options = {}) {
    const silent = options.silent === true
    if (!api.getToken()) {
      this.setData({
        tasks: [],
        filteredTasks: [],
        taskCount: 0,
        headerSubtitle: '登录后查看上传和转写状态',
        isEmpty: true,
        hasSession: false,
        hasLoaded: true,
        error: ''
      })
      this.stopPolling()
      return
    }
    if (this.tasksLoading) {
      this.startPollingIfNeeded(this.data.tasks)
      return
    }
    this.tasksLoading = true
    if (!silent) this.setData({ loading: true, hasSession: true, error: '' })
    try {
      const data = await api.request('/site/me/tasks', {
        cacheMs: options.forceRefresh ? 0 : Number(options.cacheMs || 0),
        forceRefresh: options.forceRefresh === true,
        timeout: REQUEST_TIMEOUT_MS
      })
      const tasks = (data.tasks || []).map(decorateTask)
      const nextSignature = taskListSignature(tasks)
      const tasksChanged = nextSignature !== this.tasksViewSignature
      if (tasksChanged || !this.data.hasLoaded || !this.data.hasSession) {
        const processingCount = tasks.filter((task) => task.statusGroup === 'processing').length
        const completedCount = tasks.filter((task) => task.statusGroup === 'completed').length
        this.tasksViewSignature = nextSignature
        this.setData({
          tasks,
          filteredTasks: filterTasks(tasks, this.data.activeFilter),
          filters: buildFilters(tasks),
          taskCount: tasks.length,
          processingCount,
          completedCount,
          headerSubtitle: `${tasks.length} 个任务`,
          isEmpty: tasks.length === 0,
          hasSession: true,
          hasLoaded: true,
          error: ''
        })
      } else if (this.data.error) {
        this.setData({ error: '' })
      }
      this.statusesSignature = statusListSignature(tasks)
      this.startPollingIfNeeded(tasks, { reset: tasksChanged || options.resetPolling === true })
    } catch (error) {
      if (isAuthError(error)) {
        api.clearSession()
        getApp().globalData.user = null
        this.setData({
          tasks: [],
          filteredTasks: [],
          taskCount: 0,
          headerSubtitle: '登录后查看上传和转写状态',
          isEmpty: true,
          hasSession: false,
          hasLoaded: true,
          error: ''
        })
        this.stopPolling()
      } else {
        this.setData({ error: error.message, hasSession: true, hasLoaded: true })
        this.startPollingIfNeeded(this.data.tasks)
      }
    } finally {
      this.tasksLoading = false
      if (!silent) this.setData({ loading: false })
    }
  },

  openTask(event) {
    const id = eventDataset(event).id
    if (id) wx.navigateTo({ url: `/pages/task/task?id=${id}` })
  },

  changeFilter(event) {
    const activeFilter = eventDataset(event).filter || 'all'
    this.setData({ activeFilter, filteredTasks: filterTasks(this.data.tasks, activeFilter) })
  },

  goLogin() {
    wx.switchTab({ url: '/pages/index/index' })
  },

  startPollingIfNeeded(tasks, options = {}) {
    const hasProcessing = tasks.some((task) => task.statusGroup === 'processing')
    if (!hasProcessing) {
      this.stopPolling()
      return
    }
    if (!this.pageVisible) return
    if (options.reset) {
      if (this.pollTimer) clearTimeout(this.pollTimer)
      this.pollTimer = null
      this.pollAttempt = 0
    }
    if (this.pollTimer) return
    const attempt = Number(this.pollAttempt || 0)
    const delay = POLL_DELAYS_MS[Math.min(attempt, POLL_DELAYS_MS.length - 1)]
    this.pollTimer = setTimeout(() => {
      this.pollTimer = null
      this.pollAttempt = attempt + 1
      this.pollTaskStatuses()
    }, delay)
  },

  async pollTaskStatuses() {
    if (!this.pageVisible || !this.data.tasks.some((task) => task.statusGroup === 'processing')) return
    try {
      const data = await api.request('/site/me/tasks/statuses', {
        forceRefresh: true,
        timeout: REQUEST_TIMEOUT_MS
      })
      if (!this.pageVisible) return
      const nextStatusesSignature = statusListSignature(data.statuses || [])
      const nextRevision = String(data.revision === undefined ? '' : data.revision)
      const revisionChanged = this.tasksRevision && nextRevision && this.tasksRevision !== nextRevision
      const statusesChanged = nextStatusesSignature !== this.statusesSignature
      this.tasksRevision = nextRevision
      if (revisionChanged || statusesChanged) {
        await this.loadTasks({ silent: true, forceRefresh: true, resetPolling: true })
        return
      }
    } catch (error) {
      // 状态同步失败时保留现有列表，下一次按退避间隔重试。
    }
    this.startPollingIfNeeded(this.data.tasks)
  },

  stopPolling() {
    if (this.pollTimer) clearTimeout(this.pollTimer)
    this.pollTimer = null
    this.pollAttempt = 0
  }
})

function decorateTask(task) {
  const statusGroup = taskStatusGroup(task.status)
  return {
    ...task,
    displayTitle: taskDisplayTitle(task),
    statusLabel: statusLabel(task.status),
    statusTheme: statusTheme(task.status),
    summary: taskText(task),
    durationText: formatDuration(task.duration_seconds),
    pointsText: formatPoints(task.points_cost),
    createdText: formatDateTime(task.created_at),
    statusGroup,
    actionText: task.status === 'uploaded' ? '去确认' : statusGroup === 'completed' ? '查看文本' : '查看详情'
  }
}

function taskStatusGroup(status) {
  if (status === 'uploaded') return 'action'
  if (['queued', 'starting', 'transcribing'].includes(status)) return 'processing'
  if (['completed', 'confirmed'].includes(status)) return 'completed'
  if (['failed', 'expired'].includes(status)) return 'failed'
  return 'other'
}

function filterTasks(tasks, filter) {
  if (filter === 'all') return tasks
  return tasks.filter((task) => task.statusGroup === filter)
}

function buildFilters(tasks) {
  const count = (key) => tasks.filter((task) => task.statusGroup === key).length
  return [
    { key: 'all', label: '全部', count: tasks.length },
    { key: 'action', label: '待确认', count: count('action') },
    { key: 'processing', label: '进行中', count: count('processing') },
    { key: 'completed', label: '已完成', count: count('completed') },
    { key: 'failed', label: '异常', count: count('failed') }
  ]
}

function statusListSignature(tasks) {
  return tasks
    .map((task) => [task.id, task.status, task.updated_at, task.error].map((value) => String(value || '')).join('|'))
    .sort()
    .join('::')
}

function taskListSignature(tasks) {
  return tasks
    .map((task) =>
      [
        task.id,
        task.status,
        task.updated_at,
        task.error,
        task.title,
        task.source_name,
        task.duration_seconds,
        task.points_cost
      ]
        .map((value) => String(value || ''))
        .join('|')
    )
    .join('::')
}

function isAuthError(error) {
  if (error && (error.statusCode === 401 || error.statusCode === 403)) return true
  const message = error && error.message ? error.message : ''
  return message.includes('401') || message.toLowerCase().includes('unauthorized')
}

function eventDataset(event) {
  return (
    (event.currentTarget && event.currentTarget.dataset) ||
    (event.detail && event.detail.currentTarget && event.detail.currentTarget.dataset) ||
    {}
  )
}
