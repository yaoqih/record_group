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

function uploadTask(filePath, name) {
  const token = getToken()
  return new Promise((resolve, reject) => {
    wx.uploadFile({
      url: `${API_BASE}/site/me/tasks`,
      filePath,
      name: 'file',
      fileName: name || 'recording.mp3',
      formData: {
        source_name: name || 'recording.mp3'
      },
      header: token ? { Authorization: `Bearer ${token}` } : {},
      success: (res) => {
        let data = {}
        try {
          data = JSON.parse(res.data || '{}')
        } catch (error) {
          reject(new Error('上传成功但返回内容不是 JSON'))
          return
        }
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(data)
          return
        }
        reject(new Error(resolveErrorMessage(data, `上传失败：HTTP ${res.statusCode}`)))
      },
      fail: (err) => reject(new Error(err.errMsg || '上传失败'))
    })
  })
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
