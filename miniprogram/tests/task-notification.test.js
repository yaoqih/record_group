const test = require('node:test')
const assert = require('node:assert/strict')

function loadTaskPage() {
  let pageDefinition
  global.Page = (definition) => {
    pageDefinition = definition
  }
  delete require.cache[require.resolve('../pages/task/task')]
  require('../pages/task/task')
  return pageDefinition
}

function createPageContext() {
  return {
    data: {
      taskId: 'task-1',
      task: { id: 'task-1', status: 'uploaded' },
      starting: false,
      canStart: true,
      notificationAvailable: true,
      notificationConfig: { enabled: true, template_id: 'template-1' },
      notifyOnComplete: true
    },
    setData(nextData) {
      Object.assign(this.data, nextData)
    },
    startPollingIfNeeded() {},
    selectComponent() {
      return null
    }
  }
}

test('accepted subscription is requested in the start gesture and sent to the API', async () => {
  const api = require('../utils/api')
  const originalRequest = api.request
  const calls = []
  global.wx = {
    requestSubscribeMessage(options) {
      calls.push('subscribe')
      assert.deepEqual(options.tmplIds, ['template-1'])
      options.success({ 'template-1': 'accept' })
    }
  }
  const pageDefinition = loadTaskPage()
  api.request = async (path, options) => {
    calls.push('start')
    assert.equal(path, '/site/me/tasks/task-1/start')
    assert.deepEqual(options.data, {
      confirm_points: true,
      notify_on_complete: true,
      notification_template_id: 'template-1'
    })
    return { task: { id: 'task-1', status: 'queued' } }
  }

  try {
    await pageDefinition.startTask.call(createPageContext())
    assert.deepEqual(calls, ['subscribe', 'start'])
  } finally {
    api.request = originalRequest
    delete global.Page
    delete global.wx
  }
})

test('rejected subscription does not block transcription', async () => {
  const api = require('../utils/api')
  const originalRequest = api.request
  let startPayload
  global.wx = {
    requestSubscribeMessage(options) {
      options.success({ 'template-1': 'reject' })
    }
  }
  const pageDefinition = loadTaskPage()
  api.request = async (path, options) => {
    startPayload = options.data
    return { task: { id: 'task-1', status: 'queued' } }
  }

  try {
    const context = createPageContext()
    await pageDefinition.startTask.call(context)
    assert.deepEqual(startPayload, {
      confirm_points: true,
      notify_on_complete: false,
      notification_template_id: ''
    })
    assert.equal(context.data.task.status, 'queued')
    assert.equal(context.data.starting, false)
  } finally {
    api.request = originalRequest
    delete global.Page
    delete global.wx
  }
})
