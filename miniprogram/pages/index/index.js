const api = require('../../utils/api')
const agreement = require('../../utils/agreement')
const uploadUtils = require('../../utils/upload')
const { statusLabel, statusTheme, taskDisplayTitle, taskText } = require('../../utils/format')

const REQUEST_TIMEOUT_MS = 10000
const PAGE_CACHE_MS = 2000
const POLL_DELAYS_MS = [5000, 10000, 20000, 30000]

Page({
  data: {
    user: null,
    nickname: '',
    loading: false,
    uploading: false,
    agreementAccepted: agreement.hasAcceptedCurrentAgreement(),
    uploadQueue: [],
    uploadCompleted: 0,
    uploadFailed: 0,
    uploadSummary: '',
    retryableFailedCount: 0,
    latestTask: null,
    error: ''
  },

  onShow() {
    this.pageVisible = true
    const agreementAccepted = agreement.hasAcceptedCurrentAgreement()
    if (agreementAccepted !== this.data.agreementAccepted) this.setData({ agreementAccepted })
    const cachedUser = api.getCachedUser()
    if (cachedUser && !this.data.user) this.setData({ user: cachedUser })
    this.loadMe({ cacheMs: PAGE_CACHE_MS })
  },

  async onPullDownRefresh() {
    await this.loadMe({ forceRefresh: true })
    wx.stopPullDownRefresh()
  },

  onHide() {
    this.pageVisible = false
    this.stopLatestTaskPolling()
  },

  onUnload() {
    this.pageVisible = false
    this.stopLatestTaskPolling()
  },

  onNicknameInput(event) {
    this.setData({ nickname: inputValue(event) })
  },

  onAgreementChange(event) {
    const checked = Boolean(event && event.detail && event.detail.checked)
    if (checked) {
      agreement.acceptCurrentAgreement()
    } else {
      agreement.clearCurrentAgreementAcceptance()
    }
    this.setData({ agreementAccepted: checked, error: '' })
  },

  toggleAgreementAcceptance() {
    const checked = !this.data.agreementAccepted
    if (checked) {
      agreement.acceptCurrentAgreement()
    } else {
      agreement.clearCurrentAgreementAcceptance()
    }
    this.setData({ agreementAccepted: checked, error: '' })
  },

  openAgreement() {
    wx.navigateTo({ url: '/pages/agreement/agreement' })
  },

  async onLogin() {
    if (this.data.loading || this.data.uploading) return
    if (!agreement.hasAcceptedCurrentAgreement()) {
      this.setData({ agreementAccepted: false, error: '请先阅读并同意用户协议与隐私说明' })
      return
    }
    this.setData({ loading: true, error: '' })
    try {
      const data = await api.loginWithWechat(this.data.nickname)
      this.resetUploadState({ user: data.user, latestTask: null, error: '' })
      getApp().globalData.user = data.user
    } catch (error) {
      this.setData({ error: error.message })
    } finally {
      this.setData({ loading: false })
    }
  },

  async loadMe(options = {}) {
    if (!api.getToken()) {
      this.resetUploadState({ user: null, latestTask: null })
      getApp().globalData.user = null
      this.stopLatestTaskPolling()
      return
    }
    try {
      const data = await api.request('/site/me', {
        cacheMs: options.forceRefresh ? 0 : Number(options.cacheMs || 0),
        forceRefresh: options.forceRefresh === true,
        timeout: REQUEST_TIMEOUT_MS
      })
      if (userSignature(data.user) !== userSignature(this.data.user)) this.setData({ user: data.user })
      if (this.data.error) this.setData({ error: '' })
      getApp().globalData.user = data.user
      await this.refreshLatestTask({ silent: true, forceRefresh: options.forceRefresh === true })
    } catch (error) {
      if (isAuthError(error)) {
        api.clearSession()
        this.resetUploadState({ user: null, latestTask: null })
        getApp().globalData.user = null
        this.stopLatestTaskPolling()
      } else {
        this.setData({ error: error.message })
      }
    }
  },

  async refreshLatestTask(options = {}) {
    if (!api.getToken()) return
    if (this.latestTaskLoading) {
      this.startLatestTaskPollingIfNeeded(this.data.latestTask)
      return
    }
    this.latestTaskLoading = true
    try {
      const data = await api.request('/site/me/tasks', {
        cacheMs: options.forceRefresh ? 0 : PAGE_CACHE_MS,
        forceRefresh: options.forceRefresh === true,
        timeout: REQUEST_TIMEOUT_MS
      })
      const tasks = data.tasks || []
      const currentId = this.data.latestTask && this.data.latestTask.id
      const latest = (currentId && tasks.find((task) => task.id === currentId)) || tasks[0] || null
      const latestTask = latest ? decorateTask(latest) : null
      const nextSignature = taskViewSignature(latestTask)
      const previousStatus = this.data.latestTask && this.data.latestTask.status
      const statusChanged = previousStatus !== (latestTask && latestTask.status)
      if (this.latestTaskViewSignature !== nextSignature) {
        this.latestTaskViewSignature = nextSignature
        this.setData({ latestTask })
      }
      this.latestTaskStatusSignature = taskStatusSignature(latestTask)
      this.startLatestTaskPollingIfNeeded(latestTask, { reset: statusChanged })
    } catch (error) {
      if (!options.silent) this.setData({ error: error.message })
      this.startLatestTaskPollingIfNeeded(this.data.latestTask)
    } finally {
      this.latestTaskLoading = false
    }
  },

  chooseMessageFile() {
    if (!this.data.user) {
      showToast(this, 'warning', '请先登录再上传')
      return
    }
    if (!this.ensureAgreementAccepted()) return
    if (this.data.uploading) return
    wx.chooseMessageFile({
      count: uploadUtils.MAX_UPLOAD_FILES,
      type: 'file',
      extension: uploadUtils.AUDIO_PICKER_EXTENSIONS,
      success: (res) => {
        this.startUploadSelection(res.tempFiles || [])
      },
      fail: (error) => this.handleChooseFailure(error)
    })
  },

  async startUploadSelection(tempFiles) {
    if (this.data.uploading) return
    if (!api.getToken()) {
      this.setData({ error: '请先登录' })
      return
    }
    if (!this.ensureAgreementAccepted()) return
    const selection = uploadUtils.buildUploadSelection(tempFiles)
    if (!selection.queue.length) {
      this.setData({ error: '没有选择可上传的文件' })
      return
    }
    const initialSummary = selection.invalidCount
      ? `已选择 ${selection.queue.length} 个，${selection.invalidCount} 个不可上传`
      : `已选择 ${selection.queue.length} 个文件`
    this.failedUploadFiles = []
    this.setData({
      uploading: selection.uploadable.length > 0,
      uploadQueue: selection.queue,
      uploadCompleted: 0,
      uploadFailed: selection.invalidCount,
      uploadSummary: initialSummary,
      retryableFailedCount: 0,
      error: ''
    })
    if (!selection.uploadable.length) {
      showToast(this, 'warning', '所选文件不符合上传要求')
      return
    }
    await this.uploadFilesSequentially(selection.uploadable, selection.queue.length, selection.invalidCount)
  },

  async uploadFilesSequentially(files, selectedCount, initialFailed = 0) {
    let completed = 0
    let failed = initialFailed
    let latestTask = null
    const failedFiles = []
    let authenticationLost = false

    for (let fileIndex = 0; fileIndex < files.length; fileIndex += 1) {
      const file = files[fileIndex]
      const position = fileIndex + 1
      this.updateUploadQueueItem(file.queueIndex, {
        status: 'uploading',
        statusLabel: '准备中',
        progress: 0,
        progressLabel: '0%',
        progressStatus: '',
        error: ''
      })
      this.setData({
        uploadSummary: `正在上传 ${position}/${files.length} · 已完成 ${completed}`
      })
      let lastProgress = -1
      let lastPhaseRank = -1
      try {
        const data = await api.uploadTask(file.filePath, file.name, file.sizeBytes, {
          onProgress: (detail) => {
            const progress = uploadUtils.normalizeUploadProgress(detail && detail.progress)
            const phase = (detail && detail.phase) || 'uploading'
            const phaseRank = uploadPhaseRank(phase)
            if (phaseRank < lastPhaseRank || progress < lastProgress) return
            if (phaseRank === lastPhaseRank && progress < 100 && progress - lastProgress < 2) return
            lastProgress = progress
            lastPhaseRank = phaseRank
            this.updateUploadQueueItem(file.queueIndex, {
              statusLabel: uploadPhaseLabel(phase),
              progress,
              progressLabel: phase === 'finalizing' ? '处理中' : `${progress}%`
            })
          }
        })
        const task = decorateTask(data.task)
        latestTask = task
        completed += 1
        this.updateUploadQueueItem(file.queueIndex, {
          status: 'uploaded',
          statusLabel: '已上传',
          progress: 100,
          progressLabel: '',
          progressStatus: 'success',
          taskId: task.id || ''
        })
      } catch (error) {
        const message = (error && error.message) || '上传失败'
        failed += 1
        this.updateUploadQueueItem(file.queueIndex, {
          status: 'failed',
          statusLabel: '上传失败',
          progressStatus: 'error',
          error: message
        })
        if (isAuthError(error)) {
          authenticationLost = true
          api.clearSession()
          getApp().globalData.user = null
          break
        }
        failedFiles.push(file)
      }
      this.setData({ uploadCompleted: completed, uploadFailed: failed })
    }

    if (authenticationLost) {
      this.resetUploadState({
        user: null,
        latestTask: null,
        error: '登录已失效，请重新登录后选择文件'
      })
      showToast(this, 'warning', '登录已失效，请重新登录')
      return
    }

    this.failedUploadFiles = failedFiles
    const summary = failed
      ? `${completed} 个上传成功，${failed} 个未完成`
      : `${completed} 个文件上传成功`
    const nextData = {
      uploading: false,
      uploadCompleted: completed,
      uploadFailed: failed,
      uploadSummary: summary,
      retryableFailedCount: failedFiles.length
    }
    if (latestTask) {
      this.latestTaskViewSignature = taskViewSignature(latestTask)
      this.latestTaskStatusSignature = taskStatusSignature(latestTask)
      nextData.latestTask = latestTask
    }
    this.setData(nextData)

    if (completed) {
      showToast(this, failed ? 'warning' : 'success', summary)
    } else {
      showToast(this, 'error', summary)
    }
    if (selectedCount === 1 && completed === 1 && latestTask && latestTask.id) {
      wx.navigateTo({
        url: `/pages/task/task?id=${encodeURIComponent(latestTask.id)}`,
        fail: () => {
          this.setData({ error: '上传成功，但打开任务详情失败' })
          this.startLatestTaskPollingIfNeeded(latestTask, { reset: true })
        }
      })
    }
  },

  async retryFailedUploads() {
    if (this.data.uploading || !this.failedUploadFiles || !this.failedUploadFiles.length) return
    const files = this.failedUploadFiles.map((file, index) => ({ ...file, queueIndex: index }))
    const queue = files.map((file, index) => ({
      id: `retry-${Date.now()}-${index}`,
      name: file.name,
      sizeLabel: uploadUtils.formatFileSize(file.sizeBytes),
      status: 'queued',
      statusLabel: '等待上传',
      progress: 0,
      progressLabel: '等待',
      progressStatus: '',
      error: ''
    }))
    this.failedUploadFiles = []
    this.setData({
      uploading: true,
      uploadQueue: queue,
      uploadCompleted: 0,
      uploadFailed: 0,
      uploadSummary: `准备重试 ${files.length} 个文件`,
      retryableFailedCount: 0,
      error: ''
    })
    await this.uploadFilesSequentially(files, files.length)
  },

  updateUploadQueueItem(index, changes) {
    const update = {}
    Object.keys(changes).forEach((key) => {
      update[`uploadQueue[${index}].${key}`] = changes[key]
    })
    this.setData(update)
  },

  resetUploadState(extraData = {}) {
    this.failedUploadFiles = []
    this.setData({
      uploading: false,
      uploadQueue: [],
      uploadCompleted: 0,
      uploadFailed: 0,
      uploadSummary: '',
      retryableFailedCount: 0,
      ...extraData
    })
  },

  stopTap() {
    // Prevent queue actions from reopening the file picker.
  },

  openLatestTask() {
    if (!this.data.latestTask) return
    wx.navigateTo({ url: `/pages/task/task?id=${this.data.latestTask.id}` })
  },

  goTasks() {
    wx.switchTab({ url: '/pages/tasks/tasks' })
  },

  goMine() {
    wx.switchTab({ url: '/pages/mine/mine' })
  },

  ensureAgreementAccepted() {
    if (agreement.hasAcceptedCurrentAgreement()) return true
    this.setData({ agreementAccepted: false, error: '请先阅读并同意当前版本用户协议与隐私说明' })
    wx.showModal({
      title: '需要同意协议',
      content: '上传录音前，请阅读并同意当前版本的《用户协议与隐私说明》。',
      confirmText: '查看协议',
      cancelText: '暂不上传',
      success: (result) => {
        if (result.confirm) this.openAgreement()
      }
    })
    return false
  },

  handleChooseFailure(error) {
    const message = error && error.errMsg ? error.errMsg : ''
    if (message.includes('cancel')) return
    this.setData({ error: message || '选择文件失败' })
  },

  startLatestTaskPollingIfNeeded(task, options = {}) {
    if (!task || !isProcessingStatus(task.status)) {
      this.stopLatestTaskPolling()
      return
    }
    if (!this.pageVisible) return
    if (options.reset) {
      if (this.latestTaskPollTimer) clearTimeout(this.latestTaskPollTimer)
      this.latestTaskPollTimer = null
      this.latestTaskPollAttempt = 0
    }
    if (this.latestTaskPollTimer) return
    const attempt = Number(this.latestTaskPollAttempt || 0)
    const delay = POLL_DELAYS_MS[Math.min(attempt, POLL_DELAYS_MS.length - 1)]
    this.latestTaskPollTimer = setTimeout(() => {
      this.latestTaskPollTimer = null
      this.latestTaskPollAttempt = attempt + 1
      this.pollLatestTaskStatus()
    }, delay)
  },

  async pollLatestTaskStatus() {
    const task = this.data.latestTask
    if (!this.pageVisible || !task || !isProcessingStatus(task.status)) return
    try {
      const data = await api.request('/site/me/tasks/statuses', {
        forceRefresh: true,
        timeout: REQUEST_TIMEOUT_MS
      })
      if (!this.pageVisible) return
      const status = (data.statuses || []).find((item) => item.id === task.id)
      const nextSignature = taskStatusSignature(status)
      if (!status || nextSignature !== this.latestTaskStatusSignature) {
        await this.refreshLatestTask({ silent: true, forceRefresh: true })
        return
      }
    } catch (error) {
      // 短暂网络异常时保留当前任务，并通过退避继续同步。
    }
    this.startLatestTaskPollingIfNeeded(this.data.latestTask)
  },

  stopLatestTaskPolling() {
    if (this.latestTaskPollTimer) clearTimeout(this.latestTaskPollTimer)
    this.latestTaskPollTimer = null
    this.latestTaskPollAttempt = 0
  }
})

