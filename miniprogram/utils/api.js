const { API_BASE, USE_DEV_LOGIN } = require('./config')
const agreement = require('./agreement')

const MAX_CACHE_ENTRIES = 30
const pendingRequests = new Map()
const responseCache = new Map()
let cacheGeneration = 0

function getToken() {
  return wx.getStorageSync('recordflow_token') || ''
}

function setSession(token, user) {
  invalidateRequestCache()
  wx.setStorageSync('recordflow_token', token)
  wx.setStorageSync('recordflow_user', user)
}

function clearSession() {
  invalidateRequestCache()
  wx.removeStorageSync('recordflow_token')
  wx.removeStorageSync('recordflow_user')
}

function getCachedUser() {
  return wx.getStorageSync('recordflow_user') || null
}

function request(path, options = {}) {
  const token = getToken()
  const method = String(options.method || 'GET').toUpperCase()
  const header = Object.assign({}, options.header || {})
  if (token) header.Authorization = `Bearer ${token}`
  const requestKey = buildRequestKey(method, path, options.data, header)
  const canDedupe = method === 'GET' && options.dedupe !== false
  const cacheMs = method === 'GET' ? Math.max(0, Number(options.cacheMs || 0)) : 0
  const cached = !options.forceRefresh && cacheMs > 0 ? getCachedResponse(requestKey) : null
  if (cached) return Promise.resolve(cached.data)
  if (canDedupe && pendingRequests.has(requestKey)) return pendingRequests.get(requestKey)

  const generation = cacheGeneration
  const requestPromise = new Promise((resolve, reject) => {
    const requestOptions = {
      url: `${API_BASE}${path}`,
      method,
      data: options.data,
      header,
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          if (method !== 'GET') invalidateRequestCache()
          if (cacheMs > 0 && generation === cacheGeneration) {
            cacheResponse(requestKey, res.data, cacheMs)
          }
          resolve(res.data)
          return
        }
        const error = new Error(resolveErrorMessage(res.data, `请求失败：HTTP ${res.statusCode}`))
        error.statusCode = res.statusCode
        error.requestId = res.header && (res.header['X-Request-ID'] || res.header['x-request-id'])
        reject(error)
      },
      fail: (err) => reject(new Error(err.errMsg || '网络请求失败'))
    }
    const timeout = Number(options.timeout || 0)
    if (timeout > 0) requestOptions.timeout = timeout
    wx.request(requestOptions)
  })
  if (!canDedupe) return requestPromise

  pendingRequests.set(requestKey, requestPromise)
  const clearPending = () => {
    if (pendingRequests.get(requestKey) === requestPromise) pendingRequests.delete(requestKey)
  }
  requestPromise.then(clearPending, clearPending)
  return requestPromise
}

function buildRequestKey(method, path, data, header) {
  return `${method}:${path}:${stableStringify(data)}:${stableStringify(header)}`
}

function stableStringify(value) {
  if (value === undefined) return ''
  if (value === null || typeof value !== 'object') return JSON.stringify(value)
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(',')}]`
  return `{${Object.keys(value)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`)
    .join(',')}}`
}

function getCachedResponse(key) {
  const cached = responseCache.get(key)
  if (!cached) return null
  if (cached.expiresAt <= Date.now()) {
    responseCache.delete(key)
    return null
  }
  return cached
}

function cacheResponse(key, data, cacheMs) {
  if (responseCache.size >= MAX_CACHE_ENTRIES && !responseCache.has(key)) {
    const oldestKey = responseCache.keys().next().value
    if (oldestKey) responseCache.delete(oldestKey)
  }
  responseCache.set(key, { data, expiresAt: Date.now() + cacheMs })
}

function invalidateRequestCache() {
  cacheGeneration += 1
  responseCache.clear()
}

function loginWithWechat(nickname) {
  if (!agreement.hasAcceptedCurrentAgreement()) {
    return Promise.reject(new Error('请先阅读并同意用户协议与隐私说明'))
  }
  const agreementData = agreement.loginPayload()
  if (USE_DEV_LOGIN) {
    return request('/site/auth/dev/login', {
      method: 'POST',
      data: {
        nickname: nickname || '开发用户',
        ...agreementData
      }
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
          data: {
            code,
            nickname: nickname || '',
            ...agreementData
          }
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

function uploadTask(filePath, name, sizeBytes, options = {}) {
  if (!agreement.hasAcceptedCurrentAgreement()) {
    return Promise.reject(new Error('请先阅读并同意当前版本用户协议与隐私说明'))
  }
  const sourceName = name || 'recording.mp3'
  notifyUploadProgress(options, { progress: 0, phase: 'preparing' })
  return request('/site/me/tasks/direct-upload/init', {
    method: 'POST',
    data: {
      source_name: sourceName,
      size_bytes: sizeBytes || undefined
    }
  }).then((data) => uploadFileToCOS(filePath, sourceName, data, options))
}

function uploadFileToCOS(filePath, sourceName, initData, options) {
  const upload = initData.upload || {}
  if (upload.method && upload.method !== 'POST') {
    return Promise.reject(new Error(`暂不支持 ${upload.method} 上传方式`))
  }
  return postFileToCOS(filePath, sourceName, initData, upload, options)
}

function postFileToCOS(filePath, sourceName, initData, upload, options) {
  const formData = upload.form_data || {}
  return new Promise((resolve, reject) => {
    const uploadTask = wx.uploadFile({
      url: upload.url,
      filePath,
      name: upload.file_field || 'file',
      fileName: sourceName,
      formData,
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          notifyUploadProgress(options, { progress: 100, phase: 'finalizing' })
          completeDirectUpload(initData, upload)
            .then((data) => {
              notifyUploadProgress(options, { progress: 100, phase: 'complete' })
              resolve(data)
            })
            .catch(reject)
          return
        }
        reject(new Error(resolveCOSUploadError(res)))
      },
      fail: (err) => reject(new Error(err.errMsg || '上传失败'))
    })
    if (uploadTask && typeof uploadTask.onProgressUpdate === 'function') {
      uploadTask.onProgressUpdate((detail) => {
        notifyUploadProgress(options, {
          progress: detail.progress,
          phase: 'uploading',
          totalBytesSent: detail.totalBytesSent,
          totalBytesExpectedToSend: detail.totalBytesExpectedToSend
        })
      })
    }
  })
}

function notifyUploadProgress(options, detail) {
  if (!options || typeof options.onProgress !== 'function') return
  options.onProgress(detail)
}

function completeDirectUpload(initData, upload) {
  return request('/site/me/tasks/direct-upload/complete', {
    method: 'POST',
    data: {
      upload_token: initData.upload_token,
      object_key: upload.object_key
    }
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
