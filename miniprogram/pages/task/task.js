const api = require('../../utils/api')
const {
  formatDateTime,
  formatDuration,
  formatMilliseconds,
  formatPoints,
  statusLabel,
  statusTheme,
  taskDisplayTitle,
  taskText
} = require('../../utils/format')

const REQUEST_TIMEOUT_MS = 10000
const PAGE_CACHE_MS = 2000
const AUDIO_PROGRESS_THROTTLE_MS = 500
const POLL_DELAYS_MS = [5000, 10000, 20000, 30000]
const EXPORT_OPTIONS = [
  { label: 'TXT 文本', format: 'text' },
  { label: 'SRT 字幕', format: 'srt' },
  { label: 'Word 文档', format: 'doc' }
]

Page({
  data: {
    taskId: '',
    task: null,
    utterances: [],
    audio: null,
    currentTimeText: '00:00',
    durationText: '00:00',
    durationSeconds: 0,
    progressValue: 0,
    isPlaying: false,
    canStart: false,
    isProcessing: false,
    notificationConfig: null,
    notificationAvailable: false,
    notifyOnComplete: true,
    transcriptLoading: false,
    showEmptyTranscript: false,
    deleteDialogVisible: false,
    deleteDialogConfirm: { content: '删除', theme: 'danger' },
    loading: false,
    starting: false,
    deleting: false,
    isExporting: false,
    error: ''
  },

  onLoad(options) {
    const taskId = options.id || ''
    this.setData({ taskId })
    if (!taskId) {
      this.setData({ error: '缺少任务 ID' })
      return
    }
    this.loadTask()
  },

  onShow() {
    this.pageVisible = true
    if (this.hasLoadedOnce && this.data.taskId) {
      this.loadTask({ silent: true, cacheMs: PAGE_CACHE_MS })
    }
    this.hasLoadedOnce = true
  },

  async onPullDownRefresh() {
    await this.loadTask({ silent: true, forceRefresh: true })
    wx.stopPullDownRefresh()
  },

  onHide() {
    this.pageVisible = false
    this.stopPolling()
  },

  onUnload() {
    this.pageVisible = false
    this.stopPolling()
    this.editorLoadToken = ''
    if (this.audio) {
      this.audio.destroy()
      this.audio = null
    }
  },

  async loadTask(options = {}) {
    const silent = options && options.silent === true
    if (!this.data.taskId) return
    if (this.loadingTask) {
      this.startPollingIfNeeded(this.data.task && this.data.task.status)
      return
    }
    this.loadingTask = true
    if (!silent) this.setData({ loading: true, error: '' })
    try {
      const data = await api.request(`/site/me/tasks/${this.data.taskId}`, {
        cacheMs: options.forceRefresh ? 0 : Number(options.cacheMs || 0),
        forceRefresh: options.forceRefresh === true,
        timeout: REQUEST_TIMEOUT_MS
      })
      const task = decorateTask(data.task)
      const notificationConfig = normalizeNotificationConfig(data.notification_config)
      const notificationAvailable = notificationConfig.enabled
      const nextTaskSignature = taskViewSignature(task)
      const previousTask = this.data.task
      const statusChanged = !previousTask || previousTask.status !== task.status
      const durationSeconds = Math.max(0, Math.ceil(Number(task.duration_seconds || 0)))
      const isProcessing = isProcessingStatus(task.status)
      const shouldLoadEditor = task.status === 'completed' || task.status === 'confirmed'
      const editorSignature = editorTaskSignature(task)
      const shouldRefreshEditor = shouldLoadEditor && this.loadedEditorSignature !== editorSignature
      const nextNotificationSignature = notificationConfigSignature(notificationConfig)
      const notificationConfigChanged = this.notificationConfigSignature !== nextNotificationSignature
      if (notificationConfigChanged) this.notificationConfigSignature = nextNotificationSignature
      if (this.taskViewSignature !== nextTaskSignature) {
        this.taskViewSignature = nextTaskSignature
        this.setData({
          task,
          utterances: shouldLoadEditor ? this.data.utterances : [],
          audio:
            task.media && task.media.public_url && this.audioSrc === task.media.public_url
              ? this.data.audio
              : null,
          durationSeconds,
          durationText: formatMilliseconds(durationSeconds * 1000),
          canStart: task.status === 'uploaded',
          isProcessing,
          ...(notificationConfigChanged ? { notificationConfig, notificationAvailable } : {}),
          transcriptLoading: shouldRefreshEditor,
          showEmptyTranscript: false,
          error: ''
        })
        if (!shouldLoadEditor) this.loadedEditorSignature = ''
        this.deferAudioSource(task.media)
      } else if (notificationConfigChanged) {
        this.setData({ notificationConfig, notificationAvailable })
      } else if (shouldRefreshEditor && !this.editorLoading) {
        this.setData({ transcriptLoading: true, showEmptyTranscript: false })
      } else if (options.forceRefresh && this.data.error) {
        this.setData({ error: '' })
      }
      this.taskStatusSignature = taskStatusSignature(task)
      this.startPollingIfNeeded(task.status, { reset: statusChanged || options.resetPolling === true })
      if (shouldRefreshEditor) this.loadEditorAfterTask(task.status, editorSignature)
    } catch (error) {
      if (!silent) this.setData({ error: error.message })
      this.startPollingIfNeeded(this.data.task && this.data.task.status)
    } finally {
      this.loadingTask = false
      if (!silent) this.setData({ loading: false })
    }
  },

  async loadEditorAfterTask(status, expectedSignature) {
    if (status !== 'completed' && status !== 'confirmed') {
      this.setData({ transcriptLoading: false, utterances: [], showEmptyTranscript: false })
      return
    }
    if (this.editorLoading) return
    const token = `${this.data.taskId}:${Date.now()}`
    this.editorLoadToken = token
    this.editorLoading = true
    try {
      const editor = await api.request(`/site/me/tasks/${this.data.taskId}/editor`, {
        cacheMs: PAGE_CACHE_MS,
        timeout: REQUEST_TIMEOUT_MS
      })
      if (this.editorLoadToken !== token) return
      const utterances = normalizeUtterances(editor.editor && editor.editor.utterances)
      this.loadedEditorSignature = expectedSignature
      this.setData({
        utterances,
        transcriptLoading: false,
        showEmptyTranscript: utterances.length === 0
      })
    } catch (error) {
      if (this.editorLoadToken !== token) return
      this.setData({
        utterances: [],
        transcriptLoading: false,
        showEmptyTranscript: true
      })
    } finally {
      if (this.editorLoadToken === token) this.editorLoading = false
    }
  },

  togglePlay() {
    if (!this.audio || !this.data.audio || !this.data.audio.public_url) {
      this.setData({ error: '暂无可播放音频' })
      return
    }
    if (this.data.isPlaying) {
      this.audio.pause()
    } else {
      this.audio.play()
    }
  },

  seekBySlider(event) {
    const value = event.detail && event.detail.value
    this.seekAudio(Number(value || 0), this.data.isPlaying)
  },

  seekUtterance(event) {
    const ms = Number(event.currentTarget.dataset.start || 0)
    if (!this.audio || !this.data.audio || !this.data.audio.public_url) {
      this.setData({ error: '暂无可播放音频' })
      return
    }
    this.seekAudio(ms / 1000, true)
  },

  async exportTask(format) {
    if (this.data.isExporting) return
    const selectedFormat = format || 'text'
    const token = api.getToken()
    if (!token) {
      this.setData({ error: '登录已失效，请重新登录' })
      return
    }
    const url = `${api.API_BASE}/site/me/tasks/${this.data.taskId}/export?format=${encodeURIComponent(selectedFormat)}`
    this.setData({ isExporting: true, error: '' })
    wx.showLoading({ title: '正在导出', mask: true })
    try {
      await waitForNativeUI()
      const res = await downloadFile(url, token)
      if (res.statusCode !== 200) throw new Error(`导出失败：HTTP ${res.statusCode}`)
      await handleExportedFile(res.tempFilePath, selectedFormat)
    } catch (error) {
      this.setData({ error: error.message || '导出失败' })
    } finally {
      wx.hideLoading()
      this.setData({ isExporting: false })
    }
  },

  openExportMenu() {
    if (this.data.isExporting) return
    wx.showActionSheet({
      itemList: EXPORT_OPTIONS.map((option) => option.label),
      success: (result) => {
        const option = EXPORT_OPTIONS[Number(result.tapIndex)]
        if (option) this.exportTask(option.format)
      },
      fail: (error) => {
        const message = (error && error.errMsg) || ''
        if (message && !message.includes('cancel')) this.setData({ error: message })
      }
    })
  },

  async startTask() {
    if (this.data.starting || !this.data.canStart) return
    const shouldRequestNotification = Boolean(
      this.data.notificationAvailable &&
        this.data.notifyOnComplete &&
        this.data.notificationConfig &&
        this.data.notificationConfig.template_id
    )
    const notificationPermission = shouldRequestNotification
      ? requestCompletionNotification(this.data.notificationConfig.template_id)
      : Promise.resolve(false)
    this.setData({ starting: true, error: '' })
    try {
      const notifyOnComplete = await notificationPermission
      const data = await api.request(`/site/me/tasks/${this.data.taskId}/start`, {
        method: 'POST',
        data: {
          confirm_points: true,
          notify_on_complete: notifyOnComplete,
          notification_template_id: notifyOnComplete ? this.data.notificationConfig.template_id : ''
        }
      })
      const task = decorateTask(data.task)
      const isProcessing = isProcessingStatus(task.status)
      this.taskViewSignature = taskViewSignature(task)
      this.taskStatusSignature = taskStatusSignature(task)
      this.loadedEditorSignature = ''
      this.setData({
        task,
        canStart: task.status === 'uploaded',
        isProcessing,
        showEmptyTranscript: false
      })
      this.startPollingIfNeeded(task.status, { reset: true })
      showToast(this, 'success', notifyOnComplete ? '已开始，完成后将通知' : '已开始，正在排队')
    } catch (error) {
      this.setData({ error: error.message })
    } finally {
      this.setData({ starting: false })
    }
  },

  onNotifyChange(event) {
    const checked = Boolean(event && event.detail && event.detail.checked)
    this.setData({ notifyOnComplete: checked, error: '' })
  },

  deleteTask() {
    if (this.data.deleting) return
    this.setData({ deleteDialogVisible: true })
  },

  closeDeleteDialog() {
    this.setData({ deleteDialogVisible: false })
  },

  async confirmDeleteTask() {
    if (this.data.deleting) return
    this.setData({ deleteDialogVisible: false, deleting: true, error: '' })
    try {
      await api.request(`/site/me/tasks/${this.data.taskId}`, { method: 'DELETE' })
      this.stopPolling()
      navigateAfterDelete()
    } catch (error) {
      this.setData({ error: error.message })
    } finally {
      this.setData({ deleting: false })
    }
  },

  ensureAudioContext() {
    if (this.audio) return this.audio
    this.audio = wx.createInnerAudioContext()
    this.audio.onPlay(() => this.setData({ isPlaying: true }))
    this.audio.onPause(() => this.setData({ isPlaying: false }))
    this.audio.onStop(() => this.setData({ isPlaying: false }))
    this.audio.onEnded(() => {
      this.setData({
        isPlaying: false,
        progressValue: this.data.durationSeconds,
        currentTimeText: this.data.durationText
      })
    })
    this.audio.onCanplay(() => this.syncAudioProgress(true))
    this.audio.onTimeUpdate(() => this.syncAudioProgress())
    this.audio.onError((error) => {
      this.setData({ error: error.errMsg || '音频播放失败' })
    })
    return this.audio
  },

  deferAudioSource(media) {
    const token = `${this.data.taskId}:${media && media.public_url ? media.public_url : ''}`
    this.audioLoadToken = token
    setTimeout(() => {
      if (this.audioLoadToken !== token) return
      this.updateAudioSource(media)
    }, 0)
  },

  updateAudioSource(media) {
    const url = media && media.public_url ? media.public_url : ''
    const audio = url ? this.ensureAudioContext() : this.audio
    if (!audio) return
    if (!url) {
      if (this.audioSrc) audio.stop()
      this.audioSrc = ''
      this.setData({ audio: null, isPlaying: false, progressValue: 0, currentTimeText: '00:00' })
      return
    }
    if (this.audioSrc === url) return
    this.audioSrc = url
    audio.src = url
    this.setData({ audio: media || null, isPlaying: false, progressValue: 0, currentTimeText: '00:00' })
  },

  syncAudioProgress(force = false) {
    if (!this.audio) return
    const now = Date.now()
    if (!force && now - Number(this.lastAudioProgressSyncAt || 0) < AUDIO_PROGRESS_THROTTLE_MS) return
    this.lastAudioProgressSyncAt = now
    const currentSeconds = Math.max(0, Math.floor(Number(this.audio.currentTime || 0)))
    const audioDurationSeconds = Math.max(0, Math.ceil(Number(this.audio.duration || 0)))
    const durationSeconds = audioDurationSeconds || this.data.durationSeconds
    const nextData = {}
    if (currentSeconds !== this.data.progressValue) {
      nextData.progressValue = currentSeconds
      nextData.currentTimeText = formatMilliseconds(currentSeconds * 1000)
    }
    if (durationSeconds && durationSeconds !== this.data.durationSeconds) {
      nextData.durationSeconds = durationSeconds
      nextData.durationText = formatMilliseconds(durationSeconds * 1000)
    }
    if (Object.keys(nextData).length > 0) this.setData(nextData)
  },

  seekAudio(seconds, shouldPlay) {
    if (!this.audio || !this.data.audio || !this.data.audio.public_url) return
    const maxSeconds = this.data.durationSeconds || Number.MAX_SAFE_INTEGER
    const nextSeconds = Math.max(0, Math.min(Number(seconds) || 0, maxSeconds))
    this.setData({
      progressValue: nextSeconds,
      currentTimeText: formatMilliseconds(nextSeconds * 1000),
      error: ''
    })
    this.lastAudioProgressSyncAt = Date.now()
    this.audio.seek(nextSeconds)
    if (shouldPlay) this.audio.play()
  },

  startPollingIfNeeded(status, options = {}) {
    if (!isProcessingStatus(status)) {
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
      this.pollTaskStatus()
    }, delay)
  },

  async pollTaskStatus() {
    const task = this.data.task
    if (!this.pageVisible || !task || !isProcessingStatus(task.status)) return
    try {
      const data = await api.request('/site/me/tasks/statuses', {
        forceRefresh: true,
        timeout: REQUEST_TIMEOUT_MS
      })
      if (!this.pageVisible) return
      const status = (data.statuses || []).find((item) => item.id === this.data.taskId)
      if (!status || taskStatusSignature(status) !== this.taskStatusSignature) {
        await this.loadTask({ silent: true, forceRefresh: true, resetPolling: true })
        return
      }
    } catch (error) {
      // 短暂网络异常时保留页面内容，并通过退避继续同步。
    }
    this.startPollingIfNeeded(this.data.task && this.data.task.status)
  },

  stopPolling() {
    if (this.pollTimer) clearTimeout(this.pollTimer)
    this.pollTimer = null
    this.pollAttempt = 0
  }
})

