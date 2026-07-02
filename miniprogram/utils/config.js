// 本地开发可用 http://127.0.0.1:8000；真机和上线必须换成 HTTPS 域名。
const API_BASE = 'http://127.0.0.1:8000'

// 游客模式/无 AppID 时 wx.login 只能返回模拟结果。需要只调页面和上传流程时可临时打开。
const USE_DEV_LOGIN = false

module.exports = {
  API_BASE,
  USE_DEV_LOGIN
}
