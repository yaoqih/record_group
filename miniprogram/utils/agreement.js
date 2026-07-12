const AGREEMENT_VERSION = 'v2'
const AGREEMENT_EFFECTIVE_DATE = '2026年7月11日'
const AGREEMENT_STORAGE_KEY = 'recordflow_agreement_acceptance'

const AGREEMENT_OPERATOR = '服务提供方'
const AGREEMENT_CONTACT = '客服邮箱：1375626371@qq.com'
const AGREEMENT_CONTACT_NOTE = '如需行使个人信息相关权利，请在邮件中说明请求事项，我们将在核验身份后依法处理。'

function getAcceptance() {
  const stored = wx.getStorageSync(AGREEMENT_STORAGE_KEY)
  if (!stored) return null
  if (typeof stored === 'string') {
    return { version: stored, accepted: true, accepted_at: '' }
  }
  if (typeof stored !== 'object') return null
  return stored
}

function hasAcceptedCurrentAgreement() {
  const acceptance = getAcceptance()
  return Boolean(
    acceptance && acceptance.accepted === true && acceptance.version === AGREEMENT_VERSION
  )
}

function acceptCurrentAgreement() {
  const acceptance = {
    version: AGREEMENT_VERSION,
    accepted: true,
    accepted_at: new Date().toISOString()
  }
  wx.setStorageSync(AGREEMENT_STORAGE_KEY, acceptance)
  return acceptance
}

function clearCurrentAgreementAcceptance() {
  const acceptance = getAcceptance()
  if (acceptance && acceptance.version === AGREEMENT_VERSION) {
    wx.removeStorageSync(AGREEMENT_STORAGE_KEY)
  }
}

function loginPayload() {
  return {
    agreement_version: AGREEMENT_VERSION,
    agreement_accepted: true
  }
}

module.exports = {
  AGREEMENT_CONTACT,
  AGREEMENT_CONTACT_NOTE,
  AGREEMENT_EFFECTIVE_DATE,
  AGREEMENT_OPERATOR,
  AGREEMENT_VERSION,
  acceptCurrentAgreement,
  clearCurrentAgreementAcceptance,
  getAcceptance,
  hasAcceptedCurrentAgreement,
  loginPayload
}