function decorateTask(task) {
  return {
    ...task,
    displayTitle: taskDisplayTitle(task),
    statusLabel: statusLabel(task.status),
    statusTheme: statusTheme(task.status),
    durationText: formatDuration(task.duration_seconds),
    pointsText: formatPoints(task.points_cost),
    createdText: formatDateTime(task.created_at),
    expiresText: formatDateTime(task.expires_at),
    updatedText: formatDateTime(task.updated_at),
    summary: taskText(task)
  }
}

function normalizeUtterances(utterances) {
  if (!Array.isArray(utterances)) return []
  return utterances.map((item, index) => ({
    ...item,
    id: item.id || `utterance_${index}`,
    speaker: item.speaker || item.role || `#${index + 1}`,
    text: item.text || '',
    start_time: item.start_time || item.start_ms || 0,
    start_text: formatMilliseconds(item.start_time || item.start_ms || 0),
    speakerShort: speakerInitial(item.speaker || item.role || `#${index + 1}`)
  }))
}

function speakerInitial(value) {
  const text = String(value || '说')
  return text.length > 2 ? text.slice(-2) : text
}

function isProcessingStatus(status) {
  return ['queued', 'starting', 'transcribing'].includes(status)
}

function normalizeNotificationConfig(config) {
  const templateId = String((config && config.template_id) || '').trim()
  return {
    enabled: Boolean(config && config.enabled && templateId),
    template_id: templateId
  }
}

