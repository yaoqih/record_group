const api = require('../../utils/api')

const REQUEST_TIMEOUT_MS = 10000
const PAGE_CACHE_MS = 3000

Page({
  data: {
    user: null,
    displayName: '微信用户',
    userInitial: 'R',
    balanceYuan: '0.00',
    pointOptions: [
      { points: 100, price: '1' },
      { points: 500, price: '5', tag: '常用' },
      { points: 1000, price: '10' }
    ],
    selectedPoints: 500,
    selectedPrice: '5',
    showCustomPay: false,
    headerSubtitle: '登录后管理账户和充值点数',
    customPoints: 100,
    loading: false,
    paying: false,
    payingPoints: 0,
    payingCustom: false,
    error: ''
  },

  onShow() {
    const cachedUser = api.getCachedUser()
    if (cachedUser && !this.data.user) this.applyUser(cachedUser)
    this.loadMe({ silent: Boolean(cachedUser), cacheMs: PAGE_CACHE_MS })
  },

  async onPullDownRefresh() {
    await this.loadMe({ silent: true, forceRefresh: true })
    wx.stopPullDownRefresh()
  },

  onCustomPointsInput(event) {
    this.setData({ customPoints: normalizePoints(inputValue(event)) })
  },

  async loadMe(options = {}) {
    if (!api.getToken()) {
      this.setData({
        user: null,
        headerSubtitle: '登录后管理账户和充值点数',
        error: ''
      })
      return
    }
    if (this.loadingMe) return
    this.loadingMe = true
    if (!options.silent) this.setData({ loading: true, error: '' })
    try {
      const data = await api.request('/site/me', {
        cacheMs: options.forceRefresh ? 0 : Number(options.cacheMs || 0),
        forceRefresh: options.forceRefresh === true,
        timeout: REQUEST_TIMEOUT_MS
      })
      this.applyUser(data.user)
      if (this.data.error) this.setData({ error: '' })
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
      this.loadingMe = false
      if (!options.silent) this.setData({ loading: false })
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
        data: { points },
        timeout: REQUEST_TIMEOUT_MS
      })
      await requestPayment(data.payment)
      const confirmed = await api.request('/site/me/recharge/wechatpay/confirm', {
        method: 'POST',
        data: { out_trade_no: data.payment.outTradeNo },
        timeout: REQUEST_TIMEOUT_MS
      })
      this.applyUser(confirmed.user)
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

  selectPoints(event) {
    if (this.data.paying) return
    const points = Number(eventDataset(event).points || 0)
    const option = this.data.pointOptions.find((item) => item.points === points)
    if (option) this.setData({ selectedPoints: points, selectedPrice: option.price })
  },

  toggleCustomPay() {
    this.setData({ showCustomPay: !this.data.showCustomPay })
  },

  applyUser(user) {
    if (userSignature(user) === userSignature(this.data.user)) return
    this.setData({
      user,
      displayName: user.nickname || user.name || 'RecordFlow 用户',
      userInitial: userInitial(user.nickname || user.name),
      balanceYuan: (Number(user.points_balance || 0) / 100).toFixed(2),
      headerSubtitle: '管理账户和点数充值'
    })
  },

  logout() {
    if (!this.data.user) return
    api.clearSession()
    getApp().globalData.user = null
    this.loadingMe = false
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

  openAgreement() {
    wx.navigateTo({ url: '/pages/agreement/agreement' })
  },

  copyUserId() {
    const userId = this.data.user && this.data.user.id
    if (!userId) return
    wx.setClipboardData({
      data: String(userId),
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

function userInitial(value) {
  const text = String(value || 'R').trim()
  return text ? text.slice(0, 1).toUpperCase() : 'R'
}

function userSignature(user) {
  if (!user) return ''
  return [user.id, user.nickname, user.name, user.points_balance].map((value) => String(value || '')).join('|')
}

function isPaymentCancel(error) {
  const message = error && error.message ? error.message : ''
  return message.includes('cancel') || message.includes('取消')
}

function isAuthError(error) {
  if (error && (error.statusCode === 401 || error.statusCode === 403)) return true
  const message = error && error.message ? error.message : ''
  return message.includes('401') || message.toLowerCase().includes('unauthorized')
}
