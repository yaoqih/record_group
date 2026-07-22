const api = require('../../utils/api')
const { API_BASE } = require('../../utils/config')

Page({
  data: { src: '' },

  onLoad() {
    const token = api.getToken()
    if (!token) {
      wx.showToast({ title: '请先登录', icon: 'none' })
      setTimeout(() => wx.navigateBack(), 800)
      return
    }
    this.setData({ src: `${API_BASE}/mobile-upload#token=${encodeURIComponent(token)}` })
  }
})
