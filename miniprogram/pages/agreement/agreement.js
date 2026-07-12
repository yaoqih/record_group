const api = require('../../utils/api')
const agreement = require('../../utils/agreement')

const REQUEST_TIMEOUT_MS = 10000

Page({
  data: {
    version: agreement.AGREEMENT_VERSION,
    effectiveDate: agreement.AGREEMENT_EFFECTIVE_DATE,
    operator: agreement.AGREEMENT_OPERATOR,
    contact: agreement.AGREEMENT_CONTACT,
    contactNote: agreement.AGREEMENT_CONTACT_NOTE,
    accepted: false,
    accepting: false,
    error: ''
  },

  onShow() {
    this.setData({ accepted: agreement.hasAcceptedCurrentAgreement() })
  },

  async acceptAgreement() {
    if (this.data.accepting) return
    this.setData({ accepting: true, error: '' })
    try {
      if (api.getToken()) {
        await api.request('/site/me/agreement', {
          method: 'POST',
          data: {
            agreement_version: agreement.AGREEMENT_VERSION,
            agreement_accepted: true
          },
          timeout: REQUEST_TIMEOUT_MS
        })
      }
      agreement.acceptCurrentAgreement()
      this.setData({ accepted: true })
      wx.showToast({ title: '已同意当前版本', icon: 'success' })
      setTimeout(() => {
        const pages = getCurrentPages()
        if (pages.length > 1) wx.navigateBack()
      }, 500)
    } catch (error) {
      this.setData({ error: error.message || '保存同意状态失败' })
    } finally {
      this.setData({ accepting: false })
    }
  },

  withdrawAgreement() {
    wx.showModal({
      title: '撤回同意',
      content: '撤回后将无法继续登录或上传新录音，但不影响撤回前基于你同意已完成的合法处理。',
      confirmText: '确认撤回',
      confirmColor: '#b42318',
      success: (result) => {
        if (!result.confirm) return
        agreement.clearCurrentAgreementAcceptance()
        this.setData({ accepted: false, error: '' })
        wx.showToast({ title: '已撤回同意', icon: 'none' })
      }
    })
  }
})
