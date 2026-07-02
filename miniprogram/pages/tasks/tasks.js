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

Page({
  data: {
    loading: false,
    tasks: [],
    taskCount: 0,
    headerSubtitle: '登录后查看上传和转写状态',
    isEmpty: true,
    hasSession: false,
    error: ''
  },

  onShow() {
    this.loadTasks()
  },

  async loadTasks() {
    if (!api.getToken()) {
      this.setData({
        tasks: [],
        taskCount: 0,
        headerSubtitle: '登录后查看上传和转写状态',
        isEmpty: true,
        hasSession: false,
        error: ''
      })
      return
    }
    if (this.data.loading) return
    this.setData({ loading: true, hasSession: true, error: '' })
    try {
      const data = await api.request('/site/me/tasks')
      const tasks = (data.tasks || []).map(decorateTask)
      this.setData({
        tasks,
        taskCount: tasks.length,
        headerSubtitle: `${tasks.length} 个任务`,
        isEmpty: tasks.length === 0,
        hasSession: true
      })
    } catch (error) {
      if (isAuthError(error)) {
        api.clearSession()
        getApp().globalData.user = null
        this.setData({
          tasks: [],
          taskCount: 0,
          headerSubtitle: '登录后查看上传和转写状态',
          isEmpty: true,
          hasSession: false,
          error: ''
        })
      } else {
        this.setData({ error: error.message, hasSession: true })
      }
    } finally {
      this.setData({ loading: false })
    }
  },

  openTask(event) {
    const id = eventDataset(event).id
    if (id) wx.navigateTo({ url: `/pages/task/task?id=${id}` })
  },

  goLogin() {
    wx.switchTab({ url: '/pages/index/index' })
  }
})

function decorateTask(task) {
  return {
    ...task,
    displayTitle: taskDisplayTitle(task),
    statusLabel: statusLabel(task.status),
    statusTheme: statusTheme(task.status),
    summary: taskText(task),
    durationText: formatDuration(task.duration_seconds),
    pointsText: formatPoints(task.points_cost),
    createdText: formatDateTime(task.created_at)
  }
}

function isAuthError(error) {
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
