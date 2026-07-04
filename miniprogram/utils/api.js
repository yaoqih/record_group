const { API_BASE, USE_DEV_LOGIN } = require('./config')

function getToken() {
  return wx.getStorageSync('recordflow_token') || ''
}

function setSession(token, user) {
  wx.setStorageSync('recordflow_token', token)
  wx.setStorageSync('recordflow_user', user)
}

function clearSession() {
  wx.removeStorageSync('recordflow_token')
  wx.removeStorageSync('recordflow_user')
}

function getCachedUser() {
  return wx.getStorageSync('recordflow_user') || null
}

function request(path, options = {}) {
  const token = getToken()
  const header = Object.assign({}, options.header || {})
  if (token) header.Authorization = `Bearer ${token}`
  return new Promise((resolve, reject) => {
    wx.request({
      url: `${API_BASE}${path}`,
      method: options.method || 'GET',
      data: options.data,
      header,
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data)
          return
        }
        reject(new Error(resolveErrorMessage(res.data, `请求失败：HTTP ${res.statusCode}`)))
      },
      fail: (err) => reject(new Error(err.errMsg || '网络请求失败'))
    })
  })
}

function loginWithWechat(nickname) {
  if (USE_DEV_LOGIN) {
    return request('/site/auth/dev/login', {
      method: 'POST',
      data: { nickname: nickname || '开发用户' }
    }).then((data) => {
      setSession(data.token, data.user)
      return data
    })
  }
  return new Promise((resolve, reject) => {
    wx.login({
      success: ({ code }) => {
        if (!code) {
          reject(new Error('微信登录失败：没有返回 code'))
          return
        }
        request('/site/auth/wechat/login', {
          method: 'POST',
          data: { code, nickname: nickname || '' }
        })
          .then((data) => {
            setSession(data.token, data.user)
            resolve(data)
          })
          .catch(reject)
      },
      fail: (err) => reject(new Error(err.errMsg || '微信登录失败'))
    })
  })
}

function uploadTask(filePath, name, sizeBytes) {
  const sourceName = name || 'recording.mp3'
  return request('/site/me/tasks/direct-upload/init', {
    method: 'POST',
    data: {
      source_name: sourceName,
      size_bytes: sizeBytes || undefined
    }
  }).then((data) => uploadFileToCOS(filePath, sourceName, data))
}

function uploadFileToCOS(filePath, sourceName, initData) {
  const upload = initData.upload || {}
  const formData = upload.form_data || {}
  return new Promise((resolve, reject) => {
    wx.uploadFile({
      url: upload.url,
      filePath,
      name: upload.file_field || 'file',
      fileName: sourceName,
      formData,
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          request('/site/me/tasks/direct-upload/complete', {
            method: 'POST',
            data: {
              upload_token: initData.upload_token,
              object_key: upload.object_key
            }
          })
            .then(resolve)
            .catch(reject)
          return
        }
        reject(new Error(resolveCOSUploadError(res)))
      },
      fail: (err) => reject(new Error(err.errMsg || '上传失败'))
    })
  })
}

function resolveCOSUploadError(res) {
  const text = res && res.data ? String(res.data) : ''
  const message = extractXMLMessage(text)
  return message || `上传到临时存储失败：HTTP ${res.statusCode}`
}

function extractXMLMessage(text) {
  const matched = text.match(/<Message>([^<]+)<\/Message>/)
  return matched ? matched[1] : ''
}

function resolveErrorMessage(data, fallback) {
  if (data && typeof data.detail === 'string') return data.detail
  if (data && typeof data.message === 'string') return data.message
  return fallback
}

module.exports = {
  API_BASE,
  clearSession,
  getCachedUser,
  getToken,
  loginWithWechat,
  request,
  setSession,
  uploadTask
}
