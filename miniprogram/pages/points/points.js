const api = require('../../utils/api')

Page({
  data: { entries: [], loading: false, loadingMore: false, hasMore: false, nextCursor: '', error: '' },

  onShow() { this.loadLedger() },

  async onPullDownRefresh() {
    await this.loadLedger(true)
    wx.stopPullDownRefresh()
  },

  async loadLedger(forceRefresh = false) {
    if (!api.getToken()) {
      this.setData({ entries: [], hasMore: false, nextCursor: '', error: '请先登录后查看点数明细' })
      return
    }
    this.setData({ loading: true, error: '' })
    try {
      const data = await api.request('/site/me/point-ledger?limit=20', { forceRefresh, timeout: 10000 })
      this.setData({
        entries: (data.entries || []).map(formatEntry),
        hasMore: Boolean(data.has_more),
        nextCursor: data.next_cursor || ''
      })
    } catch (error) {
      this.setData({ error: error.message || '加载点数明细失败' })
    } finally {
      this.setData({ loading: false })
    }
  },

  async loadMore() {
    if (this.data.loading || this.data.loadingMore || !this.data.hasMore || !this.data.nextCursor) return
    this.setData({ loadingMore: true, error: '' })
    try {
      const cursor = encodeURIComponent(this.data.nextCursor)
      const data = await api.request(`/site/me/point-ledger?limit=20&cursor=${cursor}`, { timeout: 10000 })
      this.setData({
        entries: this.data.entries.concat((data.entries || []).map(formatEntry)),
        hasMore: Boolean(data.has_more),
        nextCursor: data.next_cursor || ''
      })
    } catch (error) {
      this.setData({ error: error.message || '加载更多失败' })
    } finally {
      this.setData({ loadingMore: false })
    }
  }
})

function formatEntry(entry) {
  const delta = Number(entry.delta || 0)
  return {
    id: entry.id,
    deltaLabel: `${delta > 0 ? '+' : ''}${delta}`,
    deltaClass: delta >= 0 ? 'positive' : 'negative',
    kindLabel: entry.display_title || ({
      seed: '赠送',
      signup_bonus: '注册赠送',
      dev_signup_bonus: '注册赠送',
      recharge: '充值',
      wechatpay_recharge: '微信充值',
      consume: '转写消耗',
      transcription_refund: '转写退还',
      admin_adjustment_credit: '后台发放',
      admin_adjustment_debit: '后台扣减'
    })[entry.kind] || '点数变动',
    note: entry.display_note || entry.note || '无备注',
    createdLabel: formatDate(entry.created_at)
  }
}

function formatDate(value) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value || '')
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}