function notificationConfigSignature(config) {
  return `${config.enabled ? '1' : '0'}|${config.template_id}`
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
    task.expires_at,
    media.public_url,
    media.status
  ]
    .map((value) => String(value || ''))
    .join('|')
}

function editorTaskSignature(task) {
  if (!task) return ''
  return [task.id, task.status, task.updated_at].map((value) => String(value || '')).join('|')
}

function showToast(page, theme, message, duration = 2000) {
  const toast = page.selectComponent('#t-toast')
  if (toast) toast.show({ theme, message, duration })
}

function waitForNativeUI() {
  return new Promise((resolve) => {
    if (typeof wx.nextTick === 'function') {
      wx.nextTick(resolve)
      return
    }
    setTimeout(resolve, 0)
  })
}

function requestCompletionNotification(templateId) {
  if (!templateId || typeof wx.requestSubscribeMessage !== 'function') return Promise.resolve(false)
  return new Promise((resolve) => {
    wx.requestSubscribeMessage({
      tmplIds: [templateId],
      success: (result) => resolve(result && result[templateId] === 'accept'),
      fail: () => resolve(false)
    })
  })
}

function downloadFile(url, token) {
  return new Promise((resolve, reject) => {
    wx.downloadFile({
      url,
      header: {
        Authorization: `Bearer ${token}`
      },
      success: resolve,
      fail: (error) => reject(new Error((error && error.errMsg) || '导出失败'))
    })
  })
}