function decorateTask(task) {
  return {
    ...task,
    displayTitle: taskDisplayTitle(task),
    statusLabel: statusLabel(task.status),
    statusTheme: statusTheme(task.status),
    summary: taskText(task),
    actionNote: task.status === 'uploaded' ? '点按查看详情和确认转写。' : '点按查看详情和转写结果。'
  }
}

function isProcessingStatus(status) {
  return ['queued', 'starting', 'transcribing'].includes(status)
}

function uploadPhaseLabel(phase) {
  if (phase === 'preparing') return '准备中'
  if (phase === 'finalizing') return '创建任务'
  if (phase === 'complete') return '已上传'
  return '上传中'
}

function uploadPhaseRank(phase) {
  if (phase === 'preparing') return 0
  if (phase === 'uploading') return 1
  if (phase === 'finalizing') return 2
  if (phase === 'complete') return 3
  return 1
}

function taskStatusSignature(task) {
  if (!task) return ''
  return [task.id, task.status, task.updated_at, task.error].map((value) => String(value || '')).join('|')
}

function taskViewSignature(task) {
  if (!task) return ''
  const media = task.media || {}
  return [
    taskStatusSignature(task),
    task.title,
    task.source_name,
    task.duration_seconds,
    task.points_cost,
    media.public_url,
    media.status
  ]
    .map((value) => String(value || ''))
    .join('|')
}

function userSignature(user) {
  if (!user) return ''
  return [user.id, user.nickname, user.name, user.points_balance].map((value) => String(value || '')).join('|')
}

function isAuthError(error) {
  if (error && (error.statusCode === 401 || error.statusCode === 403)) return true
  const message = error && error.message ? error.message : ''
  return message.includes('401') || message.toLowerCase().includes('unauthorized')
}

function inputValue(event) {
  const detail = event.detail || {}
  return typeof detail === 'object' && 'value' in detail ? detail.value : detail
}

function showToast(page, theme, message, duration = 2000) {
  const toast = page.selectComponent('#t-toast')
  if (toast) toast.show({ theme, message, duration })
}
