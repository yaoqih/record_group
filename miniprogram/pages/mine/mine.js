const api = require('../../utils/api')

const REQUEST_TIMEOUT_MS = 10000
const PAGE_CACHE_MS = 3000
const PAYMENT_SETTLEMENT_ATTEMPTS = 12
const PAYMENT_SETTLEMENT_INTERVAL_MS = 1000

Page({
  data: {
    user: null,
    displayName: '微信用户',
    userInitial: 'R',
    pointOptions: [
      { points: 100, price: '0.99' },
      { points: 500, price: '4.99', tag: '常用' },
      { points: 1000, price: '9.99' }
    ],
    selectedPoints: 500,
    selectedPrice: '4.99',
    headerSubtitle: '登录后管理账户和充值点数',
    loading: false,
    paying: false,
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
    const points = Number(eventDataset(event).points || 0)
    if (!points) return
    this.setData({ paying: true, error: '' })
    try {
      const data = await api.request('/site/me/recharge/virtual', {
        method: 'POST',
        data: { points },
        timeout: REQUEST_TIMEOUT_MS
      })
      await requestVirtualPayment(data.payment)
      const settlement = await waitForPaymentSettlement(data.payment.outTradeNo)
      if (settlement) {
        this.applyUser(settlement.user)
        getApp().globalData.user = settlement.user
        showToast(this, 'success', `${data.package.points} 点已到账`)
      } else {
        this.setData({ error: '支付成功，微信通知仍在处理中，请稍后下拉刷新余额' })
      }
    } catch (error) {
      if (isPaymentCancel(error)) {
        showToast(this, 'warning', '已取消支付')
      } else {
        this.setData({ error: error.message })
      }
    } finally {
      this.setData({ paying: false })
    }
  },

  selectPoints(event) {
    if (this.data.paying) return
    const points = Number(eventDataset(event).points || 0)
    const option = this.data.pointOptions.find((item) => item.points === points)
    if (option) this.setData({ selectedPoints: points, selectedPrice: option.price })
  },

  applyUser(user) {
    if (userSignature(user) === userSignature(this.data.user)) return
    this.setData({
      user,
      displayName: user.nickname || user.name || 'RecordFlow 用户',
      userInitial: userInitial(user.nickname || user.name),
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

  openPointLedger() {
    wx.navigateTo({ url: '/pages/points/points' })
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

function requestVirtualPayment(payment) {
  return new Promise((resolve, reject) => {
    if (typeof wx.requestVirtualPayment !== 'function') {
      reject(new Error('当前微信版本不支持虚拟支付'))
      return
    }
    if (
      !payment ||
      payment.mode !== 'short_series_goods' ||
      payment.env !== 0 ||
      !payment.offerId ||
      !payment.productId ||
      payment.buyQuantity !== 1 ||
      !Number.isInteger(payment.goodsPrice) ||
      !payment.outTradeNo ||
      !payment.paySig ||
      !payment.signature ||
      !payment.signData
    ) {
      reject(new Error('支付参数不完整，请稍后重试'))
      return
    }
    wx.requestVirtualPayment({
      mode: payment.mode,
      env: payment.env,
      offerId: payment.offerId,
      productId: payment.productId,
      buyQuantity: payment.buyQuantity,
      goodsPrice: payment.goodsPrice,
      currencyType: payment.currencyType,
      outTradeNo: payment.outTradeNo,
      attach: payment.attach,
      paySig: payment.paySig,
      signature: payment.signature,
      signData: payment.signData,
      success: resolve,
      fail: (err) => reject(new Error(err.errMsg || '支付失败'))
    })
  })
}

async function waitForPaymentSettlement(outTradeNo) {
  const encodedTradeNo = encodeURIComponent(outTradeNo)
  for (let attempt = 0; attempt < PAYMENT_SETTLEMENT_ATTEMPTS; attempt += 1) {
    if (attempt > 0) await delay(PAYMENT_SETTLEMENT_INTERVAL_MS)
    try {
      const data = await api.request(`/site/me/payments/${encodedTradeNo}`, {
        forceRefresh: true,
        timeout: REQUEST_TIMEOUT_MS
      })
      if (data.payment && data.payment.status === 'paid') return data
    } catch (error) {
      if (isAuthError(error)) throw error
    }
  }
  return null
}

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds))
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