function openDocument(filePath) {
  return new Promise((resolve, reject) => {
    wx.openDocument({
      filePath,
      showMenu: true,
      success: resolve,
      fail: (error) => reject(new Error((error && error.errMsg) || '文件预览失败'))
    })
  })
}

function readFileText(filePath) {
  return new Promise((resolve, reject) => {
    wx.getFileSystemManager().readFile({
      filePath,
      encoding: 'utf8',
      success: (res) => resolve(res.data || ''),
      fail: (error) => reject(new Error((error && error.errMsg) || '读取导出文件失败'))
    })
  })
}

function setClipboardData(data) {
  return new Promise((resolve, reject) => {
    wx.setClipboardData({
      data,
      success: resolve,
      fail: (error) => reject(new Error((error && error.errMsg) || '复制失败'))
    })
  })
}

async function handleExportedFile(filePath, format) {
  if (format === 'doc') {
    await openDocument(filePath)
    return
  }
  try {
    await openDocument(filePath)
  } catch (error) {
    const text = await readFileText(filePath)
    await setClipboardData(text)
  }
}

function navigateAfterDelete() {
  const pages = getCurrentPages()
  if (pages.length > 1) {
    wx.navigateBack()
    return
  }
  wx.switchTab({ url: '/pages/tasks/tasks' })
}
