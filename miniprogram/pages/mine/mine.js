const api = require('../../utils/api')

Page({
  data: {
    user: null,
    headerSubtitle: '登录后管理账户和充值点数',
    customPoints: 100,
    loading: false,
    paying: false,
    payingPoints: 0,
    payingCustom: false,
    error: ''
  },

  onShow() {
    this.loadMe()
  },

  onCustomPointsInput(event) {
    this.setData({ customPoints: normalizePoints(inputValue(event)) })
  },

  async loadMe() {
    if (!api.getToken()) {
      this.setData({
        user: null,
        headerSubtitle: '登录后管理账户和充值点数',
        error: ''
      })
      return
    }
    if (this.data.loading) return
    this.setData({ loading: true, error: '' })
    try {
      const data = await api.request('/site/me')
      this.setData({
        user: data.user,
        headerSubtitle: '管理账户和点数充值'
      })
      getApp().globalData.user = data.user
    } catch (error) {
      if (isAuthError(error)) {
        api.clearSession()
        getApp().globalData.user = null
        this.setData({
          user: null,
          headerSubtitle: '登录后管理账户和充值点数',
          error: ''
        })
      } else {
        this.setData({ error: error.message })
      }
    } finally {
      this.setData({ loading: false })
    }
  },

  async recharge(event) {
    if (this.data.paying) return
    const fixedPoints = Number(eventDataset(event).points || 0)
    const points = fixedPoints || normalizePoints(this.data.customPoints)
    if (points < 10 || points > 10000) {
      this.setData({ error: '充值点数范围为 10-10000' })
      return
    }
    if (!points) return
    this.setData({
      paying: true,
      payingPoints: fixedPoints,
      payingCustom: !fixedPoints,
      customPoints: fixedPoints ? this.data.customPoints : points,
      error: ''
    })
    try {
      const data = await api.request('/site/me/recharge/wechatpay', {
        method: 'POST',
        data: { points }
      })
      await requestPayment(data.payment)
      const confirmed = await api.request('/site/me/recharge/wechatpay/confirm', {
        method: 'POST',
        data: { out_trade_no: data.payment.outTradeNo }
      })
      this.setData({ user: confirmed.user })
      getApp().globalData.user = confirmed.user
      if (confirmed.trade_state && confirmed.trade_state !== 'SUCCESS') {
        this.setData({ error: '支付结果确认中，请稍后刷新账户余额' })
        return
      }
      showToast(this, 'success', '支付完成')
    } catch (error) {
      if (isPaymentCancel(error)) {
        showToast(this, 'warning', '已取消支付')
      } else {
        this.setData({ error: error.message })
      }
    } finally {
      this.setData({ paying: false, payingPoints: 0, payingCustom: false })
    }
  },

  logout() {
    if (!this.data.user) return
    api.clearSession()
    getApp().globalData.user = null
    this.setData({
      user: null,
      headerSubtitle: '登录后管理账户和充值点数',
      error: ''
    })
    showToast(this, 'success', '已退出')
  },

  goLogin() {
    wx.switchTab({ url: '/pages/index/index' })
  },

  copyUserId() {
    const userId = this.data.user && this.data.user.id
    if (!userId) return
    wx.setClipboardData({
      data: userId,
      success: () => showToast(this, 'success', '已复制用户 ID'),
      fail: () => this.setData({ error: '复制用户 ID 失败' })
    })
  }
})

function requestPayment(payment) {
  return new Promise((resolve, reject) => {
    wx.requestPayment({
      timeStamp: payment.timeStamp,
      nonceStr: payment.nonceStr,
      package: payment.package,
      signType: payment.signType || 'RSA',
      paySign: payment.paySign,
      success: resolve,
      fail: (err) => reject(new Error(err.errMsg || '支付失败'))
    })
  })
}

function inputValue(event) {
  const detail = event.detail || {}
  return typeof detail === 'object' && 'value' in detail ? detail.value : detail
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

function normalizePoints(value) {
  return Math.floor(Number(value) || 0)
}

function isPaymentCancel(error) {
  const message = error && error.message ? error.message : ''
  return message.includes('cancel') || message.includes('取消')
}

function isAuthError(error) {
  const message = error && error.message ? error.message : ''
  return message.includes('401') || message.toLowerCase().includes('unauthorized')
}
