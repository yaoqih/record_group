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
    transcriptLoading: false,
    showEmptyTranscript: false,
    deleteDialogVisible: false,
    deleteDialogConfirm: { content: '删除', theme: 'danger' },
    loading: false,
    starting: false,
    deleting: false,
    isExporting: false,
    exportingFormat: '',
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

  onUnload() {
    this.stopPolling()
    if (this.audio) {
      this.audio.destroy()
      this.audio = null
    }
  },

  async loadTask(options = {}) {
    const silent = options && options.silent === true
    if (!this.data.taskId || this.loadingTask) return
    this.loadingTask = true
    if (!silent) this.setData({ loading: true, error: '' })
    try {
      const data = await api.request(`/site/me/tasks/${this.data.taskId}`)
      const task = decorateTask(data.task)
      const durationSeconds = Math.max(0, Math.ceil(Number(task.duration_seconds || 0)))
      const isProcessing = isProcessingStatus(task.status)
      const shouldLoadEditor = task.status === 'completed' || task.status === 'confirmed'
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
        transcriptLoading: shouldLoadEditor,
        showEmptyTranscript: false
      })
      this.startPollingIfNeeded(task.status)
      this.deferAudioSource(task.media)
      this.loadEditorAfterTask(task.status)
    } catch (error) {
      if (!silent) this.setData({ error: error.message })
    } finally {
      this.loadingTask = false
      if (!silent) this.setData({ loading: false })
    }
  },

  async loadEditorAfterTask(status) {
    if (status !== 'completed' && status !== 'confirmed') {
      this.setData({ transcriptLoading: false, utterances: [], showEmptyTranscript: false })
      return
    }
    const token = `${this.data.taskId}:${Date.now()}`
    this.editorLoadToken = token
    try {
      const editor = await api.request(`/site/me/tasks/${this.data.taskId}/editor`)
      if (this.editorLoadToken !== token) return
      const utterances = normalizeUtterances(editor.editor && editor.editor.utterances)
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

  async exportTask(event) {
    if (this.data.isExporting) return
    const format = eventDataset(event).format || 'text'
    const token = api.getToken()
    if (!token) {
      this.setData({ error: '登录已失效，请重新登录' })
      return
    }
    const url = `${api.API_BASE}/site/me/tasks/${this.data.taskId}/export?format=${format}&site_token=${encodeURIComponent(token)}`
    this.setData({ isExporting: true, exportingFormat: format, error: '' })
    showToast(this, 'loading', '导出中', 0)
    try {
      const res = await downloadFile(url)
      if (res.statusCode !== 200) throw new Error(`导出失败：HTTP ${res.statusCode}`)
      await handleExportedFile(this, res.tempFilePath, format)
    } catch (error) {
      hideToast(this)
      this.setData({ error: error.message || '导出失败' })
    } finally {
      this.setData({ isExporting: false, exportingFormat: '' })
    }
  },

  async startTask() {
    if (this.data.starting || !this.data.canStart) return
    this.setData({ starting: true, error: '' })
    try {
      const data = await api.request(`/site/me/tasks/${this.data.taskId}/start`, {
        method: 'POST',
        data: { confirm_points: true }
      })
      const task = decorateTask(data.task)
      const isProcessing = isProcessingStatus(task.status)
      this.setData({
        task,
        canStart: task.status === 'uploaded',
        isProcessing,
        showEmptyTranscript: false
      })
      this.startPollingIfNeeded(task.status)
      showToast(this, 'success', '已开始，正在排队')
    } catch (error) {
      this.setData({ error: error.message })
    } finally {
      this.setData({ starting: false })
    }
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
    this.audio.onCanplay(() => this.syncAudioProgress())
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

  syncAudioProgress() {
    if (!this.audio) return
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
    this.audio.seek(nextSeconds)
    if (shouldPlay) this.audio.play()
  },

  startPollingIfNeeded(status) {
    if (!isProcessingStatus(status)) {
      this.stopPolling()
      return
    }
    if (this.pollTimer) return
    this.pollTimer = setInterval(() => {
      this.loadTask({ silent: true })
    }, 5000)
  },

  stopPolling() {
    if (!this.pollTimer) return
    clearInterval(this.pollTimer)
    this.pollTimer = null
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
    start_text: formatMilliseconds(item.start_time || item.start_ms || 0)
  }))
}

function isProcessingStatus(status) {
  return ['queued', 'starting', 'transcribing'].includes(status)
}

function eventDataset(event) {
  return (
    (event.currentTarget && event.currentTarget.dataset) ||
    (event.detail && event.detail.currentTarget && event.detail.currentTarget.dataset) ||
    {}
  )
}

function showToast(page, theme, message, duration = 2000) {
  const toast = page.selectComponent('#t-toast')
  if (toast) toast.show({ theme, message, duration })
}

function hideToast(page) {
  const toast = page.selectComponent('#t-toast')
  if (toast) toast.hide()
}

function downloadFile(url) {
  return new Promise((resolve, reject) => {
    wx.downloadFile({
      url,
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

async function handleExportedFile(page, filePath, format) {
  hideToast(page)
  if (format === 'doc') {
    await openDocument(filePath)
    showToast(page, 'success', '已打开 Word')
    return
  }
  try {
    await openDocument(filePath)
    showToast(page, 'success', '已打开文件')
  } catch (error) {
    const text = await readFileText(filePath)
    await setClipboardData(text)
    showToast(page, 'success', '已复制到剪贴板')
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
