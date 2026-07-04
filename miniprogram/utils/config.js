// 可选值：'staging' 或 'production'。设为空字符串时按小程序版本自动选择。
const API_ENV_OVERRIDE = ''

const API_BASES = {
  staging: 'https://test-record.blenet.top',
  production: 'https://record-api.blenet.top'
}

const API_ENV_BY_VERSION = {
  develop: 'staging',
  trial: 'staging',
  release: 'production'
}

function resolveApiEnv() {
  if (API_ENV_OVERRIDE) return API_ENV_OVERRIDE
  if (typeof wx === 'undefined' || !wx.getAccountInfoSync) return 'staging'
  const accountInfo = wx.getAccountInfoSync()
  const envVersion = accountInfo && accountInfo.miniProgram && accountInfo.miniProgram.envVersion
  return API_ENV_BY_VERSION[envVersion] || 'staging'
}

const API_ENV = resolveApiEnv()
const API_BASE = API_BASES[API_ENV]

// 游客模式/无 AppID 时 wx.login 只能返回模拟结果。需要只调页面和上传流程时可临时打开。
const USE_DEV_LOGIN = false

module.exports = {
  API_BASE,
  API_ENV,
  USE_DEV_LOGIN
}
