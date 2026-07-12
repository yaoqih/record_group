const test = require('node:test')
const assert = require('node:assert/strict')

test('export menu opens natively and dispatches the selected format', () => {
  let pageDefinition
  let actionSheetOptions
  global.Page = (definition) => {
    pageDefinition = definition
  }
  global.wx = {
    showActionSheet(options) {
      actionSheetOptions = options
    }
  }

  delete require.cache[require.resolve('../pages/task/task')]
  require('../pages/task/task')

  let selectedFormat = ''
  pageDefinition.openExportMenu.call({
    data: { isExporting: false },
    exportTask(format) {
      selectedFormat = format
    },
    setData() {}
  })

  assert.deepEqual(actionSheetOptions.itemList, ['TXT 文本', 'SRT 字幕', 'Word 文档'])
  actionSheetOptions.success({ tapIndex: 1 })
  assert.equal(selectedFormat, 'srt')

  delete global.Page
  delete global.wx
})

test('export shows one native loading indicator while preparing the file', async () => {
  let pageDefinition
  const events = []
  global.Page = (definition) => {
    pageDefinition = definition
  }
  global.wx = {
    getStorageSync() {
      return 'token'
    },
    showLoading(options) {
      events.push(['showLoading', options])
    },
    nextTick(callback) {
      events.push(['nextTick'])
      callback()
    },
    hideLoading() {
      events.push(['hideLoading'])
    },
    downloadFile(options) {
      events.push(['downloadFile'])
      options.success({ statusCode: 200, tempFilePath: '/tmp/export.txt' })
    },
    openDocument(options) {
      events.push(['openDocument'])
      options.success({})
    }
  }

  delete require.cache[require.resolve('../pages/task/task')]
  require('../pages/task/task')

  const context = {
    data: { isExporting: false, taskId: 'task-1' },
    setData(nextData) {
      Object.assign(this.data, nextData)
    }
  }
  await pageDefinition.exportTask.call(context, 'text')

  assert.deepEqual(events.map((event) => event[0]), [
    'showLoading',
    'nextTick',
    'downloadFile',
    'openDocument',
    'hideLoading'
  ])
  assert.deepEqual(events[0][1], { title: '正在导出', mask: true })
  assert.equal(context.data.isExporting, false)

  delete global.Page
  delete global.wx
})

test('export always hides native loading after a download failure', async () => {
  let pageDefinition
  let hidden = false
  global.Page = (definition) => {
    pageDefinition = definition
  }
  global.wx = {
    getStorageSync() {
      return 'token'
    },
    showLoading() {},
    hideLoading() {
      hidden = true
    },
    downloadFile(options) {
      options.fail({ errMsg: 'network unavailable' })
    }
  }

  delete require.cache[require.resolve('../pages/task/task')]
  require('../pages/task/task')

  const context = {
    data: { isExporting: false, taskId: 'task-1' },
    setData(nextData) {
      Object.assign(this.data, nextData)
    }
  }
  await pageDefinition.exportTask.call(context, 'text')

  assert.equal(hidden, true)
  assert.equal(context.data.isExporting, false)
  assert.equal(context.data.error, 'network unavailable')

  delete global.Page
  delete global.wx
})
