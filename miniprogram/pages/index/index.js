const api = require('../../utils/api')
const { statusLabel, statusTheme, taskDisplayTitle, taskText } = require('../../utils/format')

const MAX_AUDIO_BYTES = 200 * 1024 * 1024
const AUDIO_EXTENSIONS = ['.aac', '.aif', '.aiff', '.flac', '.m4a', '.mp3', '.oga', '.ogg', '.opus', '.pcm', '.wav', '.webm']

Page({
  data: {
    user: null,
    nickname: '',
    loading: false,
    uploading: false,
    selectedName: '',
    latestTask: null,
    error: ''
  },

  onShow() {
    this.loadMe()
  },

  onNicknameInput(event) {
    this.setData({ nickname: inputValue(event) })
  },

  async onLogin() {
    if (this.data.loading || this.data.uploading) return
    this.setData({ loading: true, error: '' })
    try {
      const data = await api.loginWithWechat(this.data.nickname)
      this.setData({ user: data.user, latestTask: null, selectedName: '' })
      getApp().globalData.user = data.user
    } catch (error) {
      this.setData({ error: error.message })
    } finally {
      this.setData({ loading: false })
    }
  },

  async loadMe() {
    if (!api.getToken()) {
      this.setData({ user: null, latestTask: null, selectedName: '' })
      getApp().globalData.user = null
      return
    }
    try {
      const data = await api.request('/site/me')
      this.setData({ user: data.user })
      getApp().globalData.user = data.user
    } catch (error) {
      api.clearSession()
      this.setData({ user: null, latestTask: null, selectedName: '' })
      getApp().globalData.user = null
    }
  },

  chooseMessageFile() {
    if (!this.data.user || this.data.uploading) return
    wx.chooseMessageFile({
      count: 1,
      type: 'file',
      extension: AUDIO_EXTENSIONS,
      success: (res) => {
        const file = res.tempFiles[0]
        if (file && this.validateAudioFile(file)) this.upload(file.path, file.name)
      },
      fail: (error) => this.handleChooseFailure(error)
    })
  },

  async upload(filePath, name) {
    if (this.data.uploading) return
    if (!api.getToken()) {
      this.setData({ error: '请先登录' })
      return
    }
    this.setData({ uploading: true, selectedName: name, error: '' })
    try {
      const data = await api.uploadTask(filePath, name)
      const task = decorateTask(data.task)
      this.setData({ latestTask: task })
      showToast(this, 'success', '上传成功')
    } catch (error) {
      this.setData({ error: error.message })
    } finally {
      this.setData({ uploading: false })
    }
  },

  openLatestTask() {
    if (!this.data.latestTask) return
    wx.navigateTo({ url: `/pages/task/task?id=${this.data.latestTask.id}` })
  },

  handleChooseFailure(error) {
    const message = error && error.errMsg ? error.errMsg : ''
    if (message.includes('cancel')) return
    this.setData({ error: message || '选择文件失败' })
  },

  validateAudioFile(file) {
    const name = file.name || ''
    const size = Number(file.size || 0)
    const lowerName = name.toLowerCase()
    const isAudio = AUDIO_EXTENSIONS.some((ext) => lowerName.endsWith(ext))
    if (!isAudio) {
      this.setData({ error: '仅支持提交音频文件' })
      return false
    }
    if (size > MAX_AUDIO_BYTES) {
      this.setData({ error: '音频文件不能超过 200MB' })
      return false
    }
    return true
  }
})

function decorateTask(task) {
  return {
    ...task,
    displayTitle: taskDisplayTitle(task),
    statusLabel: statusLabel(task.status),
    statusTheme: statusTheme(task.status),
    summary: taskText(task)
  }
}

function inputValue(event) {
  const detail = event.detail || {}
  return typeof detail === 'object' && 'value' in detail ? detail.value : detail
}

function showToast(page, theme, message, duration = 2000) {
  const toast = page.selectComponent('#t-toast')
  if (toast) toast.show({ theme, message, duration })
}
