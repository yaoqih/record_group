const test = require('node:test')
const assert = require('node:assert/strict')

test('virtual payment refreshes the balance after server settlement', async () => {
  const api = require('../utils/api')
  const originalRequest = api.request
  const requests = []
  let paymentOptions
  let globalUser
  let pageDefinition
  global.Page = (definition) => {
    pageDefinition = definition
  }
  global.getApp = () => ({
    globalData: {
      get user() {
        return globalUser
      },
      set user(value) {
        globalUser = value
      }
    }
  })
  global.wx = {
    requestVirtualPayment(options) {
      paymentOptions = options
      options.success({ errMsg: 'requestVirtualPayment:ok' })
    }
  }
  delete require.cache[require.resolve('../pages/mine/mine')]
  require('../pages/mine/mine')

  const payment = {
    mode: 'short_series_goods',
    env: 0,
    offerId: 'offer-1',
    productId: 'dot_100',
    buyQuantity: 1,
    goodsPrice: 99,
    currencyType: 'CNY',
    outTradeNo: 'order-1',
    attach: '{"points":100}',
    paySig: 'pay-signature',
    signature: 'session-signature',
    signData: '{}'
  }
  api.request = async (path, options) => {
    requests.push([path, options])
    if (path === '/site/me/recharge/virtual') {
      return { package: { points: 100 }, payment }
    }
    return {
      payment: { out_trade_no: 'order-1', status: 'paid' },
      user: { id: 'user-1', points_balance: 100 }
    }
  }

  const context = {
    data: { paying: false, error: '' },
    setData(nextData) {
      Object.assign(this.data, nextData)
    },
    applyUser(user) {
      this.data.user = user
    },
    selectComponent() {
      return null
    }
  }

  try {
    await pageDefinition.recharge.call(context, {
      currentTarget: { dataset: { points: 100 } }
    })

    assert.equal(requests[0][0], '/site/me/recharge/virtual')
    assert.deepEqual(requests[0][1].data, { points: 100 })
    assert.equal(requests[1][0], '/site/me/payments/order-1')
    assert.equal(paymentOptions.productId, 'dot_100')
    assert.equal(paymentOptions.buyQuantity, 1)
    assert.equal(context.data.user.points_balance, 100)
    assert.equal(context.data.paying, false)
    assert.equal(globalUser.points_balance, 100)
  } finally {
    api.request = originalRequest
    delete global.Page
    delete global.getApp
    delete global.wx
  }
})
