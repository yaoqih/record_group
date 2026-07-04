// 可选值：'staging' 或 'production'。真机和上线必须使用 HTTPS 域名。
const API_ENV = 'staging'

const API_BASES = {
  staging: 'https://test.record.sever.blenet.top',
  production: 'https://record.sever.blenet.top'
}

const API_BASE = API_BASES[API_ENV]

// 游客模式/无 AppID 时 wx.login 只能返回模拟结果。需要只调页面和上传流程时可临时打开。
const USE_DEV_LOGIN = false

module.exports = {
  API_BASE,
  API_ENV,
  USE_DEV_LOGIN
}
